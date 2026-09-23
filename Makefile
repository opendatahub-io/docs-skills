.PHONY: help
help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: skillsaw
skillsaw: ## Run skillsaw linter on skills and plugins
	@echo "Running skillsaw..."
	@if [ -n "$${SKILLSAW_BIN:-}" ]; then \
		"$${SKILLSAW_BIN}"; \
	else \
		uvx skillsaw; \
	fi

.PHONY: skillsaw-fix
skillsaw-fix: ## Auto-fix fixable skillsaw issues
	@echo "Fixing skillsaw issues..."
	@if [ -n "$${SKILLSAW_BIN:-}" ]; then \
		"$${SKILLSAW_BIN}" fix; \
	else \
		uvx skillsaw fix; \
	fi

.PHONY: typecheck
typecheck: ## Typecheck the pi extensions against the pinned pi types
	@echo "Typechecking extensions..."
	@if [ ! -x node_modules/.bin/tsc ]; then \
		echo "tsc not found. Install the dev dependencies with: npm ci"; \
		exit 1; \
	fi
	@node_modules/.bin/tsc -p tsconfig.json && echo "Extensions typecheck clean."

.PHONY: lint
lint: ## Run skillsaw, typecheck, ruff syntax checker and formatter, and shellcheck
	@$(MAKE) skillsaw
	@$(MAKE) typecheck
	@echo "Running ruff syntax checker on Python scripts..."
	@if command -v ruff >/dev/null 2>&1; then \
		ruff check --no-cache .; \
	else \
		echo "ruff not found, skipping Python syntax checking. Install with: pip install ruff"; \
		exit 1; \
	fi
	@echo "Running ruff format checker on Python scripts..."
	@ruff format --no-cache --check --diff .
	@echo "Running shellcheck on shell scripts..."
	@if command -v shellcheck >/dev/null 2>&1; then \
		find . -name '*.sh' -type f -exec shellcheck {} + && echo "All checks passed!"; \
	else \
		echo "shellcheck not found, skipping shell script linting. Install with: dnf install ShellCheck"; \
		exit 1; \
	fi

.PHONY: sync-styles
sync-styles: ## Download the published Vale packages into styles/
	@vale --config vale/docs.ini sync

.PHONY: test
test: ## Run pytest test suite
	python3 -m pytest tests/ -v


.DEFAULT_GOAL := help

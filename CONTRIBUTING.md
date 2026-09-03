# Contributing to docs-skills

Thank you for your interest in contributing to docs-skills! This plugin provides documentation review, writing, and workflow tools for Codex and Claude Code.

## Getting Started

1. **Fork the repository** on GitHub.
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/<your-username>/docs-skills.git
   cd docs-skills
   ```
3. **Create a branch** for your work:
   ```bash
   git checkout -b my-change
   ```

## Repository Layout

```text
.claude-plugin/              Claude Code plugin and marketplace metadata
.codex-plugin/               Codex plugin metadata
.agents/plugins/             Codex marketplace metadata
skills/                      Skill directories (SKILL.md + scripts/)
agents/                      Subagent definitions
reference/                   Shared domain knowledge
hooks/                       Claude Code event hooks (not loaded by Codex)
eval/                        Evaluation test cases
```

Read [AGENTS.md](AGENTS.md) for architecture details and conventions.

## Ways to Contribute

- **Add or improve a skill** in `skills/<skill-name>/`
- **Add or improve an agent** in `agents/`
- **Add or fix a script** in `skills/<skill-name>/scripts/`
- **Add evaluation test cases** in `eval/cases/`
- **Fix a bug** or improve existing functionality
- **Improve documentation**

## Development Setup

### Prerequisites

- **Python 3.10+** with [ruff](https://docs.astral.sh/ruff/) (`pip install ruff`)
- **[uv](https://docs.astral.sh/uv/)** for running PEP 723 scripts
- **shellcheck** (`dnf install ShellCheck` on Fedora, `apt install shellcheck` on Debian/Ubuntu)
- **Git**

### Validate Your Changes

Before submitting, always run:

```bash
make lint
```

The `lint` target runs:
- **manifest checks** prevent Claude Code and Codex metadata from drifting
- **runtime compatibility checks** verify platform-specific skills link to their Codex guidance
- **skillsaw** validates plugin structure and skill frontmatter
- **ruff** checks and formats Python code
- **shellcheck** lints shell scripts

When changing release metadata, edit `scripts/sync_plugin_manifests.py`, run `python3 scripts/sync_plugin_manifests.py`, and commit all generated manifests.

### Test Locally

For Codex:

```bash
codex plugin marketplace add /absolute/path/to/docs-skills
codex plugin add docs-skills@opendatahub-docs
```

Start a new thread to load the updated skills.

For Claude Code:

```bash
claude --plugin-dir /absolute/path/to/docs-skills
```

## Submitting Your Contribution

1. **Run validation** before committing:
   ```bash
   make lint
   ```
2. **Commit your changes** with a clear, descriptive commit message.
3. **Push to your fork** and open a Pull Request against `main`.

### Commit Messages

Write concise commit messages that explain *why* the change was made:

- `feat:` for new skills or features
- `fix:` for bug fixes
- `docs:` for documentation changes
- `chore:` for maintenance tasks

Example: `feat: add retry logic to docs-orchestrator workflow resumption`

## Style and Conventions

### Naming

- Use lowercase kebab-case for skill names: `docs-workflow-requirements`
- Use lowercase kebab-case for agent names: `docs-planner`

### Python

- Format with `ruff format`
- Pass `ruff check` with no errors
- Use Python 3.10+ type annotations
- Scripts with external deps must include PEP 723 inline metadata

### Shell Scripts

- Always use `set -euo pipefail`
- Pass `shellcheck` with no warnings

### Skills

- Each skill lives in `skills/<name>/` with a `SKILL.md` and optional `scripts/` directory
- `SKILL.md` must include YAML frontmatter with at least `name` and `description`

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).

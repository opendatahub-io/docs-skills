# Contributing to docs-skills

Thank you for your interest in contributing to docs-skills! This plugin provides documentation review, writing, and workflow tools for Claude Code.

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
.claude-plugin/plugin.json   Plugin packaging metadata
skills/docs-engine/          Shared runtime: lib, prompts, schemas, languages
skills/<skill>/SKILL.md      Skill definitions with frontmatter
tests/                       pytest suite and the synthetic fixture repository
```

Read [AGENTS.md](AGENTS.md) for architecture details and conventions.

## Ways to Contribute

- **Add a language** — two files under `skills/docs-engine/`: an entry in
  `scripts/lib/ast/languages.yaml` for the parse rules, and a
  `languages/<lang>.md` for the documentation conventions the writer prompt reads
- **Add or improve a skill** in `skills/<skill-name>/`
- **Add or fix a script** in `skills/<skill-name>/scripts/`, or in the engine's
  `scripts/lib/` when several skills need it
- **Improve a prompt or schema** in `skills/docs-engine/prompts/` and
  `skills/docs-engine/schemas/`
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
- **skillsaw** validates plugin structure and skill frontmatter
- **ruff** checks and formats Python code
- **shellcheck** lints shell scripts

### Test Locally (Claude Code)

To test a skill with Claude Code before submitting:

1. Open `claude`
2. Install the local plugin: `claude plugin install /path/to/docs-skills`
3. Test your skill
4. Remove the local plugin when done

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

Example: `feat: add a Rust language file to the writer`

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
- `SKILL.md` must include YAML frontmatter with at least `name` and `description`,
  and `name` must match the directory name
- Every skill name carries a `docs-` prefix. Skills install into one flat
  directory shared with other plugins, and a name collision makes the installer
  skip this plugin whole rather than the colliding skill
- No subagent dispatch and no `${CLAUDE_PLUGIN_ROOT}`. Model steps go through
  the engine's `lib/run/step.py`; paths resolve from the file that uses them

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).

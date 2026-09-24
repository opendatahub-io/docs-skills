# Contributing to docs-skills

Thank you for your interest in contributing to docs-skills. This package generates documentation from a code repository, and runs inside [pi](https://pi.dev).

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
package.json                 pi package manifest: name, version, pi.extensions, pi.skills
extensions/                  pi extensions: the two commands, and the lint-on-write hook
vale/docs.ini                The Vale packages and rule levels a run composes from
styles/                      The Vale styles this package owns
skills/docs-engine/          Shared runtime: lib, prompts, schemas, languages, reference
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
- **skillsaw** validates package structure and skill frontmatter
- **tsc** typechecks the pi extensions against the pinned pi types
- **ruff** checks and formats Python code
- **shellcheck** lints shell scripts

### Test locally

A local source is a pi settings entry pointing at the directory. Nothing is
copied, so this is run once and edits to the checkout are live:

```bash
npm ci
pi install .
```

Skills, extensions and prompts are read when a session starts, so run `/reload`
in an open session to pick up a change. Every script also runs from a plain
shell, which is the faster loop for anything below the command layer:

```bash
python3 skills/docs/scripts/build.py --repo . --topic "the chain" --dry-run
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
- Every skill name carries a `docs-` prefix, with `docs` itself as the entry
  point. Skills install into one flat directory shared with other packages, and
  a name collision makes the installer skip this package whole rather than the
  colliding skill
- No subagent dispatch and no harness variables. Model steps go through the
  engine's `lib/run/step.py`; paths resolve from the file that uses them

## License

By contributing, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).

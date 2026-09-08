# docs-skills

A Claude Code plugin providing documentation review, writing, and workflow tools. This file defines the shared project conventions for all AI coding agents. For Claude Code-specific instructions, see [CLAUDE.md](CLAUDE.md).

## Repository structure

```text
.claude-plugin/plugin.json   Plugin packaging metadata (name, version, description)
skills/<skill>/SKILL.md      Skill definitions with frontmatter
agents/<agent>.md            Subagent definitions with frontmatter
reference/                   Shared domain knowledge (frameworks, templates, guides)
hooks/hooks.json             Plugin-level Claude Code event hooks
eval/                        Evaluation test cases and harness config

skills/docs-engine/          Shared runtime for the generator. Not invoked directly
  scripts/lib/git/           git_context.py, api_surface.py
  scripts/lib/md/            docs_meta.py, language_file.py, fences.py, render.py
  scripts/lib/ast/           languages.yaml, per-language parse rules
  scripts/lib/run/step.py    The single model call. Prompt in, validated JSON out
  languages/<lang>.md        Per-language documentation conventions
  prompts/<step>.md          One file per model step
  schemas/<step>-out.json    What each model step must return
  config/                    Path filters, example .docs-gen.yaml, gitignore fragment
```

The generator's shared code lives inside `skills/docs-engine/` rather than at the
repository root. An installer copies each skill directory on its own and drops
symlinks on the way, so a tree above the skills does not survive installation. It
does place every skill as a flat sibling, which is what the generator skills use
to reach the engine. The rules for doing that differ from the sections below.

## Calling scripts from skills

The runtime working directory is the **project root**, not the skill directory. Bare relative paths like `scripts/foo.py` will fail. Always use a substitution variable:

### Claude Code

- **`${CLAUDE_SKILL_DIR}`** — the directory containing the skill's `SKILL.md`. Use for scripts bundled with the same skill.
- **`${CLAUDE_PLUGIN_ROOT}`** — the plugin's installation directory (repo root). Use for cross-skill calls.

```bash
# Same-skill call (stdlib-only script)
python3 ${CLAUDE_SKILL_DIR}/scripts/detect_language.py --repo /path/to/repo

# Same-skill call (PEP 723 script with external deps)
uv run --script ${CLAUDE_SKILL_DIR}/scripts/jira_reader.py --issue PROJ-123

# Cross-skill call
python3 ${CLAUDE_PLUGIN_ROOT}/skills/learn-code/scripts/detect_language.py --repo /path
```

### Cursor

Use paths relative to the repository root (workspace):

```bash
python3 skills/learn-code/scripts/detect_language.py --repo /path/to/repo
```

## The documentation generator

Its skills follow different rules from the ticket-driven pipeline, and the
difference is deliberate.

**No harness variables.** Nothing reads `${CLAUDE_PLUGIN_ROOT}` or
`${CLAUDE_SKILL_DIR}`, because no harness sets a plugin root. Python scripts
find the engine with a walk from `__file__`:

```python
def _find_engine():
    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        if (base / "scripts" / "lib" / "run" / "step.py").exists():
            return base
        sibling = base / "docs-engine"
        if (sibling / "scripts" / "lib" / "run" / "step.py").exists():
            return sibling
```

The same walk resolves `skills/docs-engine/` in a checkout and
`<skills-dir>/docs-engine/` after an install, so there is no build step and no
duplicated copy. `SKILL.md` uses `$(dirname "$0")/../docs-engine/`.

**Skill names carry a `docs-` prefix.** A destination-path collision makes the
installer skip the entire plugin with a warning rather than just the colliding
skill, so an unprefixed name like `changelog` can make every skill here vanish
from an installation.

**No subagent dispatch.** No `Agent`, no `Task`, no fan-out. Where the plan
calls for per-module work, it is a sequential loop over the engine's `step.py`.
Parallelism is the harness's to supply; the skill supplies a list.

**Every model call goes through the engine's `lib/run/step.py`.** Prompt in, JSON out,
validated against a schema, one retry with the errors appended. A step that
needs a model gets a prompt in `prompts/` and a schema in `schemas/`. Nothing
calls a model any other way.

**`allowed-tools` stays within `Bash, Read, Write`.** Every harness offers those
three under some name.

**Guards live in scripts, never in prompts.** Whether a file may be written,
which bytes may move, and whether doc comments reach source are decided by
`docs-write`'s script. A prompt instruction is a request; a function that never
receives the surrounding text is a guarantee.

## Skill and agent naming

**Skills** (invoked via the Skill tool) use bare names: `docs-workflow-requirements`, `jira-reader`, `learn-code`. Qualified names (`docs-skills:docs-workflow-requirements`) also work. Use bare names in workflow YAML step lists and skill-to-skill invocations.

**Agents** (invoked via the Agent tool's `subagent_type`) require fully-qualified names with the plugin prefix: `docs-skills:technical-reviewer`, `docs-skills:docs-writer`. Bare names like `technical-reviewer` will fail with "Agent type not found".

## Contributing rules

- Use kebab-case for skill and agent names
- Bump version in `.claude-plugin/plugin.json` when making changes
- New Python scripts with external dependencies must use PEP 723 inline metadata
- New stdlib-only scripts use plain `python3` invocation
- Run `make lint` before committing (skillsaw + ruff + shellcheck)
- Install test dependencies with `pip install -r requirements.txt` before running `make test`
- Use `feat:`, `fix:`, `docs:`, `chore:` commit prefixes
- Generator skills carry no harness variables and no subagent dispatch (see above)
- A new language is two files under `skills/docs-engine/`: an entry in
  `scripts/lib/ast/languages.yaml` and a `languages/<lang>.md` whose frontmatter
  validates against `schemas/language-file.json`
- When referencing Python in install steps, always use `python3`

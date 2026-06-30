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
```

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

## Skill and agent naming

**Skills** (invoked via the Skill tool) use bare names: `docs-workflow-requirements`, `jira-reader`, `learn-code`. Qualified names (`docs-skills:docs-workflow-requirements`) also work. Use bare names in workflow YAML step lists and skill-to-skill invocations.

**Agents** (invoked via the Agent tool's `subagent_type`) require fully-qualified names with the plugin prefix: `docs-skills:technical-reviewer`, `docs-skills:docs-writer`. Bare names like `technical-reviewer` will fail with "Agent type not found".

## Contributing rules

- Use kebab-case for skill and agent names
- Bump version in `.claude-plugin/plugin.json` when making changes
- New Python scripts with external dependencies must use PEP 723 inline metadata
- New stdlib-only scripts use plain `python3` invocation
- Run `make lint` before committing (skillsaw + ruff + shellcheck)
- Use `feat:`, `fix:`, `docs:`, `chore:` commit prefixes
- When referencing Python in install steps, always use `python3`

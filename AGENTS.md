# docs-skills

A Codex and Claude Code plugin providing documentation review, writing, and workflow tools. This file defines the shared project conventions for all AI coding agents. For Claude Code-specific instructions, see [CLAUDE.md](CLAUDE.md).

## Repository structure

```text
.claude-plugin/plugin.json   Plugin packaging metadata (name, version, description)
.claude-plugin/marketplace.json  Claude Code marketplace metadata
.codex-plugin/plugin.json    Codex plugin packaging metadata
.agents/plugins/marketplace.json  Codex marketplace metadata
skills/<skill>/SKILL.md      Skill definitions with frontmatter
agents/<agent>.md            Subagent definitions with frontmatter
reference/                   Shared domain knowledge (frameworks, templates, guides)
hooks/hooks.json             Plugin-level Claude Code event hooks
eval/                        Evaluation test cases and harness config
```

## Calling scripts from skills

Paths in `SKILL.md` are relative to that skill's directory. Hosts must resolve
them against the loaded `SKILL.md` location before invoking the shell; the
target project remains the working directory.

```bash
# Same-skill call (stdlib-only script)
python3 scripts/detect_language.py --repo /path/to/repo

# Same-skill call (PEP 723 script with external deps)
uv run --script scripts/jira_reader.py --issue PROJ-123

# Cross-skill call
python3 ../learn-code/scripts/detect_language.py --repo /path
```

Claude Code, Codex, and other Agent Skills hosts use the same convention. See
[runtime compatibility](reference/runtime-compatibility.md).

## Skill and agent naming

**Skills** (invoked via the Skill tool) use bare names: `docs-workflow-requirements`, `jira-reader`, `learn-code`. Qualified names (`docs-skills:docs-workflow-requirements`) also work. Use bare names in workflow YAML step lists and skill-to-skill invocations.

**Agents in Claude Code** (invoked via the Agent tool's `subagent_type`) require fully-qualified names with the plugin prefix: `docs-skills:technical-reviewer`, `docs-skills:docs-writer`. Bare names like `technical-reviewer` will fail with "Agent type not found".

**Agents in Codex** use collaboration subagents. The invoking skill must direct the subagent to load the matching file from `agents/`; see [runtime compatibility](reference/runtime-compatibility.md).

## Contributing rules

- Use kebab-case for skill and agent names
- Bump `PLUGIN_VERSION` in `scripts/sync_plugin_manifests.py` when making changes, then regenerate both platform manifests
- Run `python3 scripts/sync_plugin_manifests.py --check` before committing
- New Python scripts with external dependencies must use PEP 723 inline metadata
- New stdlib-only scripts use plain `python3` invocation
- Run `make lint` before committing (skillsaw + ruff + shellcheck)
- Install test dependencies with `pip install -r requirements.txt` before running `make test`
- Use `feat:`, `fix:`, `docs:`, `chore:` commit prefixes
- When referencing Python in install steps, always use `python3`

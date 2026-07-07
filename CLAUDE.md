# docs-skills

Follow the shared project conventions in @AGENTS.md for repository structure, skill naming, contributing rules, and general script invocation patterns. The instructions below apply only to Claude Code.

## Repository structure

```text
.claude-plugin/plugin.json   Plugin packaging metadata
skills/                      Skill directories (each contains SKILL.md + scripts/)
agents/                      Subagent definitions (.md files)
reference/                   Shared domain knowledge (frameworks, templates, style guides)
hooks/                       Plugin-level Claude Code event hooks
eval/                        Evaluation test cases and harness config
```

## Coding guidelines

Behavioral rules to reduce common mistakes. These bias toward caution over speed — use judgment for trivial tasks.

### Think before coding

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity first

- No features beyond what was asked.
- No duplication of existing functionality.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical changes

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## Script calls in skills

The runtime working directory is the **project root**, not the skill directory. Bare relative paths like `scripts/foo.py` will fail. Use the appropriate substitution variable:

- **`${CLAUDE_SKILL_DIR}`** — resolves to the directory containing the skill's `SKILL.md`. Use for scripts bundled with the same skill.
- **`${CLAUDE_PLUGIN_ROOT}`** — resolves to the plugin's installation directory (repo root). Use for cross-skill calls, reference files, and hook/MCP/LSP subprocess contexts.

### PEP 723 scripts (external dependencies)

Scripts with external dependencies use PEP 723 inline metadata and must be invoked via `uv run --script`:

```bash
uv run --script ${CLAUDE_SKILL_DIR}/scripts/jira_reader.py --issue PROJ-123
```

Do **not** insert a `--` separator between the script path and its arguments. With `uv run --script <path>`, uv passes everything after the path straight to the script, so a `--` ends up in the script's `argv`. Subcommand-first scripts (e.g. `git_pr_reader resolve`) tolerate it, but flag-first scripts like `jira_reader --issue` fail with `error: unrecognized arguments: --`. The lint workflow rejects any `uv run --script <path> -- …` invocation.

### Stdlib-only scripts

Scripts with no external dependencies use plain `python3`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/detect_language.py --repo /path/to/repo
```

### Cross-skill calls

```bash
uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/jira-reader/scripts/jira_reader.py --issue PROJ-123
python3 ${CLAUDE_PLUGIN_ROOT}/skills/learn-code/scripts/detect_language.py --repo /path
```

## Referencing files from agents and skills

`@` references (e.g., `@reference/file.md`) are a **user input feature** resolved by the Claude Code CLI when typing in the chat prompt. They are NOT resolved inside agent or skill body text — the body becomes the system prompt verbatim.

**In skills (SKILL.md):** Use relative markdown links for progressive disclosure. Claude follows these by reading the files on demand:

```markdown
See [reference/asciidoc-reference.md](../../reference/asciidoc-reference.md)
```

**In agents (subagents):** Use `${CLAUDE_PLUGIN_ROOT}` paths with explicit Read instructions. Agent bodies become system prompts where markdown links are not auto-resolved:

```markdown
## CRITICAL: Mandatory reference loading

Read: ${CLAUDE_PLUGIN_ROOT}/reference/jtbd-framework.md
Read: ${CLAUDE_PLUGIN_ROOT}/reference/asciidoc-reference.md

If either file cannot be read, STOP and report the error.
```

**Reference files** under `reference/` contain domain knowledge (frameworks, templates, style guides) shared across agents. Agents MUST read them at runtime via the Read tool — they are not automatically injected.

## Skill logic must live in scripts

**If a step can be scripted, it MUST be a script — not prose for Claude to execute by hand.** Any procedural logic — argument parsing, mode determination, input validation, path computation, directory creation, conditionals, state transitions, decision rules, template rendering — belongs in a script under `skills/<skill-name>/scripts/`, never as step-by-step instructions in SKILL.md. Text that walks Claude through a deterministic procedure is a bug: it drifts under context compaction, cannot be tested, and produces inconsistent results. The test: *if you could write a function that does it, write the function.*

**All JSON reading and writing MUST go through a script.** Never hand-author a JSON file (sidecars, progress files, config, manifests) from a template in SKILL.md, and never hand-parse JSON in prose. Hand-authored JSON silently drifts from its schema (see the pipeline-diagnostics and security-review sidecar drift that motivated this rule); a script derives every field deterministically and can be unit-tested. SKILL.md may show a JSON *example* for documentation, but the actual read/write is always a script call.

The SKILL.md itself should only contain:

- Frontmatter and description
- Instructions to run the script and act on its output
- Domain knowledge that is genuinely Claude's judgment — prompt templates, checklists, review criteria, agent dispatch instructions, when to STOP and ask the user
- Output verification (that the script produced what was expected)

Do NOT embed procedural logic (conditionals, path construction, validation, JSON assembly, decision tables) inline in SKILL.md. If you find yourself writing "if X then set Y" or a JSON block with placeholders to fill in, stop and move it to a script.

## Workflow step skills must write step-result.json

All `docs-workflow-*` step skills must write a `step-result.json` sidecar alongside their primary output. This lightweight metadata file lets the orchestrator read structured results without parsing markdown.

- Follow the common schema defined in `skills/docs-orchestrator/schema/step-result-schema.md`
- Every sidecar must include `schema_version`, `step`, `ticket`, and `completed_at`
- Each step's full JSON Schema lives in the step skill's own `schema/` directory (e.g., `skills/docs-workflow-requirements/schema/requirements.json`)

## Step schemas are mandatory

Every `docs-workflow-*` step skill must have both an **input schema** and an **output schema** in its `schema/` directory:

- **Output schema** (`<step-name>.json`): defines the `step-result.json` sidecar contract
- **Input schema** (`<step-name>-input.json`): defines the CLI args contract — what `build_step_args()` produces and what the step expects to receive

When adding or modifying a step, update both schemas. The full index is at `skills/docs-orchestrator/schema/step-result-schema.md`.

## Orchestrator steps must have tests

Every function in `scripts/docs_orchestrator.py` must have test coverage in `tests/test_docs_orchestrator.py`. This includes:

- All post-processor functions (`_pp_*`)
- All action constructors (`make_run_skill`, `make_complete`, `make_fail`)
- All pure helpers (`build_step_args`, `evaluate_when`, `check_input_deps`, etc.)
- All filesystem helpers (`atomic_write_json`, `read_sidecar`, `read/write_progress`, etc.)

When adding or modifying an orchestrator function, add or update corresponding tests. Tests gate in CI via `.github/workflows/test.yml` — PRs with failing tests will not merge. Run `make test` locally before pushing.

## Schema conformance tests

`tests/test_schema_conformance.py` validates that all step JSON Schemas are well-formed and that sidecars conform to them. It auto-discovers schemas from `skills/docs-workflow-*/schema/` and validates golden examples against them. When adding or modifying a step schema, update the corresponding golden example in the test file. See `skills/docs-orchestrator/schema/step-result-schema.md` for full details.

The `validate_sidecar()` helper in `tests/schema_helpers.py` can be imported by other test files to validate sidecar dicts against their schemas.

## Authoring skills, agents, and plugins

When creating or modifying skills, agents, hooks, or plugin components, follow the official Anthropic documentation. Do NOT rely on training data for schemas, frontmatter fields, or best practices — use WebFetch to consult the canonical docs.

### Canonical documentation references

| Component | Documentation |
|---|---|
| Skill authoring best practices | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices.md |
| Skills overview and structure | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview.md |
| Skills in Claude Code | https://code.claude.com/docs/en/skills.md |
| Plugin schema and reference | https://code.claude.com/docs/en/plugins-reference.md |
| Plugin creation guide | https://code.claude.com/docs/en/plugins.md |
| Subagents | https://code.claude.com/docs/en/sub-agents.md |
| Hooks | https://code.claude.com/docs/en/hooks.md |

### Skill files

New skills must use the directory-based format: `skills/<skill-name>/SKILL.md`. Each skill directory contains a SKILL.md and optional `scripts/`, `config/`, `defaults/`, `hooks/`, `schemas/`, `references/` subdirectories.

### Agent files (subagents)

Key constraints:
- The markdown body becomes the agent's system prompt — agents do NOT receive the full Claude Code system prompt
- `@` references in agent body text are NOT resolved — use `${CLAUDE_PLUGIN_ROOT}` paths with explicit Read instructions
- Plugin agents cannot use `hooks`, `mcpServers`, or `permissionMode` frontmatter fields
- Subagents cannot spawn other subagents

### Hooks

Plugin-level hooks are registered in `hooks/hooks.json`. The orchestrator also has a `setup-hooks.sh` script that installs project-level hooks for workflow completion and source resolution.

## Debugging

When investigating issues in this repo:

- **Wrong workflow output**: Read the relevant skill's `SKILL.md` for expected behavior. Check the step skill's `schema/<step-name>.json` for the output schema (index at `skills/docs-orchestrator/schema/step-result-schema.md`). Verify `step-result.json` was written correctly.
- **Orchestrator stuck or skipping steps**: Check the workflow progress JSON in `.agent_workspace/<TICKET>/workflow/`. Verify step dependencies and `when:` conditions in the workflow YAML.
- **Script failures**: Check that PEP 723 scripts are invoked with `uv run --script`, not `python3`. Check that `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PLUGIN_ROOT}` resolve correctly.
- **Agent missing context**: Agents must explicitly Read reference files — they are not auto-injected. Check the agent's Read instructions point to valid `${CLAUDE_PLUGIN_ROOT}/reference/` paths.

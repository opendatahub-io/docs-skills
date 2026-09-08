# docs-skills

Follow the shared project conventions in @AGENTS.md for repository structure, skill naming, contributing rules, and script invocation patterns. The instructions below apply only to Claude Code.

## Repository structure

```text
.claude-plugin/plugin.json   Plugin packaging metadata
skills/docs-engine/          Shared runtime. Not invoked directly
skills/<skill>/SKILL.md      Skill definitions with frontmatter
tests/                       pytest suite and the synthetic fixture repository
```

There are no `agents/`, `hooks/`, or `reference/` directories. Subagent dispatch is gone: every model step runs through the engine's `lib/run/step.py`, so nothing depends on a harness offering subagents.

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

The runtime working directory is the project root, not the skill directory, so a bare `scripts/foo.py` fails. Resolve from the skill instead.

```bash
# Same-skill script
python3 "$(dirname "$0")/scripts/write.py" --repo .

# The shared runtime, which lives in the docs-engine skill
python3 "$(dirname "$0")/../docs-engine/scripts/lib/git/git_context.py" context --repo .
```

Do not use `${CLAUDE_PLUGIN_ROOT}` or `${CLAUDE_SKILL_DIR}`. No harness sets a plugin root, and a skill installer copies each skill directory on its own, so paths must resolve from the file that uses them. Python scripts walk up from `__file__` to find `docs-engine`; see AGENTS.md for the exact lookup.

## Skill logic must live in scripts

Anything deterministic belongs in a script, not in prose a model re-derives each run. Path resolution, JSON assembly, schema validation, git plumbing, and every ownership guard are script-level. A `SKILL.md` says when to reach for the skill and what its arguments mean; it does not restate what the script already does.

Ownership is the clearest case. Whether a file may be written, and which bytes may move, is decided in `docs-write`'s script. A prompt instruction is a request; a function that never receives the surrounding text is a guarantee.

## Referencing files from skills

`@` references are a user input feature resolved by the Claude Code CLI when typing in the chat prompt. They are NOT resolved inside skill body text, which becomes the system prompt verbatim. Use a relative path and a normal link instead.

## Debugging

- **Wrong or missing documents**: read `.docs-gen/write-report.json`. Every result carries a status and a reason, including refusals by the ownership contract.
- **A run did nothing**: `docs-sync` exits 1 when the loop guard fires or no module changed. Its stderr says which. `.docs-gen/relevance.json` carries the per-module verdict.
- **A model step failed**: `step.py` writes `<out>.error.json` with the validation errors and the raw reply that failed them.
- **Claims that do not match the code**: `.docs-gen/review.json` lists every finding with a severity and the document it came from.

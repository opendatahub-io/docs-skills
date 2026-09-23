---
name: docs-query-code
description: Answers a question about an analyzed repository with file and line citations. Use when code-analysis artifacts exist and a focused, source-grounded answer is needed.
argument-hint: "<question> [--repo PATH] [--write PATH]"
allowed-tools: Bash, Read, Write
---

# docs-query-code

Answers a question about a repository and cites the lines behind the answer.

## Quick start

```bash
QUERY="$(dirname "$0")/scripts/query.py"

python3 "$QUERY" "How does the scheduler decide to retry?" --repo /path/to/code
python3 "$QUERY" "What calls into the storage layer?" --repo . --write docs/answers/
```

Run `docs-repo-analyze` first. This skill reads its artifacts from `.docs-gen/` and exits 1 with an explanation when `registry.json` is missing.

## What it reads

| Source | What it contributes | Required |
|---|---|---|
| `registry.json` | Which code modules exist, their paths and kind | Yes |
| The source tree | Lines matching the question's terms, with line numbers | Yes |
| `modules/<slug>.json` | Per-code-module purpose, responsibilities, gotchas | When present |
| `dep-pairs.json` | What depends on what | When present |
| `ONBOARDING.md` | The synthesized overview | When present |

Search terms come from the question. Anything backticked, CamelCase, or snake_case is treated as an identifier and ranked above the plain words, since identifiers are the part of a question that narrows a search.

## One call, no dispatch

The answer is a single `lib/run/step.py` invocation, the runner every model step in this plugin uses. Nothing here dispatches a subagent, so the skill behaves the same under Claude Code, Codex, or a bare shell.

## Grounding

The prompt receives real source lines with real line numbers and is told to cite them. A claim it cannot attach to a line goes under `uncertain` instead of into the answer.

Where a code-module summary and the source disagree, the source wins and the answer reports the summary as stale. Summaries are generated from an earlier commit and go out of date. Lines do not.

## Output

Markdown with YAML frontmatter, carrying `managed: generated` so the metadata layer treats it like any other generated page. Output prints to stdout by default. `--write` accepts a file path, or a directory, where the filename becomes a slug of the question plus a UTC timestamp.

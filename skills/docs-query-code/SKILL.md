---
name: docs-query-code
description: Answer a question about a repository the generator has already analyzed. Reads the registry, module summaries, and dependency graph, greps the source for the question's terms, and answers once with file:line citations.
argument-hint: "<question> [--repo PATH] [--write PATH]"
allowed-tools: Bash, Read, Write
---

# docs-query-code

Ask a question, get an answer with line numbers behind it.

## Quick start

```bash
QUERY="$(dirname "$0")/scripts/query.py"

python3 "$QUERY" "How does the scheduler decide to retry?" --repo /path/to/code
python3 "$QUERY" "What calls into the storage layer?" --repo . --write docs/answers/
```

Requires an earlier `docs-repo-analyze` run, whose artifacts it reads from
`.docs-gen/`. Without one it exits 1 and says so.

## What it reads

| Source | What it contributes |
|---|---|
| `registry.json` | Which modules exist, their paths and kind |
| `modules/<slug>.json` | Per-module purpose, responsibilities, gotchas |
| `dep-pairs.json` | What depends on what |
| `ONBOARDING.md` | The synthesized overview, when one was written |
| the source tree | Lines matching the question's terms, with line numbers |

Search terms come from the question. Anything backticked, CamelCase, or
snake_case is treated as an identifier and ranked above the plain words, because
that is the part of a question that actually narrows a search.

## One call, no dispatch

The answer is a single `lib/run/step.py` invocation, the same runner every other
model step in this plugin uses. Nothing here dispatches a subagent, so the skill
behaves identically under Claude Code, Codex, or a bare shell.

## Grounding

The prompt gets real source lines with real line numbers and is told to cite
them. A claim it cannot attach to a line is asked for separately, under
`uncertain`, rather than being folded into the answer.

Where the module summaries and the source disagree, the source wins and the
answer says the summary is stale. Summaries are generated from an earlier commit
and go out of date; the lines do not.

## Output

Markdown with YAML frontmatter, carrying `managed: generated` so the metadata
layer treats it like any other generated page. Prints to stdout by default.
`--write` takes a file, or a directory, in which case the filename is a slug of
the question plus a UTC timestamp.

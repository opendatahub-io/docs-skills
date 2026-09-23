---
name: docs-review
description: Checks generated documentation against code and pipeline artifacts. Use when drafts need deterministic grounding checks, with optional model review of claims and style.
argument-hint: <repo-path> [--docs-dir DIR] [--llm-cmd CMD] [--vale-config PATH] [--no-style] [--strict]
allowed-tools: Bash, Read, Write
---

# docs-review

Runs the deterministic checks first and reaches a model only for the findings they cannot settle. Most runs never need the model.

## Quick start

```bash
REVIEW="$(dirname "$0")/scripts/review.py"

# Deterministic checks only. Free
python3 "$REVIEW" --repo . --out .docs-gen --docs-dir docs

# Also judge behavioural claims that no symbol name settles
python3 "$REVIEW" --repo . --out .docs-gen --llm-cmd "claude -p"
```

## Deterministic checks

| Check | Rule | Failure means |
|---|---|---|
| Grounding | Every backticked identifier in prose appears in `api-surface.json` | The page names something the code does not define |
| Registry membership | Every `source_modules` entry identifies a code module in the registry | The topic has lost its subject |
| Fence freshness | Every `docs-gen` region `sha` matches the current code-module head, or is queued | The region describes older code. A region with no sha is a warning |
| Frontmatter | `managed` holds one of the three values | A missing `description` or `source_sha` is a warning |
| Evidence | Every `file:line` the writer cited points at a file that exists | The citation leads nowhere |

Grounding exempts code blocks, where an example legitimately names the caller's own variables. This check covers most of what a retired LLM quality gate used to do, at no token cost.

## What reaches a model

One class of finding: a sentence that makes a behavioural claim naming no symbol. "The queue retries three times before giving up" cannot be checked against an API listing. Each flagged document costs one call asking whether the cited evidence lines support the claim, and an unsupported claim becomes a warning.

Documents marked `manual` are skipped entirely.

## Output

`review.json` in the artifact directory, with a severity on every finding. The caller renders the errors into the pull request body so a reviewer sees what still needs a human decision.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Review completed with nothing blocking |
| 1 | Nothing to review |
| 3 | A blocking error was found |

Findings that rest on matching text report and never block. Two cases settled
this. `Direct.Length` measures a Markdown table row as though it were a
sentence, so the rule is correct about the word count while the document is
fine. The grounding check compares backticked words against an extracted
symbol table, where a config key, a CLI name or a field name reads the same as
an invented method.

The advisory kinds are `prose`, `style`, `style-failed`, `style-unavailable`,
`vale-unavailable` and `ungrounded-identifier`. `review.json` counts them under
`advisory`, and the summary line names them so a run that passes while
reporting errors does not read as a forgotten exit code.

What blocks is what the tool can check structurally: an unparseable document,
a broken fenced region, a malformed `managed` field, a `source_modules` entry
naming a module the registry does not hold. `--strict` blocks on everything,
including warnings and the advisory kinds.

A grounding finding carries a severity that says how much to trust it. A
qualified name such as `client.reconnect` is an API path and nothing else, so
a miss is an `error`. A bare word is ambiguous and reports as a `warning`.

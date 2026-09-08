---
name: docs-review
description: Check generated documentation against the code it describes. Grounding, registry membership, staleness, fence freshness, and frontmatter all resolve deterministically from artifacts on disk. Only ambiguous behavioural claims reach a model.
argument-hint: <repo-path> [--docs-dir DIR] [--llm-cmd CMD] [--strict]
allowed-tools: Bash, Read, Write
---

# docs-review

Deterministic first, model second, and on most runs the model is not needed.

## Quick start

```bash
REVIEW="$(dirname "$0")/scripts/review.py"

# Deterministic checks only. Free
python3 "$REVIEW" --repo . --out .docs-gen --docs-dir docs

# Also judge behavioural claims no symbol name settles
python3 "$REVIEW" --repo . --out .docs-gen --llm-cmd "claude -p"
```

Exit 3 when errors were found. Exit 1 when there is nothing to review.

## The deterministic checks

**Grounding.** Every backticked identifier in prose must appear in
`api-surface.json`. This is the check that replaces most of a retired LLM
quality gate, and it costs nothing. Code blocks are exempt: an example
legitimately names the caller's own variables.

**Registry membership.** Every `source_modules` entry must exist in the
registry. A document naming a module that no longer exists has lost its subject.

**Staleness.** Each document's `source_modules` is intersected with `rebuild[]`
from `relevance.json`. Generated and assisted documents whose modules moved are
queued for rewrite. Manual documents become a finding for a human and are never
written. That split is what lets hand-written pages take part in the pipeline
without being overwritten by it.

**Fence freshness.** Every `docs-gen` region's `sha` must match the current
module head or be queued. A region with no sha at all is a warning.

**Frontmatter.** `managed` must be one of the three values. A missing
`description` or `source_sha` is a warning.

**Evidence.** Every `file:line` the writer cited must point at a file that
exists.

## What reaches a model

One class of finding: a sentence making a behavioural claim that names no
symbol. "The queue retries three times before giving up" cannot be checked
against an API listing. One call per flagged document asks whether the cited
evidence lines support the claim, and an unsupported claim becomes a warning.

Documents marked `manual` are skipped entirely.

## Output

`review.json` under the artifact directory, with a severity on every finding.
`docs-sync` renders the errors and the stale hand-written pages into the pull
request body, so a reviewer sees what a human still has to decide.

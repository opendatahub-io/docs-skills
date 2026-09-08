---
name: docs-write
description: Generate or update Markdown documentation for a code module. Enforces whole-file ownership through the managed frontmatter field and within-file ownership through docs-gen fenced regions, both in script rather than in a prompt.
argument-hint: <repo-path> [--relevance FILE | --modules NAME...] [--llm-cmd CMD]
allowed-tools: Bash, Read, Write
---

# docs-write

Writes one document set per module, in plain Markdown with YAML frontmatter.

## Quick start

```bash
WRITE="$(dirname "$0")/scripts/write.py"

# Write only what the relevance engine named
python3 "$WRITE" --repo . --out .docs-gen \
  --relevance .docs-gen/relevance.json --llm-cmd "claude -p"

# Write specific modules
python3 "$WRITE" --repo . --out .docs-gen --modules pkg/queue pkg/scheduler
```

Normally invoked by `docs-sync`, which supplies the relevance list.

## Ownership

The `managed` field in a document's frontmatter decides what happens to it.

| `managed` | What the writer does |
|---|---|
| absent | Creates the file. Stamps `managed: generated` |
| `generated` | Regenerates the body. Keeps frontmatter a human set |
| `assisted` | Rewrites only the `docs-gen` fenced regions |
| `manual` | Never opens the file for writing. Emits a staleness finding |

These are enforced in `scripts/write.py`. A `manual` file's path never reaches a
write call, and an `assisted` file's surrounding prose is never sent to the
model at all. No prompt wording moves either boundary, which is why they are
here rather than in the prompt.

Marking sets `manual` by default, so pointing this at an existing documentation
tree protects every file on first contact. Only the writer promotes a file to
`generated`.

## Fenced regions

```markdown
<!-- docs-gen:begin section=api source=pkg/scheduler sha=a1b2c3d -->
generated body
<!-- docs-gen:end -->
```

`lib/md/fences.py` rewrites the inside and asserts every byte outside came back
unchanged. A rewrite that would touch the surrounding prose raises rather than
writing.

## Determinism

The model returns structure: sections with stable ids, headings, and bodies.
`lib/md/render.py` turns that into bytes, so heading levels, blank lines, and
frontmatter key order never vary between runs.

A rewrite below the churn floor is discarded. An LLM rewording one sentence on
an unchanged module produces a real diff worth nothing to a reviewer, and the
floor is what stops that from opening a pull request. Section adds and removes
bypass the floor: structural change is always worth showing.

Section ids are the unit of regeneration. A section declares the symbols it
covers, so a single signature change rewrites that section and no other.

## Grounding

Every identifier the writer puts in backticks must exist in the extracted API.
`docs-review` checks it mechanically and fails the document otherwise, at zero
tokens.

Examples come from test files under the module path before they come from the
model. A call lifted from a test breaks the test suite when it rots; an invented
one rots silently.

Claims the writer cannot ground land in `gaps` rather than in the prose.

## Doc types

Which types a module gets comes from the `artifacts` map in
`languages/<lang>.md`, keyed by the module's kind. Where the language names a
native reference generator, `reference` is skipped: pdoc, godoc, typedoc, and
rustdoc produce symbol listings better than prose does, and they never go stale.

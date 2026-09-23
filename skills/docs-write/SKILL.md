---
name: docs-write
description: Writes Markdown documentation for a code module or a planned deliverable. Enforces whole-file ownership through the managed frontmatter field and within-file ownership through docs-gen fenced regions, both in script rather than in a prompt.
argument-hint: <repo-path> [--plan FILE | --modules NAME... | --relevance FILE] [--llm-cmd CMD]
allowed-tools: Bash, Read, Write
---

# docs-write

Writes one Markdown document per planned deliverable, or one document set per code module.

## Quick start

```bash
WRITE="$(dirname "$0")/scripts/write.py"

# Plan mode: what /docs runs, one document per deliverable
python3 "$WRITE" --repo . --out .docs-gen --plan .docs-gen/plan.json --llm-cmd "pi -p"

# Module mode: what /docs-sync runs, only the modules the relevance verdict named
python3 "$WRITE" --repo . --out .docs-gen --relevance .docs-gen/relevance.json --llm-cmd "pi -p"

# Module mode, named explicitly
python3 "$WRITE" --repo . --out .docs-gen --modules pkg/queue pkg/scheduler
```

The two modes are one skill, and one argument parser, because they share the
ownership contract, the renderer and the prose repair loop. They differ only in
what decides the document set: a plan names deliverables, a relevance verdict
or a module list names code modules. Every flag of either mode is reachable
through this one entry point.

## Ownership

The `managed` field in a document's frontmatter decides what happens to it.

| `managed` | What the writer does |
|---|---|
| absent | Creates the file. Stamps `managed: generated` |
| `generated` | Regenerates the body. Keeps frontmatter a human set |
| `assisted` | Rewrites only the `docs-gen` fenced regions |
| `manual` | Never opens the file for writing. Emits a staleness finding |

These are enforced in `scripts/write.py`, through `docs-engine`'s
`lib/md/ownership.py`. A `manual` file's path never reaches a write call, and
an `assisted` file's surrounding prose is never sent to the model at all. No
prompt wording moves either boundary, which is why they are here rather than in
the prompt.

Marking sets `manual` by default, so pointing this at an existing documentation
tree protects every file on first contact. Only the writer promotes a file to
`generated`.

## New pages and updates

A plan deliverable carries a `kind`. A `new` deliverable writes into the
changeset directory `--changeset` names, and is a flat kebab-case file name so
that a separator in it cannot decide where the file lands. An `update`
deliverable names a path already under `docs_dir`, nested or not, and is
refused when that path does not exist: a plan built before someone deleted a
page should not put the page back.

Without `--changeset` the writer writes in place and prunes nothing. `prune`
deletes from `<changeset>/new`, so a default pointing at `docs_dir` would empty
a real `docs/new/` of anything the plan did not account for.

Both produce the same kind of document, so both take the same prompt and the
same schema. Ownership is the only thing that differs between them.

## Evidence

A page is grounded in what the repository shows: the module registry and the
public API from `docs-repo-analyze`, and the commits from `docs-git-context`. A
deliverable with neither a symbol nor a commit behind it is refused rather than
written from its own title.

## Prose

With `--vale-config`, a draft that fails the prose gate goes back to the model
with its alerts, up to `--vale-attempts` times. What will not clear is published
with the page and reported against it, because a rule that has survived every
repair pass is usually reading the document wrong.

## Output

`write-report.json` carries one record per deliverable or module, each with a
status and a reason. A refusal is a record, never an exception, so one
deliverable that fails never costs the documents drafted beside it.

| Exit | Meaning |
|---|---|
| 0 | Documents written |
| 1 | Nothing written |
| 2 | No plan, or nothing to write from |
| 3 | The writer failed |

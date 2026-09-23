# Generated documents

The contract every writer in this plugin shares. `docs-topic-write` and `docs-module-write` both enforce it, and `lib/md/docs_meta.py` maintains the frontmatter it reads.

## Ownership

The `managed` field in a document's frontmatter decides what happens to the file.

| `managed`   | What the writer does                                |
| ----------- | --------------------------------------------------- |
| absent      | Creates the file. Stamps `managed: generated`       |
| `generated` | Regenerates the body. Keeps frontmatter a human set |
| `assisted`  | Rewrites only the `docs-gen` fenced regions         |
| `manual`    | Never opens the file for writing                    |

Each writer's `scripts/write.py` enforces these in code, which is why they live there and not in a prompt. A `manual` file's path never reaches a write call, and an `assisted` file's surrounding prose never reaches the model at all. No prompt wording can move either boundary.

Marking sets `manual` by default, so pointing a writer at an existing documentation tree protects every file on first contact. Only a writer promotes a file to `generated`.

## Fenced regions

```markdown
<!-- docs-gen:begin section=api source=pkg/scheduler sha=a1b2c3d -->
generated body
<!-- docs-gen:end -->
```

`lib/md/fences.py` rewrites the inside of a region and asserts that every byte outside came back unchanged. A rewrite that would touch the surrounding prose raises instead of writing.

## Determinism

The model returns structure: sections with stable ids, headings, and bodies. `lib/md/render.py` turns that structure into bytes, which holds heading levels, blank lines, and frontmatter key order steady between runs.

Section ids stay stable across regeneration.

## Grounding

Claims a writer cannot ground land in `gaps` instead of in the prose. `docs-review` checks the grounded identifiers and claims after writing.

# git-context.json schema

Version `git-context/1`. Written by `git_context.py context`.

## Top level

| Field | Type | Notes |
|---|---|---|
| `schema` | string | `git-context/1` |
| `repo` | string | Absolute path to the working copy |
| `head` | string | Full SHA at HEAD |
| `branch` | string | Branch name, or `HEAD` when detached |
| `range` | object | See below |
| `summary` | object | Aggregates over the commit corpus |
| `modules` | object | Module name to rollup. Empty without `--registry` |
| `hotspots` | array | Ranked, capped by `--limit` (default 30) |
| `files` | object | Path to per-file rollup |
| `commits` | array | Commit records. File lists only with `--full` |

## range

| Field | Notes |
|---|---|
| `range` | Revision range string, or `null` when unresolvable |
| `basis` | `explicit`, `since_sha`, `since_watermark`, `since_last_tag`, `last_tag_span`, `commit_count_fallback`, `orphaned_sha`, `no_valid_watermark` |
| `base` | Left side of the range |
| `warning` | Present when `range` is `null` |

A `basis` of `commit_count_fallback` means the repository has no usable tags.
Treat the resulting scope as approximate.

## summary

| Field | Notes |
|---|---|
| `commit_count` | Commits in range, merges included |
| `conventional_ratio` | Share of subjects matching conventional commits, 0.0 to 1.0 |
| `types` | Conventional type to count, descending |
| `authors` | Author name to commit count, descending |
| `pull_requests` | Sorted PR/MR numbers parsed from subjects |
| `issues` | Sorted issue keys from trailers and, if `--issue-prefix` is set, bodies |
| `breaking_changes` | `{sha, subject}` for `type!:` or a `BREAKING CHANGE:` trailer |

`conventional_ratio` is a routing signal. Above roughly 0.7 the commit types
are trustworthy enough to drive change classification on their own. Below that,
fall back to diff inspection.

## commits[]

| Field | Notes |
|---|---|
| `sha`, `short` | Full and abbreviated |
| `parents` | Parent SHAs |
| `is_merge` | True when more than one parent |
| `author` | `{name, email}` |
| `date` | ISO 8601, author date |
| `subject`, `body` | Message parts |
| `trailers` | Lowercased key to list of values |
| `pr` | Integer or `null` |
| `issues` | Issue keys |
| `conventional` | Subject matched the conventional pattern |
| `type`, `scope` | From the subject, `null` when unmatched |
| `breaking` | `type!:` or a `BREAKING CHANGE:` trailer |
| `files` | Only with `--full`. `{path, adds, dels, binary, renamed_from?}` |

## files{}

Keyed by current path. Merge commits are excluded so numbers are not doubled.

| Field | Notes |
|---|---|
| `adds`, `dels` | Summed across the range |
| `commits` | Number of non-merge commits touching the path |
| `renamed_from` | Previous path, or `null` |
| `module` | Attributed module, or `null` |

Binary files report `adds` and `dels` as `null` with `binary: true` on the
per-commit entry.

## modules{}

| Field | Notes |
|---|---|
| `files` | Paths attributed to this module |
| `adds`, `dels` | Summed |
| `commits` | Sorted SHAs touching the module |

This is the join that makes incremental regeneration possible. A module absent
from this object did not change in range and needs no rebuild.

## hotspots[]

Sorted by commit count first, then total churn. `{path, churn, commits, module}`.
Commit frequency ranks above line volume because a file edited eleven times is
a better documentation target than one rewritten once.

## .docs-state.json

Separate artifact, committed to the docs repo.

```json
{
  "registry_hash": "sha256:...",
  "modules": {
    "pkg/scheduler": {"sha": "a1b2c3...", "doc": "docs/scheduler.md"}
  }
}
```

`registry_hash` covers the `docs-learn-code` registry. A mismatch means module
boundaries moved and attribution from a previous run cannot be trusted, so
rebuild everything.

---

# api-surface.json schema

Version `api-surface/1`. Written by `api_surface.py snapshot`.

| Field | Notes |
|---|---|
| `registry_hash` | Hash of module boundaries alone |
| `api_hash` | Rollup of every module hash |
| `ref` | Present when snapshotted with `--at` |
| `modules{}` | `hash`, `symbol_count`, `symbols{}`, `source` |

Each symbol is keyed `kind:name` and carries `fp`, `file`, `line`, `signature`.
The fingerprint `fp` hashes kind, name, and whitespace-normalized signature, so
reformatting is invisible and a parameter rename is not.

`source` is `native` when fingerprinted in-process, `external` when ingested
from a language extractor via `--api-dir`.

# api-diff/1

| Field | Notes |
|---|---|
| `registry_changed` | Boundaries moved. Forces a full rebuild downstream |
| `api_changed` | Any module hash differs |
| `known_modules` | Every module present in either snapshot |
| `modules{}` | Only modules whose hash changed |

Absence from `modules` while present in `known_modules` means the surface held
still. That distinction is what stops a reflow being escalated for review.

Per module: `added[]`, `removed[]`, `changed[{symbol, before, after}]`,
`moved[{symbol, before, after}]`, `before_hash`, `after_hash`.

# doc-relevance/1

| Field | Notes |
|---|---|
| `verdict` | `incremental`, `no_op`, or `full_rebuild` |
| `rebuild[]` | Modules to regenerate |
| `review[]` | Modules the rules could not judge |
| `unattributed_files[]` | Changed paths matching no module, capped at 50 |
| `modules{}` | Per-module verdict, reason, counts, and commits |

A growing `unattributed_files` list means the registry is drifting from the
repository layout and needs regenerating.

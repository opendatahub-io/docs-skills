---
name: docs-sync
description: Keep a repository's Markdown documentation current with its code. Runs the whole chain — history, module registry, API fingerprints, change relevance, writing, review, metadata, changelog — and stops early when nothing changed. The CI entry point.
argument-hint: <repo-path> [--bootstrap | --since-watermark FILE] [--llm-cmd CMD]
allowed-tools: Bash, Read, Write
---

# docs-sync

Point it at a repository, get documentation. Merge to main, get the delta.

This is the entry point that composes every other skill in the plugin. Reach for
it rather than running the steps by hand; the ordering, the caching, and the
loop guard all live here.

## Quick start

```bash
SYNC="$(dirname "$0")/scripts/sync.py"

# First run on a repository with no documentation state
python3 "$SYNC" --repo /path/to/code --bootstrap --max-modules 20

# Every run after that
python3 "$SYNC" --repo /path/to/code --since-watermark .docs-state.json
```

## What it runs

```
git-context      what changed, and where it landed        no model
repo-analyze     module registry, per-module API          one call per module
api_surface      fingerprints, diff, relevance verdict    no model
docs-write       the documents citing a changed module   one call per document
docs_meta mark   frontmatter provenance                   no model
docs-review      grounding, staleness, fences             no model unless flagged
docs_meta index  the document index in AGENTS.md          no model
changelog        release notes                            no model above ratio 0.7
```

Every arrow is a file under `.docs-gen/`. A run that dies halfway leaves the
artifacts it already produced, and the next run picks up from them.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Wrote documentation |
| 1 | Nothing to do. No module changed, or the loop guard fired |
| 3 | Review found errors, or a step failed |
| 5 | Every write was refused by the ownership contract |

CI treats 1 as success and opens no pull request.

## The loop guard

Documentation living in the repository it describes creates a cycle: the docs
pull request merges, that merge is a push, and the push retriggers the run.

Three independent signals stop it. HEAD authored by the configured
`bot_author`. A change set confined to paths this tool writes, which covers
`docs/`, `.docs-gen/`, `.docs-state.json`, and `CHANGELOG.md`. A watermark
already level with HEAD for every module.

`--force` skips the guard. Use it when debugging, not in CI.

## Bootstrap

`--bootstrap` is the first run: no watermark to work from, so every module goes
into `rebuild[]`. On a large repository that is the expensive run, which is what
`--max-modules` is for. Modules that were capped out keep their old watermark
entry, so the next run continues where this one stopped rather than starting
over.

The watermark is written at the end, so the second run is incremental whatever
happened in the first.

## Configuration

`.docs-gen.yaml` at the repository root, under a `generate:` key. Command line
flags win over it. See the file this plugin ships as an example.

```yaml
generate:
  llm_cmd: "pi -p"
  docs_dir: docs
  bot_author: docs-bot@example.com
  max_modules_per_run: 20
  issue_prefixes: [RHOAIENG]
```

## Artifacts

`.docs-gen/` holds the run's state. `registry.json`, `api/`, and
`api-surface.json` are committed; everything else is transient. The `.gitignore`
fragment the plugin ships gets that split right.

`pr-body.md` is rendered from the relevance verdict and the review findings:
which modules were rebuilt and why, which hand-written pages went stale, what
was skipped. Pass it to whatever opens the pull request.

## What it will not do

Write a file whose frontmatter says `managed: manual`. Touch a byte outside a
`docs-gen` fence in a file marked `assisted`. Write doc comments into source
unless the language file says `writable: true`. Those three are enforced in
`docs-write`'s script, not in a prompt.

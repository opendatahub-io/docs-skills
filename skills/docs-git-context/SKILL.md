---
name: docs-git-context
description: Extract structured history from a git repository for documentation generation. Resolves which revision range to document, parses the commit corpus, attributes changes to code modules, ranks hotspots, and tracks a per-module documented-SHA watermark for incremental CI runs. Deterministic and offline.
argument-hint: <repo-path> [--range REV..REV | --since-watermark FILE]
allowed-tools: Bash, Read, Write
---

# git-context

Turns a repository's history into one JSON artifact that every downstream
documentation step reads. No model calls, no forge API, no network. A run over
a few hundred commits takes under a second and produces the same output every
time, which is what makes it safe to put in CI.

Everything here is `docs-engine`'s `lib/git/git_context.py`, stdlib only. Invoke it directly.
There is no agent dispatch and nothing harness-specific, so the same commands
work under Claude Code, Codex, or a plain shell in a CI job.

## When to use

Reach for this before planning or writing anything. It answers what changed,
where it landed in the codebase, and whether the change is worth documenting.
Skip it only when generating docs for a repo with no history worth reading.

## Quick start

```bash
# Resolve from this file, not from an environment variable: skill installers
# copy a skill directory to a different path per harness, and none of them set
# a plugin root.
GC="$(dirname "$0")/../docs-engine/scripts/lib/git/git_context.py"

# One artifact with everything downstream needs
python3 "$GC" context --repo /path/to/repo \
  --registry .docs-gen/registry.json \
  --excludes "$(dirname "$0")/../docs-engine/config/path_filters.txt" \
  --out .docs-gen/git-context.json
```

Read `git-context.json` from disk. Do not shell out to git yourself; if
something is missing from the artifact, add it here so every harness gets it.

## Commands

| Command | Purpose |
|---|---|
| `range` | Decide what to document. Since last tag by default |
| `commits` | Structured commit corpus with trailers, PR numbers, issue keys |
| `changes` | Per-file and per-module rollup of adds, deletes, renames |
| `churn` | Hotspot ranking by commit frequency, then volume |
| `context` | All of the above in one file. The normal entry point |
| `clone` | Treeless clone that keeps full history |
| `watermark` | Read or update the documented-SHA state file |

## Choosing a range

Precedence: `--range`, then `--since-sha`, then `--since-watermark`, then the
default. The default walks back to the most recent tag; if HEAD is exactly at a
tag it takes the previous tag's span instead. Untagged repos fall back to the
last 200 commits, reported as `commit_count_fallback` so callers know the basis
was weak.

When a watermark SHA is unreachable (rebase, force-push, squashed branch) the
command returns `range: null` with a warning rather than guessing. Treat that
as a signal to rebuild the module's docs in full.

## Clone behaviour

`clone` uses `--filter=blob:none`. Full commit history, blobs fetched lazily on
first read. Shallow clones cannot answer history questions at all, so if the
target directory already holds a shallow repository the tool runs
`fetch --unshallow` before doing anything else. GitHub Actions checks out
shallow by default, so this fires on most CI runs.

Fork-based PRs whose branch is absent from origin fall back to
`refs/pull/N/head` or `refs/merge-requests/N/head`.

## Module attribution

Pass `--registry` pointing at a `learn-code` `registry.json`, or at a simple
`{"module-name": ["path/prefix"]}` map. Longest matching prefix wins. Without a
registry the artifact still lists files; it just cannot roll them up.

`--excludes` takes a file of regex patterns, one per line, `#` for comments.
Filter out tests, vendored code, and build output here so churn rankings
reflect real source movement.

## What the artifact carries

```
schema, repo, head, branch, range
summary   commit_count, conventional_ratio, types, authors,
          pull_requests, issues, breaking_changes
modules   files, adds, dels, commits          (needs --registry)
hotspots  path, commits, churn, module
files     path -> adds, dels, commits, renamed_from, module
commits   full records; file lists only with --full
```

See [reference/schema.md](reference/schema.md) for field-level detail.

## Incremental CI runs

```bash
# What moved since the docs were last updated
python3 "$GC" context --repo . --since-watermark .docs-state.json \
  --registry registry.json --out git-context.json

# ... regenerate only the modules listed under .modules ...

# Record what is now documented
python3 "$GC" watermark write --file .docs-state.json --repo . \
  --module pkg/scheduler --doc docs/scheduler.md
```

Commit `.docs-state.json` alongside the generated docs so the next run has a
floor to work from.

## API surface and change relevance

`docs-engine`'s `lib/git/api_surface.py` is the other half of this skill. It fingerprints the
public API, which serves two jobs from one artifact: the rollup hashes drive
cache invalidation, and diffing two snapshots decides whether a change is worth
documenting.

```bash
AS="$(dirname "$0")/../docs-engine/scripts/lib/git/api_surface.py"

python3 "$AS" snapshot --repo . --registry registry.json --at "$WATERMARK_SHA" --out before.json
python3 "$AS" snapshot --repo . --registry registry.json --out after.json
python3 "$AS" diff --before before.json --after after.json --out api-diff.json
python3 "$AS" relevance --git-context git-context.json --api-diff api-diff.json --out relevance.json
```

`relevance.json` carries a `rebuild` list. Regenerate those modules and nothing
else. A `review` list holds modules the deterministic rules could not judge, and
that is the only place a model needs to be involved.

Snapshots at a past ref use a temporary detached worktree, so an old surface can
always be rebuilt without storing it. Signatures are whitespace-normalized,
which means a reflow or a reformat produces an identical fingerprint.

### Verdicts

| Verdict | Meaning |
|---|---|
| `rebuild` | Public symbols added, removed, or re-signed |
| `update_refs` | Symbol moved file with its signature intact. Fix links only |
| `skip` | Fingerprint unchanged, or documentation files alone changed |
| `review` | Source changed and no surface data exists. Escalate |
| `full_rebuild` | Registry hash moved, so attribution cannot be trusted |

Two precedence rules matter. A commit-level `BREAKING CHANGE:` marker applies to
the repository, so it never escalates a module whose fingerprint held still; the
fingerprint is the stronger evidence. And a registry hash mismatch overrides
everything, because module boundaries moving invalidates every prior attribution.

### Language coverage

Python is fingerprinted natively via stdlib `ast`. Other languages come in
through `--api-dir`, pointing at per-module JSON from `learn-code`'s tree-sitter
extractor, which already emits `{name, kind, file, signature}`. Adding a language
means teaching the extractor, not touching this script.

## Metadata

`docs-engine`'s `lib/md/docs_meta.py` owns document frontmatter: reading, filling, validating,
indexing, and the staleness join.

```bash
DM="$(dirname "$0")/../docs-engine/scripts/lib/md/docs_meta.py"

python3 "$DM" mark  --repo . --source file,git,context --context git-context.json --write
python3 "$DM" stale --repo . --relevance relevance.json --out stale.json
python3 "$DM" index --repo . --out AGENTS.md
python3 "$DM" validate --repo .          # exit 3 on error
```

Fields: `id`, `title`, `description`, `type`, `owner`, `tags`, `lastUpdated`,
plus four provenance fields, `managed`, `source_modules`, `source_sha`, and
`generator`.

`managed` carries whole-file ownership. `generated` means the writer owns the
body. `assisted` means it owns only the fenced regions. `manual` means it never
opens the file for writing. Marking sets `manual` by default, so a pre-existing
corpus is protected on first contact and only the writer promotes a file.

`stale` is the join that makes any of this useful: `source_modules` intersected
with `rebuild[]` from `relevance.json`. Generated and assisted documents whose
modules moved are queued for rewrite; manual documents become a finding for a
human.

Marking is fill-when-absent, so a human correction is never overwritten.
Rendering uses a fixed key order and preserves the body byte for byte, which is
what makes a second run produce an unchanged corpus. `AGENTS.md`, `CLAUDE.md`,
`SKILL.md`, and the `.claude` and `.cursor` directories are skipped; marking an
agent instruction file corrupts what an agent reads to orient itself.

## Notes on accuracy

Merge commits are excluded from file rollups. Their diffs count against both
parents and would double every number.

PR numbers come from commit subjects (`Merge pull request #N`, a trailing
`(#N)`, GitLab's `See merge request !N`). This works offline and needs no
token. Fall back to a forge API only when the parse comes up empty.

Issue keys are read from trailers unconditionally. Scanning commit bodies for
bare keys requires `--issue-prefix RHOAIENG PROJ`, because an unscoped
`[A-Z]+-\d+` pattern matches CWE-22, SHA-256, and UTF-8.

Trailers are parsed from git's `%(trailers)` output, with a fallback that reads
the body directly. Git rejects any trailer block containing a key with a space,
so a commit carrying `BREAKING CHANGE:` otherwise loses its `Fixes:` and
`Co-authored-by:` lines as collateral. The fallback walks paragraphs backwards
and merges each one that parses wholly as trailers, stopping at the first that
does not, so a commit-msg hook appending its own footer (rh-pre-commit, Gerrit
`Change-Id`, DCO tooling) does not hide the real trailers behind it.

Renames need `-M`, which is always on. A rename shows as one entry with
`renamed_from` set, so a moved file does not trigger a spurious rebuild.

## Limitations

Submodules are not traversed. Monorepos need `--path` scoping per component.
Squash-merge repositories collapse a branch into one commit, so per-commit
granularity is thin and the PR body becomes the better narrative source.

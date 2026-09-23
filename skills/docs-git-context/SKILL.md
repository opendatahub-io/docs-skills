---
name: docs-git-context
description: Extracts structured history from a git repository for documentation generation. Use when planning or writing requires deterministic, offline evidence of what changed.
argument-hint: <repo-path> [--range REV..REV]
allowed-tools: Bash, Read, Write
---

# docs-git-context

Turns a repository's history into one JSON artifact that every downstream documentation step reads. It makes no model calls, no forge API requests, and no network requests of any kind. A run over a few hundred commits takes under a second and produces identical output every time, which is what makes it safe in CI.

Everything here is `docs-engine`'s `lib/git/git_context.py`, standard library only. Invoke it directly. There is no agent dispatch and nothing harness-specific, so the same commands work under Claude Code, Codex, or a plain shell in a CI job.

## When to use

Reach for this before planning or writing anything. It answers what changed, where the change landed in the repository, and whether the change is worth documenting. Skip it only when generating docs for a repository whose history holds nothing worth reading.

## Quick start

```bash
# Resolve from this file, not from an environment variable: skill installers
# copy a skill directory to a different path per harness, and none of them set a plugin root.
GC="$(dirname "$0")/../docs-engine/scripts/lib/git/git_context.py"

# One artifact with everything downstream needs
python3 "$GC" context --repo /path/to/repo \
  --registry .docs-gen/registry.json \
  --excludes "$(dirname "$0")/../docs-engine/config/path_filters.txt" \
  --out .docs-gen/git-context.json
```

Read `git-context.json` from disk. Do not shell out to git yourself. When something is missing from the artifact, add it here so every harness gets it.

## Commands

| Command   | Purpose                                                                  |
| --------- | ------------------------------------------------------------------------ |
| `range`   | Decide what to document. Since last tag by default                       |
| `commits` | Structured commit corpus with trailers, pull request numbers, issue keys |
| `changes` | Per-file and per-code-module rollup of adds, deletes, renames            |
| `churn`   | Hotspot ranking by commit frequency, then volume                         |
| `context` | All of the above in one file. The normal entry point                     |
| `clone`   | Treeless clone that keeps full history                                   |

## Choosing a range

Precedence runs `--range`, then `--since-sha`, then the default. The default walks back to the most recent tag, and where HEAD sits exactly on a tag it takes the previous tag's span instead. An untagged repository falls back to the last 200 commits, reported as `commit_count_fallback` so callers know the basis was weak.

## Clone behaviour

`clone` uses `--filter=blob:none`, which keeps full commit history and fetches blobs lazily on first read. A shallow clone cannot answer history questions at all, so a target directory already holding one gets `fetch --unshallow` before anything else happens. GitHub Actions checks out shallow by default, so this fires on most CI runs.

A fork-based pull request whose branch is absent from origin falls back to `refs/pull/N/head` or `refs/merge-requests/N/head`.

## Code-module attribution

Pass `--registry` pointing at a `docs-repo-analyze` `registry.json`, or at a simple `{"module-name": ["path/prefix"]}` map. The longest matching prefix wins. Without a registry the artifact still lists files, but it cannot roll them up.

`--excludes` takes a file of regex patterns, one per line, with `#` for comments. Filter out tests, vendored code, and build output here so churn rankings reflect real source movement.

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

## API surface

`docs-engine`'s `lib/git/api_surface.py` is the other half of this skill. It fingerprints the public API, and the rollup hashes drive cache invalidation.

```bash
AS="$(dirname "$0")/../docs-engine/scripts/lib/git/api_surface.py"

python3 "$AS" snapshot --repo . --registry registry.json --out api-surface.json
```

A snapshot at a past ref (`--at REF`) uses a temporary detached worktree, so an old surface can be rebuilt without storing it. Signatures are whitespace-normalized, so a reflow or a reformat produces an identical fingerprint.

### Language coverage

Python is fingerprinted natively via the standard library `ast` module. Other languages arrive through `--api-dir`, pointing at the per-code-module JSON that `docs-repo-analyze`'s tree-sitter extractor emits as `{name, kind, file, signature}`. Adding a language means teaching the extractor rather than touching this script.

## Metadata

`docs-engine`'s `lib/md/docs_meta.py` owns document frontmatter: reading, filling, validating, and indexing.

```bash
DM="$(dirname "$0")/../docs-engine/scripts/lib/md/docs_meta.py"

python3 "$DM" mark  --repo . --source file,git,context --context git-context.json --write
python3 "$DM" index --repo . --out AGENTS.md
python3 "$DM" validate --repo .          # exit 3 on error
```

Fields: `id`, `title`, `description`, `type`, `owner`, `tags`, `lastUpdated`, plus four provenance fields, `managed`, `source_modules`, `source_sha`, and `generator`.

`managed` carries whole-file ownership, and marking sets it to `manual` by default so a pre-existing corpus is protected on first contact. See [generated-documents.md](../docs-engine/reference/generated-documents.md) for what each value permits.

Marking fills a field only when it is absent, which leaves a human correction alone. Rendering uses a fixed key order and preserves the body byte for byte, so a second run produces an unchanged corpus. Marking skips `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, and the `.claude` and `.cursor` directories, because marking an agent instruction file corrupts what an agent reads to orient itself.

## Notes on accuracy

Merge commits are excluded from file rollups. Their diffs count against both parents and would double every number.

Pull request numbers come from commit subjects: `Merge pull request #N`, a trailing `(#N)`, and GitLab's `See merge request !N`. This works offline and needs no token. Fall back to a forge API only where the parse comes up empty.

Issue keys are read from trailers unconditionally. Scanning commit bodies for bare keys requires `--issue-prefix RHOAIENG PROJ`, because an unscoped `[A-Z]+-\d+` pattern also matches CWE-22, SHA-256, and UTF-8.

Trailers are parsed from git's `%(trailers)` output, with a fallback that reads the body directly. Git rejects any trailer block containing a key with a space in it, so a commit carrying `BREAKING CHANGE:` otherwise loses its `Fixes:` and `Co-authored-by:` lines as collateral. The fallback walks paragraphs backwards and merges each one that parses wholly as trailers, stopping at the first that does not. A commit-msg hook appending its own footer (rh-pre-commit, Gerrit `Change-Id`, DCO tooling) therefore cannot hide the real trailers behind it.

Renames need `-M`, which is always on. A rename shows as one entry with `renamed_from` set, so a moved file does not trigger a spurious rebuild.

## Limitations

Submodules are not traversed. Monorepos need `--path` scoping per component. A squash-merge repository collapses a branch into one commit, so per-commit granularity is thin and the pull request body becomes the better narrative source.

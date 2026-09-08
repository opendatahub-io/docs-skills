---
name: changelog
description: Release notes from git history. Groups conventional commits by type, hoists breaking changes, and links pull request numbers with no model call. Falls back to one model call for a repository whose commit subjects are prose.
argument-hint: "[--context FILE] [--version LABEL] [--llm-cmd CMD]"
allowed-tools: Bash, Read, Write
---

# changelog

A repository that writes conventional commits already carries its own changelog
in structured form. Grouping the commits is arithmetic, and the result beats a
paraphrase of the same information.

## Quick start

```bash
CL="$(dirname "$0")/scripts/changelog.py"
GC="$(dirname "$0")/../../lib/git/git_context.py"

python3 "$GC" context --repo . --out .docs-gen/git-context.json
python3 "$CL" --context .docs-gen/git-context.json --repo . --version v1.2.0
```

## When a model gets involved

Above a `conventional_ratio` of 0.7, never. Below it, one call summarizes the
range from subjects and bodies, and without `--llm-cmd` it degrades to the
deterministic grouping rather than failing.

## What lands in the notes

Breaking changes first, then features, fixes, performance, reverts, internal
changes, documentation, and dependencies. Commits typed `chore`, `style`,
`test`, `ci`, or `build` are dropped: a reader scanning release notes is
deciding whether to upgrade, and a lint fix answers nothing.

Pull request numbers are read from commit subjects offline, with no forge token.
A squash merge that already appended `(#123)` to its subject does not get the
number twice.

## Merging

The newest section goes inside a `changelog:begin` marker, so a hand-written
preamble above it and every prior release below it survive. A second run over an
unchanged range rewrites the same bytes.

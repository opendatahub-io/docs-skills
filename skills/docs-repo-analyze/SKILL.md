---
name: docs-repo-analyze
description: Map a code repository into modules, extract each module's public API, and summarize what each one does. Produces the registry, per-module API JSON, a dependency graph, and an onboarding guide. Sequential, with no subagent dispatch.
argument-hint: <repo-path> [--llm-cmd CMD] [--out DIR] [--paths DIR...] [--subject TOPIC]
allowed-tools: Bash, Read, Write
---

# docs-repo-analyze

Turns a repository into the structured picture every later step reads: which
modules exist, where their boundaries fall, what each one exposes, and what
depends on what.

One sequential model call per module through `docs-engine`'s `lib/run/step.py`, so
the same commands work under any harness or none. There is no fan-out over
subagents.

## Quick start

```bash
ANALYZE="$(dirname "$0")/scripts/analyze.py"

# Deterministic half only: registry, API extraction, no model calls
python3 "$ANALYZE" --repo /path/to/code --out .docs-gen

# With summaries and the onboarding guide
python3 "$ANALYZE" --repo /path/to/code --out .docs-gen --llm-cmd "pi -p"
```

Omitting `--llm-cmd` is a real mode, not a degraded one. The registry and the
API files are everything `api_surface.py` and the relevance engine need, and
they cost nothing.

## Output

| File | Model | Contents |
|---|---|---|
| `registry.json` | no | Module boundaries, kind, file lists, `registry_hash` |
| `registry-boundaries.json` | no | The flat `{module: [prefix]}` view the fingerprinter reads |
| `api-surface.json` | no | The fingerprinted public API the planner and writer ground on |
| `api/<slug>.json` | no | Public symbols per module, for `api_surface --api-dir` |
| `modules/<slug>.json` | yes | Purpose, responsibilities, dependencies, gotchas |
| `dep-pairs.json` | no | Cross-module edges, from those summaries |
| `ONBOARDING.md` | yes | The synthesis |

A module name carries slashes and a filename cannot, so `pkg/scheduler` is
written as `pkg__scheduler.json`. Each file names its own module in a `module`
key, and the ingestion path reads that rather than the filename.

## The registry hash

`registry_hash` is a hash of module boundaries alone. A run whose hash matches
the watermark skips module analysis entirely, which is what `--skip-cached`
does. A mismatch means attribution from an earlier run cannot be trusted, so
every module rebuilds regardless of what the API diff says.

## Narrowing a large repository

`--paths` maps only the modules under the directories it names. `--subject`
does the same from a phrase, which is how the `/docs` chain scopes a topic run:
reading a large repository whole is minutes of work for symbols no page uses.

## Language coverage

Python is fingerprinted natively by `api_surface.py` through the standard
library's `ast`, so no extraction happens here. Go, JavaScript, and TypeScript
go through the tree-sitter extractor and arrive at the fingerprint layer via
`--api-dir`.

Parse rules per language live in `docs-engine/lib/ast/languages.yaml`: module boundaries,
config file names, what counts as public, and the shared exclusion lists.
Adding a language means teaching the extractor and adding an entry there.

That file is not the same as `languages/<lang>.md`, which holds documentation
conventions and reaches the writer prompt verbatim. Two different consumers,
kept apart on purpose.

## Module kind

Each module is classified `library`, `service`, or `cli` from path and filename
evidence. The language file maps that to a set of doc types. An unrecognised
answer falls back to `library`, so a wrong guess costs a page rather than a run.

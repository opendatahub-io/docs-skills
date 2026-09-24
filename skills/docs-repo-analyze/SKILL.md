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
| `modules/<slug>.error.json` | no | Written when one module's summary fails: the errors, and the reply that failed them |
| `dep-pairs.json` | no | Cross-module edges, from those summaries |
| `onboarding.json` | yes | The synthesis reply. Committed, and what the foundation writer reads |
| `ONBOARDING.md` | yes | The same synthesis rendered for a person. Transient |
| `synthesis-error.json` | no | Written when synthesis fails, or when a batch failed and the run carried on: stage, command, input size, errors, raw reply |

A module name carries slashes and a filename cannot, so `pkg/scheduler` is
written as `pkg__scheduler.json`. Each file names its own module in a `module`
key, and the ingestion path reads that rather than the filename.

## When one module fails

A module whose summary fails is skipped and the run carries on, because one
module is one gap in the guide rather than a reason to abandon the rest. The
reply that failed lands in `modules/<slug>.error.json` next to the summary that
is not there: `$.evidence[0]: does not match /.../` says what the contract
wanted, and the record says what arrived. A later run that summarizes the module
successfully removes it.

## The registry hash

`registry_hash` is a hash of module boundaries alone. A run whose hash matches
the watermark skips module analysis entirely, which is what `--skip-cached`
does. A mismatch means attribution from an earlier run cannot be trusted, so
every module rebuilds regardless of what the API diff says.

## Bounding the synthesis

The onboarding guide is one call over every module summary and the dependency
graph, because one call sees the shape the pairs make. A repository with enough
modules exceeds the model's context window doing that, and the only thing said
about it was `$: no JSON object or array found in output`.

So the summaries are packed into batches of at most `--synthesis-budget`
characters, each batch is compacted by one call that keeps the module paths,
dependencies, gotchas and evidence while shortening the prose, and the guide is
written from those. One batch means one call, so a small repository behaves
exactly as it did.

Characters rather than tokens: `read_sources` already budgets that way, a token
count needs either a tokenizer dependency or a chars-per-token guess that is a
character budget wearing a hat, and this runtime is the standard library plus
PyYAML. Roughly four characters to a token, so the 240,000 default is about
60,000 tokens of summaries per call. A summary is measured as the prompt will
carry it, indented and key-sorted, because that is what reaches the window.

The compacted set is measured again against the budget. One pass is not a
guarantee, and a set still over it would reach exactly the call batching
exists to avoid; a pass that sheds nothing ends the loop rather than paying for
another round of it. A batch that fails carries its own summaries forward
instead, so a repository does not lose its guide over one timed-out call.

`--synthesis-budget` has a floor. Below it every module lands in a batch of its
own, which is a model call per module rather than compaction, so the value is
rejected at the command line rather than honoured into a bill.

Configure it per repository under `generate.analyze.synthesis_budget` in
`.docs-gen.yaml`; `docs-sync` passes it through.

A failed synthesis writes `synthesis-error.json`: the stage, the command, the
module count, the input size in characters, the errors, and the raw reply the
model actually sent. A batch failure the run recovered from writes the same
record with `"recovered": true`. The reply is capped and anything in the
command that looks like a credential is masked, because the file is written
inside the repository being documented.

`--modules` narrows which modules are summarized, and a guide built from three
of fifty describes a repository nobody has, so a narrowed run skips synthesis
and says so. Any existing `ONBOARDING.md` is left alone.

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

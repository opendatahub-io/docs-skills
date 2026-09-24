---
name: docs-plan
description: Decides which documents to write from a repository's modules, public API and history. Use when analysis must become a validated list of documentation deliverables.
argument-hint: "--llm-cmd CMD [--repo PATH] [--docs-dir DIR] [--out DIR] [--topic TOPIC]"
allowed-tools: Bash, Read, Write
---

# docs-plan

Turns what the analyzer found into a validated list of deliverables. It runs between analysis and writing.

## Quick start

```bash
python3 scripts/plan.py --repo . --out .docs-gen --llm-cmd "pi -p"
```

Run `docs-repo-analyze` first. This step reads its artifacts and exits 2 with an explanation when `registry.json` is missing.

## The foundation set

```bash
python3 scripts/plan.py --repo . --out .docs-gen --docs-dir docs --foundation --llm-cmd "pi -p"
```

`--foundation` plans five documents and spends no model call, because every
gate is decided from the registry, the API surface, the dependency graph and
the working tree.

| Document | Gate |
|---|---|
| `README.md` | the registry holds at least one module |
| `GET-STARTED.md` | a module of kind `cli` or `service`, and a manifest declaring a runnable target |
| `ARCHITECTURE.md` | 3 or more modules and at least one dependency edge |
| `SECURITY.md` | security vocabulary or a security tool config, and no policy file where GitHub reads one |
| `ROADMAP.md` | a deprecated symbol, an alpha or beta API version, or unreleased notes |

A document that fails its gate is skipped rather than scaffolded, and
`foundation.json` names the gate so a maintainer knows whether to supply the
evidence or switch the document off in `.docs-gen.yaml`.

`--skip-doc` leaves a document unwritten whatever the evidence says. An
unrecognised name exits 2 rather than being ignored, so a typo cannot silently
leave a document enabled.

## What it reads

| Source | What it contributes | Required |
|---|---|---|
| `registry.json` | The modules that exist, and what kind each is | yes |
| `api-surface.json` | The public symbols each module exposes | no |
| `modules/<slug>.json` | Each module's purpose and responsibilities | no |
| `git-context.md` | What moved recently, and where | no |
| `changes.json` | The commits matching the subject | no |
| `<docs-dir>/**/*.md` | What is already written, and who owns it | no |

The existing pages matter as much as the modules. A planner that cannot see them proposes a page that is already there, and the writer then either duplicates it or refuses it.

## Output

`plan.md` carries one bullet per deliverable and lints under the DocsPlan voice, which fails any non-list line long enough to be a paragraph. The rule keeps a plan from growing into the document it plans.

`plan.json` carries the same deliverables, what the existing pages already cover, and every rejection with its reason.

## Validation

A malformed deliverable fails later and further from its cause, so each one is checked here:

| Check | Why |
|---|---|
| `path` is a bare kebab-case `.md` name | The writer joins it onto `docs_dir`, so a directory or a traversal decides where a file lands |
| `type` is concept, procedure or reference | These are what the structural Vale rules gate on |
| `title` and `rationale` are present | A deliverable with neither is a path and nothing else |
| No duplicate paths | Two deliverables writing one file means the second silently wins |
| Sources name a known module or an existing page | An invented module reaches the writer as evidence for a claim nothing supports |

A bad source is dropped and the deliverable survives. Everything else rejects the deliverable, with the reason recorded in `plan.json`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Deliverables planned |
| 1 | Nothing to plan: no modules, or every deliverable was rejected |
| 2 | No registry, or the model step failed |

A repository yielding no modules exits 1 before spending a model call. Asking a model to plan from a topic phrase and nothing else is asking it to invent, and the writer refuses every page that would produce.

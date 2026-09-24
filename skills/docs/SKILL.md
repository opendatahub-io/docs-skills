---
name: docs
description: Documents a code repository. Use when running the complete chain from git history through analysis, planning, writing and review.
argument-hint: "[--topic TOPIC] [--repo PATH] [--llm-cmd CMD] [--models] [--dry-run]"
allowed-tools: Bash, Read, Write
---

# docs

Runs the whole generation chain over one repository, turning what the code does and how it got that way into a set of documents.

```
git-context   the repository's own history               no model
repo-analyze  modules, public API, per-module summaries   one call per module
plan          which of the five documents are supported   no model
write         one document per surviving deliverable      one call per document
review        grounding, commands, prose, style           rarely a call
```

Without a topic the run writes the foundation set: README, GET-STARTED,
ARCHITECTURE, SECURITY and ROADMAP, into the documentation directory. Each is
written only where the repository holds evidence for it, so the planning step
spends no model call and a document with nothing behind it is skipped rather
than scaffolded. `docs-plan`'s own page carries the gate for each one.

```
$ /docs
wrote:   docs/README.md docs/GET-STARTED.md docs/ARCHITECTURE.md docs/ROADMAP.md
skipped: docs/SECURITY.md  a policy already exists at SECURITY.md
```

Every skip names the gate behind it in `foundation.json`, because a maintainer
reading one needs to know whether to supply the missing evidence or switch the
document off in `.docs-gen.yaml`.

`--topic` narrows the run to a subject instead, and keeps the planner prompt:
a subject nobody named cannot be gated for.

## Quick start

```bash
python3 scripts/build.py --repo . --topic "kv cache tiering" --llm-cmd "pi -p"
python3 scripts/build.py --repo . --topic "disconnected mirroring" --llm-cmd "pi -p"
python3 scripts/build.py --repo . --models
```

## Where a run writes

`--out` names the artifact root, `.docs-gen` by default, and each run gets its own directory inside it under the same key its changeset carries, which is the topic's slug. Nothing reads the root itself.

```
.docs-gen/
  vale-packages/                  what --sync-styles downloaded
  kv-cache-tiering/               one run's context, registry, API surface,
                                  module summaries, plan, drafts report and review
```

The split is between what a run derives and what it downloads. Derived artifacts belong to one run and get its directory, because a step that stops early used to leave its answer sitting in the root for the next run to read as its own. A style package is the same bytes whoever asked for it, so it stays shared and is fetched once.

Re-running a topic empties its directory first, so a run never reads what the last one left. The style packages are outside it, so nothing is downloaded again; the registry and the API surface are derived and are rebuilt.

The same run clears `docs/changeset-*-<topic>/`, every dated one for the subject, so the drafts on disk are only ever this run's. Both clears happen before the first step, and a draft marked `managed: manual` is kept and named in the log.

## When a rule stops the run

The artifact gate lints the chain's own notes before the expensive write step and stops on an error-level alert. It names the rules that did it, grouped, with the file and line of each hit, and then says how to change what they cost:

```
docs: the run stopped on 1 rule(s), 1 error-level alert(s):
docs:   RedHat.Headings (1):
docs:     plan.md line 7: Use sentence-style capitalization in 'Plan: accelerators'.

A rule that is wrong about these documents can be lowered in /repo/.vale.ini:

  RedHat.Headings = warning    (line 11, currently `error`)
```

A level in the repository's own config is carried into every composed config and overrides the built-in one. `= NO` switches a rule off.

Each rule is annotated with the line already setting it, because Vale honours the first level it finds and a second line for one already set does nothing.

## Step order

The order is load-bearing. Each constraint below came from a run that failed without it.

**`repo-analyze` runs before `plan`.** The module registry and the public API are what a plan rests on: a deliverable is planned because a module exists and exposes something worth explaining. Planning first means planning from the topic phrase alone.

**A repository with no history does not stop the chain.** A repository that has never been committed still has modules and a public API, and those are what a page rests on. Only the commit evidence is missing, and the run says so.

**No modules found does not stop the chain either.** A repository in a language the extractor does not cover yields an empty registry, and the planner then has the history alone to work from. It says there is nothing to plan rather than inventing deliverables.

**The Vale workspace is composed immediately before the writer.** Composing it earlier writes style files into the artifact directory inside the repository, where a language detector then counts them.

**Every run builds a fresh workspace.** `compose.link_styles` keeps whatever style names it finds, so a workspace reused across two repositories lints the second against the first one's styles.

## Per-step models

```yaml
generate:
  llm_cmd: "pi -p --model anthropic/claude-haiku-4-5"
  llm_cmd_steps:
    plan:   "pi -p --model anthropic/claude-opus-5:high"
    review: "pi -p --model anthropic/claude-opus-5:high"
```

Resolution runs from lowest precedence to highest: the built-in default, `llm_cmd`, the `llm_cmd_steps` entry, `DOCS_LLM_CMD`, then `--llm-cmd`. An unknown step key stops the run rather than leaving that step on a model nobody chose.

`review` stays deterministic unless it is named, so no run starts billing for a pass it was not asked for. `--models` prints the resolved table and exits.

## Where the policy lives

The orchestrator holds the step order. The decisions it makes along the way live in `docs-engine`, so a caller driving the steps by hand reaches the same conclusions: `lib.pipeline.config` decides which model runs a step, and `lib.pipeline.workspace` decides the Vale config a run lints against. Neither module prints, since a library that prints cannot be called from anything with output of its own.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Documents were written |
| 1 | Nothing to write |
| 2 | Configuration error |
| 3 | A step failed, or the review found errors |

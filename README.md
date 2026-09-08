# docs-skills

Generates developer documentation for a code repository, then keeps it current
as the code changes.

Point it at a repo and it reads the history, maps the modules, extracts the
public API, and writes a Markdown page per module. Merge to main and it works
out which modules actually changed, rewrites only those, and opens a pull
request explaining why. On most pushes it decides nothing needs writing and
opens nothing.

It runs under Claude Code, Codex, or a plain shell, and needs no forge token, no
issue tracker, and no ticket to exist before it starts.

## What you get

```text
docs/
  scheduler.md              one page per module, plain Markdown
  scheduler-task.md         getting started, where the module warrants it
CHANGELOG.md                release notes, grouped from commit history
AGENTS.md                   an index of the docs, merged into a marked region
.docs-state.json            which commit each module's docs were written from
.docs-gen/                  the artifacts every step reads and writes
```

Each page carries provenance in its frontmatter, so a reader and a later run
both know where it came from and who owns it:

```markdown
---
id: docs/scheduler
title: Scheduler
description: Queues jobs and retries them.
type: concept
managed: generated
source_modules:
  - pkg/scheduler
source_sha: d6bc7b8
generator: docs-skills/0.5.0
---
## What it does

Call `Submit` to enqueue a job. The queue retries on failure up to `retries`.
```

`managed` is the field that matters. It decides whether the writer may touch the
file at all, and it defaults to `manual` on anything that already exists.

## What it will not do

**Compete with your reference generator.** pdoc, godoc, typedoc, and rustdoc
render signatures better than prose does, and they never go stale. Where a
language names one, this skips reference pages entirely and writes what those
tools cannot: why a module exists, how the pieces fit, and how to get from
nothing to a working call.

**Touch a file marked `managed: manual`.** Its path never reaches a write call.

**Write doc comments into your source.** That would be a pull request against
code, which lands in a different review and risk class. It reports the gap
instead, unless a language file opts in.

**Open a pull request for a paraphrase.** An unchanged module produces an
unchanged fingerprint and is skipped. A rewrite below the churn floor is
discarded rather than committed.

## How a run works

```text
docs-git-context     what changed, and which module it landed in    no model
docs-repo-analyze    module registry, public API, dependencies      one per module
api_surface          fingerprint, diff, verdict per module          no model
docs-write           a document set per module in rebuild[]         one per document
docs-review          grounding, staleness, fences, frontmatter      usually no model
docs-changelog       release notes                                  usually no model
```

`docs-sync` runs that chain in order and stops early when nothing moved. Every
arrow between steps is a file under `.docs-gen/`, so a run that dies halfway
leaves what it already produced and the next one resumes from disk.

## Quick start

```bash
# Install
claude plugin marketplace add opendatahub-io/docs-skills
claude plugin install docs-skills@opendatahub-docs

# First run: no prior state, so every module is queued. Cap it on a large repo.
/docs-sync /path/to/code --bootstrap --max-modules 20

# Every run after that: only what changed since the watermark
/docs-sync /path/to/code --since-watermark .docs-state.json
```

From a checkout, without a harness, the same thing:

```bash
python3 skills/docs-sync/scripts/sync.py --repo /path/to/code \
    --bootstrap --max-modules 20 --llm-cmd "claude -p"
```

## The skills

| Skill | Model calls | What it does |
|---|---|---|
| [`docs-git-context`](skills/docs-git-context/) | none | Revision range, commit corpus, module attribution, hotspots, watermark |
| [`docs-repo-analyze`](skills/docs-repo-analyze/) | one per module | Module registry, public API extraction, dependency graph, onboarding guide |
| [`docs-write`](skills/docs-write/) | one per document | Markdown per module, with ownership enforced in script |
| [`docs-review`](skills/docs-review/) | zero on most runs | Grounding, staleness, fence freshness, frontmatter |
| [`docs-sync`](skills/docs-sync/) | none directly | The CI entry point. Composes the rest |
| [`docs-changelog`](skills/docs-changelog/) | zero above ratio 0.7 | Release notes from commit history |
| [`docs-query-code`](skills/docs-query-code/) | one | Answers a question about an analyzed codebase, with file:line citations |
| [`docs-engine`](skills/docs-engine/) | none | Shared runtime the others read. Not invoked directly |

## How it decides what to rewrite

Every public symbol is fingerprinted as a hash of its kind, name, and
whitespace-normalized signature. Two snapshots diff into a verdict per module.

| Verdict | Meaning |
|---|---|
| `rebuild` | Public symbols added, removed, or re-signed |
| `update_refs` | A symbol moved file with its signature intact. Fix links only |
| `skip` | Fingerprint unchanged, or documentation alone changed |
| `review` | Source changed and no surface data exists. Escalate |
| `full_rebuild` | Module boundaries moved, so prior attribution cannot be trusted |

A reformat produces an identical fingerprint and triggers nothing. A
`BREAKING CHANGE:` trailer never escalates a module whose fingerprint held
still, because the fingerprint is the stronger evidence.

## Ownership

Generated documentation is worth having only if it never eats a hand-written
paragraph. The `managed` field in a document's frontmatter decides what happens
to it.

| `managed` | What the writer does |
|---|---|
| absent | Creates the file. Stamps `managed: generated` |
| `generated` | Regenerates the body. Keeps frontmatter a human set |
| `assisted` | Rewrites only the `docs-gen` fenced regions |
| `manual` | Never opens the file for writing. Emits a staleness finding |

Both boundaries are enforced in `skills/docs-write/scripts/write.py`. A `manual`
file's path never reaches a write call, and an `assisted` file's surrounding
prose is never sent to the model at all. No prompt wording moves either one.

Marking sets `manual` by default, so pointing this at an existing documentation
tree protects every file on first contact.

## Harness agnosticism

Every model call goes through `docs-engine`'s `lib/run/step.py`, which renders a prompt, pipes it
to a command on stdin, recovers JSON from whatever the CLI printed around it,
validates against a schema, and retries once with the errors appended.

```bash
python3 skills/docs-engine/scripts/lib/run/step.py \
  --prompt skills/docs-engine/prompts/write-module.md \
  --input .docs-gen/write-input/scheduler.json \
  --schema skills/docs-engine/schemas/write-out.json \
  --llm-cmd "claude -p" \
  --out .docs-gen/write-output/scheduler.json
```

Swap `--llm-cmd` for `codex exec`, `ollama run <model>`, or a shell wrapper
around a raw HTTP call. Nothing else changes. `cat` works as a mock, which is
what the test suite uses.

No skill reads `${CLAUDE_PLUGIN_ROOT}` or any other harness variable, because no
harness sets one. Scripts resolve from `__file__`, and each `SKILL.md` uses
paths relative to itself.

The shared code lives in a `docs-engine` skill rather than at the repository
root. An installer copies each skill directory on its own and drops symlinks on
the way, so a tree above the skills does not survive an install and cannot be
linked in. It does place every skill as a flat sibling, and that is what the
lookup walks to:

```python
for base in (here.parent, *here.parents):
    if (base / "scripts" / "lib" / "run" / "step.py").exists():
        return base
    if (base / "docs-engine" / "scripts" / "lib" / "run" / "step.py").exists():
        return base / "docs-engine"
```

One walk resolves `skills/docs-engine/` in a checkout and
`<skills-dir>/docs-engine/` after an install, so there is no build step, no
duplicated copy, and nothing to keep in sync.

## Configuration

One file at the root of the repository being documented. Copy
[`config/docs-gen.example.yaml`](skills/docs-engine/config/docs-gen.example.yaml) to
`.docs-gen.yaml`.

```yaml
generate:
  llm_cmd: "claude -p"
  docs_dir: docs
  bot_author: docs-bot@example.com
  max_modules_per_run: 20
  issue_prefixes: [RHOAIENG]
```

## Artifacts

Pipeline state lives under `.docs-gen/` in the documented repository.
`registry.json`, `api/`, and `api-surface.json` are committed; everything else
is transient. [`config/gitignore.fragment`](skills/docs-engine/config/gitignore.fragment) has the
split.

The durable set is committed rather than cached because a `registry_hash` match
skips module analysis, which presumes the registry is already on disk, and the
grounding check reads `api-surface.json` on every run. A cold CI cache would
produce a matching hash with nothing behind it.

## Per-language knowledge

Two files per language, kept apart because they have different consumers.

[`lib/ast/languages.yaml`](skills/docs-engine/scripts/lib/ast/languages.yaml) holds parse rules: module
boundaries, config file names, what counts as public. Read by `repo-analyze`'s
scripts.

[`languages/<lang>.md`](skills/docs-engine/languages/) holds documentation conventions: where docs live, which
reference generator to defer to, doc comment format, example conventions,
identifier casing in prose. The body reaches the writer prompt verbatim, and the
YAML frontmatter carries the values a script executes.

Adding a language is adding a file. Python and Go ship today.

## CI

[`.github/workflows/docs-sync.yml.example`](.github/workflows/docs-sync.yml.example)
is a workflow to copy into the repository being documented. It opens a pull
request whose body is rendered from the relevance verdict and the review
findings, so a reviewer sees which modules were rebuilt and why, and which
hand-written pages went stale.

Exit code 1 means nothing to do and opens no pull request. That is the normal
outcome on most pushes.

The loop guard stops a docs pull request from retriggering the workflow when it
merges: HEAD authored by the configured `bot_author`, a change set confined to
paths this tool writes, or a watermark already level with HEAD.


## Installation

### From GitHub (marketplace)

```bash
claude plugin marketplace add opendatahub-io/docs-skills
claude plugin install docs-skills@opendatahub-docs
```

### From a local clone

```bash
git clone git@github.com:opendatahub-io/docs-skills.git
claude --plugin-dir ./docs-skills
```

`--plugin-dir` loads the plugin without installing it, which is the way to work
on it. Run `/reload-plugins` after a change.

### Without a harness

Nothing here needs one. Clone the repository and call the scripts directly, as
the [quick start](#quick-start) shows. The only requirement is a command that
reads a prompt on stdin and writes JSON to stdout.

## Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.10+ | Everything |
| git | 2.0+ | History, fingerprints, watermarks |
| PyYAML | any | Frontmatter and `.docs-gen.yaml` |
| [uv](https://docs.astral.sh/uv/) | any | The tree-sitter extractor's PEP 723 dependencies |

The runtime is otherwise standard library. There is no forge token, no JIRA
credential, and no network call outside the model command you choose.

Tree-sitter grammars come in through `uv run --script` for Go, JavaScript, and
TypeScript. Python is fingerprinted natively through the standard library's
`ast`, so a Python-only repository needs neither uv nor tree-sitter.

For development, add [ruff](https://docs.astral.sh/ruff/) and
[shellcheck](https://www.shellcheck.net/), both used by `make lint`.

## Development

```bash
make lint       # skillsaw, ruff, shellcheck
make test       # pytest
```

The tests run against a synthetic repository with a scripted history, so every
relevance verdict has one right answer. No model is involved: the writer's
`--llm-cmd` is a script returning a fixed document, which is what makes the
ownership guards testable.

```bash
python3 -m pytest tests/ -v
```

One test copies every skill the way an installer does, flat and with symlinks
dropped, then runs the whole pipeline from the result. That is what keeps the
`docs-engine` lookup honest.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow, and
[AGENTS.md](AGENTS.md) for architecture and conventions.

## Migrating from the ticket-driven pipeline

Releases before 0.5.0 carried a JIRA-anchored workflow for a publishing team,
producing AsciiDoc against the IBM and Red Hat style guides. That pipeline is
gone: 51 skills, 16 subagents, the JTBD apparatus, the AsciiDoc reference, the
style guide skills, the evaluation harness, and the hooks.

Pin `v0.4.1` if you depend on it.

Everything that survived is listed above. `docs-learn-code`'s extractors live on
inside `docs-engine`, and `docs-query-code` answers through the same step runner
as every other model call rather than dispatching a subagent.

Skill names all carry a `docs-` prefix now, so `/learn-code` is gone along with
the skill itself. Skills install into one flat directory shared with every other
plugin, and a name collision makes the installer skip this plugin whole rather
than the colliding skill, which one generic name like `changelog` was enough to
trigger.

## Versioning

Git tags (`v0.1.0`, `v0.2.0`). The `main` branch is the development head.

## License

[Apache License 2.0](LICENSE)

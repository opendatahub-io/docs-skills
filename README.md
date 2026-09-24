# docs-skills

Documentation tooling for [pi](https://pi.dev).

* Reads a code repository: its history, its modules, and its public API
* Decides which documents to write and which existing pages to change
* Writes and reviews with Vale hooks keeping token consumption lean

Claims about code are checked against the public API the analyzer extracted. Prose is checked by [Vale](https://vale.sh): a draft goes back to the model with its alerts until they clear. What will not clear after the last attempt is published with the page and reported against it, because a rule that has survived every repair pass is usually reading the document wrong rather than finding prose that is wrong. The reviewer reports rather than blocks wherever its verdict rests on matching text, which covers both the style findings and the check that compares backticked words against the extracted API. A run fails on what the tool can check structurally: a document it cannot parse, a broken fenced region, frontmatter naming a module the registry does not hold. `--strict` turns every finding back into a gate.

## Two entry points

`/docs` documents a repository from where it stands now. It reads the history, maps the modules, extracts the public API, and writes the foundation set: README, GET-STARTED, ARCHITECTURE, SECURITY and ROADMAP.

Each of the five is written only where the repository holds evidence for it, and the gates are deterministic, so deciding costs no model call:

| Document | Written when |
|---|---|
| `README.md` | the registry holds at least one module |
| `GET-STARTED.md` | a module of kind `cli` or `service` exists, and a manifest declares a runnable target |
| `ARCHITECTURE.md` | three or more modules, and at least one dependency edge between them |
| `SECURITY.md` | a module path or public symbol matches the security vocabulary, or a security tool config is present, and no policy file exists where GitHub reads one |
| `ROADMAP.md` | a deprecated symbol, an alpha or beta API version, or unreleased release notes |

A document whose gate fails is skipped with the gate named, never scaffolded with blanks. Five documents is what a 300-module repository produces and what a three-module one produces: the payload behind each is capped, so the output does not grow with the code.

Module detail is not published. It persists as committed JSON under `.docs-gen/<run>/`, where it grounds the five documents. A stale entry there is a cache miss the registry hash detects, rather than a sentence a reader believes.

`/docs-sync` keeps that documentation current. It compares an API fingerprint against a watermark, rewrites the documents citing a module that moved, and stops early when nothing changed. This is the one for CI.

```cmd
/docs: --help

options:
  -h, --help           show this help message and exit
  --repo REPO          Where documents are written
  --topic TOPIC        Narrow the run to a subject. Without it, the whole
                       repository
  --out OUT            The artifact root, one directory per run inside it.
                       Default .docs-gen
  --docs-dir DOCS_DIR
  --llm-cmd LLM_CMD
  --models             Print the resolved per-step models and exit
  --no-review
  --dry-run            Plan only, write nothing
  --sync-styles        Download the Vale packages used by the default prose
                       checks
```

## Reducing model token wastage with Vale

Vale acts as a cheap deterministic layer around expensive LLM work.

Vale replaces large standing prompt instructions for mechanical matters such as terminology, punctuation, passive voice, inflated wording, and document structure. Savings come from:

- Mechanical review findings cost no tokens at all.
- Repair calls send the draft and the alerts. It does not resend the write prompt, the module summaries or the symbol list, none of which decide whether a sentence hedges.
- Compactness rules constrain intermediate outputs, reducing material repeated in downstream responses.
- In interactive `pi` use, clean writes produce no Vale feedback and require no separate reviewer response.
- An edit is answered for the block it changed, so a narrow fix does not hand back alerts from the rest of the page.

## Prerequisites

- Python 3.10 or later, and git
- Vale 3.21 or later
- Pi 0.85.1 or later, with an authenticated provider

## Install

docs-skills runs inside [pi](https://pi.dev). Install pi and authenticate a provider:

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent

pi
```

In pi, run `/login` and select a provider. Then install the package:

```bash
pi install git:git@github.com:opendatahub-io/docs-skills@v0.4.0
```

To develop and test it, install from a local checkout of the repo:

```bash
pi install .
```

Install using one or the other method, never both.

### Working on docs-skills

A local source is a settings entry pointing at the directory. Nothing is copied, so `pi install .` is run once and edits to the checkout are live.

Skills, extensions and prompts are read when a session starts, so run `/reload` in an open session to pick up a change.

The extensions are typechecked against the pi version `package.json` pins, which is how a renamed tool schema is caught before it quietly stops a hook from firing:

```bash
npm ci
make typecheck
```

Nothing in `node_modules` ships. pi aliases both `@earendil-works` specifiers to its own copy when it loads an extension.

## Run it

Launch `pi` in the repository you want documented. In a new directory, sync the Vale styles first:

```bash
/docs --sync-styles
```

This creates `.vale.ini` and `.docs-gen/vale-packages` in pi's current directory. Style syncing needs no model.

Then run:

```bash
/docs "hierarchical KV cache tiering"
```

A bare first word is the topic, which narrows the run to a subject. Without one the whole repository is read.

Example output:

```bash
docs/changeset-2026-09-13-hierarchical-kv-cache-tiering/
  index.md
  new/
    configure-kv-cache-tiering.md
```

Re-running a topic clears its changeset first, so what you are looking at is only ever this run's work. Mark a draft `managed: manual` and it is kept, and the run says so.

The reasoning behind those drafts lands in `.docs-gen`, one directory per run, keyed the way the changeset is keyed:

```bash
.docs-gen/
  vale-packages/                             # what --sync-styles downloaded
  hierarchical-kv-cache-tiering/
    git-context.json   git-context.md   changes.json
    registry.json      api/             api-surface.json
    modules/           dep-pairs.json   ONBOARDING.md
    plan.json          plan.md
    write-report.json  review.json      vale-run/
```

Each step writes its answer as JSON and its own working notes as Markdown beside it. The Markdown is what the word budgets under `vale.budgets` apply to, and what the next step reads.

A run reads only its own directory and empties it before it starts, so neither another topic nor the same topic's last run can leave an answer behind to be picked up as this run's own. Only what a run downloads is shared, since re-fetching a style package per run spends time on bytes that do not differ.

### Keeping documentation current

`/docs-sync` is the incremental half. It writes a watermark recording which commit each module's documentation was written from, and the next run compares an API fingerprint against it.

```bash
/docs-sync --bootstrap --max-modules 20    # the first run, on a repo with no state
/docs-sync                                 # every run after that
```

Three signals stop it documenting its own last commit: HEAD authored by the configured `bot_author`, a change set confined to the paths this tool writes, and a watermark already level with HEAD for every module. `--force` skips the guard. Use it when debugging, not in CI.

### Run it unattended

The same commands work without a session, which is how they run from cron or a pipeline:

```bash
pi -p "/docs-sync --repo ."
```

`-p` processes the command and exits, and every line the chain writes goes to stdout as plain text. A step prefixes its own name, and a line reporting an outcome carries its severity after that, so a pipeline can grep for one without reading the wording:

```
docs: warning: no repository context: nothing committed yet
docs-review: error: 4 documents, 1 errors, 0 warnings
warning docs/guide.md: preview technology: say this once, near the top
```

Inside a session the same severities pick the colour each line is drawn in. Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Documents written |
| 1 | Nothing to write |
| 2 | A configuration error |
| 3 | A step failed |
| 5 | Every write was refused by the ownership contract (`/docs-sync`) |

Add `--offline` to pi to skip its startup network calls once the model catalog is cached.

## Configuration

Place a `.docs-gen.yaml` file at the root of the repository being documented. Every key has a default:

```yaml
generate:
  docs_dir: docs
  llm_cmd: "pi -p"
  # Optional. Every step not named here runs `llm_cmd`.
  # Possible values: analyze, plan, write, review, changelog
  llm_cmd_steps:
    plan:   "pi -p -nt --offline --model openai/gpt-5.6-sol:high"
    review: "pi -p -nt --offline --model anthropic/claude-opus-5:high"
  # Bare issue keys are scanned out of commit bodies only for these prefixes.
  issue_prefixes: [RHOAIENG]
  # /docs-sync only.
  bot_author: docs-bot@example.com
  max_modules_per_run: 20
  # Word ceilings on the chain's own working notes (default values shown).
  vale:
    budgets:
      git_context: 6000
      onboarding: 6000
      plan: 6000
      index: 6000
```

### Choosing a model per step

`llm_cmd` is the command every step runs. `llm_cmd_steps` overrides it for the steps you name.

A named step spawns the command it names, as its own process with its own model. Every step you do not name goes to the session's own model.

The entry is a command rather than a model pattern, which is what lets a step use a runner that is not pi at all:

```yaml
  llm_cmd_steps:
    plan:   "pi -p -nt --offline --model openai/gpt-5.6-luna:high"
    review: "claude -p"
```

Add `-nt` to a pinned `pi` command. Without it the spawned pi runs its full agent loop with tools, and every step here wants a single completion that returns JSON. `--offline` skips pi's startup network calls.

## Ownership

The `managed` field in a document's frontmatter decides what a run may do to it.

| `managed` | What the writer does |
| --- | --- |
| absent | Creates the file. Stamps `managed: generated` |
| `generated` | Regenerates the body. Keeps frontmatter a human set |
| `assisted` | Rewrites only the `docs-gen` fenced regions |
| `manual` | Never opens the file for writing. Emits a staleness finding |

Marking sets `manual` by default, so pointing this at an existing documentation tree protects every file on first contact. These are enforced in `docs-write`'s script, not in a prompt.

## Development

```bash
python3 -m pip install -r requirements.txt
npm ci
make lint
python3 -m pytest tests/ -q
```

## License

[Apache License 2.0](LICENSE)

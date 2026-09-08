# docs-skills

Documentation tooling for Claude Code, Codex, and a plain shell.

The repository carries two tracks.

**[Documentation generator](#documentation-generator).** Point it at a code
repository and get developer documentation in plain Markdown. Merge to main and
get the delta. Deterministic where it can be, harness-agnostic throughout, and
built to run unattended in CI. This is where the project is going.

**[Ticket-driven pipeline](#ticket-driven-pipeline).** The JIRA-anchored
workflow for a publishing team, producing AsciiDoc against the IBM and Red Hat
style guides. Still supported, and slated for removal once the generator has run
against a real repository. Nothing in it changed in this release.

## Documentation generator

Seven skills. No subagent dispatch, no forge token, and no assumption that a
documentation ticket exists before work begins.

```bash
# First run on a repository with no documentation state
python3 skills/docs-sync/scripts/sync.py --repo /path/to/code \
    --bootstrap --max-modules 20 --llm-cmd "claude -p"

# Every run after that
python3 skills/docs-sync/scripts/sync.py --repo /path/to/code \
    --since-watermark .docs-state.json --llm-cmd "claude -p"
```

### The skills

| Skill | Model calls | What it does |
|---|---|---|
| [`docs-git-context`](skills/docs-git-context/) | none | Revision range, commit corpus, module attribution, hotspots, watermark |
| [`docs-repo-analyze`](skills/docs-repo-analyze/) | one per module | Module registry, public API extraction, dependency graph, onboarding guide |
| [`docs-write`](skills/docs-write/) | one per document | Markdown per module, with ownership enforced in script |
| [`docs-review`](skills/docs-review/) | zero on most runs | Grounding, staleness, fence freshness, frontmatter |
| [`docs-sync`](skills/docs-sync/) | none directly | The CI entry point. Composes the rest |
| [`docs-changelog`](skills/docs-changelog/) | zero above ratio 0.7 | Release notes from commit history |
| [`docs-engine`](skills/docs-engine/) | none | Shared runtime the six above read. Not invoked directly |
| [`query-code`](skills/query-code/) | one | Questions about an analyzed codebase |

### How it decides what to rewrite

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

### Ownership

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

### Harness agnosticism

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

### Configuration

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

### Artifacts

Pipeline state lives under `.docs-gen/` in the documented repository.
`registry.json`, `api/`, and `api-surface.json` are committed; everything else
is transient. [`config/gitignore.fragment`](skills/docs-engine/config/gitignore.fragment) has the
split.

The durable set is committed rather than cached because a `registry_hash` match
skips module analysis, which presumes the registry is already on disk, and the
grounding check reads `api-surface.json` on every run. A cold CI cache would
produce a matching hash with nothing behind it.

### Per-language knowledge

Two files per language, kept apart because they have different consumers.

[`lib/ast/languages.yaml`](skills/docs-engine/scripts/lib/ast/languages.yaml) holds parse rules: module
boundaries, config file names, what counts as public. Read by `repo-analyze`'s
scripts.

[`languages/<lang>.md`](skills/docs-engine/languages/) holds documentation conventions: where docs live, which
reference generator to defer to, doc comment format, example conventions,
identifier casing in prose. The body reaches the writer prompt verbatim, and the
YAML frontmatter carries the values a script executes.

Adding a language is adding a file. Python and Go ship today.

### CI

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

## Ticket-driven pipeline

The JIRA-anchored workflow, unchanged in this release.

### Skills

| Category | Skills | Description |
|----------|--------|-------------|
| **Workflow** | `docs-orchestrator`, `docs-workflow-start`, `docs-workflow-requirements`, `docs-workflow-planning`, `docs-workflow-writing`, `docs-workflow-code-analysis`, `docs-workflow-pr-analysis`, `docs-workflow-scope-req-audit`, `docs-workflow-style-review`, `docs-workflow-tech-review`, `docs-workflow-create-merge-request`, `docs-workflow-create-jira`, `docs-workflow-jira-ready` | End-to-end documentation pipeline with YAML-defined step lists, conditional execution, and resume capability |
| **Code Analysis** | `learn-code`, `query-code`, `understand-pull-request` | Tree-sitter AST parsing, module registry, cross-module relationships, PR impact analysis |
| **Generator** | `docs-engine`, `docs-git-context`, `docs-repo-analyze`, `docs-write`, `docs-review`, `docs-sync`, `docs-changelog` | See [Documentation generator](#documentation-generator) |
| **Review** | `docs-review-style`, `docs-review-technical`, `docs-review-content-quality`, `docs-review-modular-docs` | Multi-agent style and technical review with confidence scoring and claim validation |
| **Style Guides** | `ibm-sg-*` (8 skills), `rh-ssg-*` (8 skills) | IBM Style Guide and Red Hat Supplementary Style Guide compliance |
| **Integration** | `jira-reader`, `jira-writer`, `git-pr-reader`, `article-extractor`, `docs-convert-gdoc-md`, `redhat-docs-toc` | JIRA, GitHub/GitLab, Google Docs, and web content integration |
| **Other** | `rn-known-issues` | Release notes known issues audit |

### Agents

| Agent | Description |
|-------|-------------|
| `docs-planner` | Documentation architecture using JTBD framework |
| `docs-writer` | Content creation (CONCEPT/PROCEDURE/REFERENCE/ASSEMBLY) |
| `docs-reviewer` | Style and modular docs compliance review |
| `technical-reviewer` | Technical accuracy review with code-aware validation |
| `repo-mapper` | Codebase module detection and registry creation |
| `module-analyzer` | Deep analysis of single codebase module |
| `relationship-analyzer` | Cross-module coupling and dependency analysis |
| `synthesis-writer` | Combine module analyses into ONBOARDING.md |
| `code-questioner` | Answer questions about analyzed codebases |
| `requirements-discoverer` | Lightweight JIRA/PR/spec requirement enumeration |
| `requirements-analyst` | Deep per-requirement analysis with acceptance criteria |
| `requirement-classifier` | Classify requirements by code evidence status |
| `pr-repo-summarizer` | Quick repository overview for PR context |
| `pr-change-analyzer` | Analyze PR changes against module registry |
| `pr-synthesis-writer` | Combine PR data into PR-ANALYSIS.md |

## Installation

### From GitHub (marketplace)

Add the repo as a marketplace, then install the plugin:

```bash
claude plugin marketplace add opendatahub-io/docs-skills
claude plugin install docs-skills@opendatahub-docs
```

### From local clone

```bash
git clone git@github.com:opendatahub-io/docs-skills.git
claude --plugin-dir ./docs-skills
```

### For development

Use `--plugin-dir` to load the plugin without installing. Run `/reload-plugins` after making changes:

```bash
claude --plugin-dir /path/to/docs-skills
```

## Prerequisites

### Environment variables

Create an `.env` file with your tokens. Use either `~/.env` (global) or `.env` in the project root (overrides global):

```bash
JIRA_API_TOKEN=your_jira_api_token
JIRA_EMAIL=you@example.com
# Optional: defaults to https://redhat.atlassian.net
JIRA_URL=https://your-jira-instance.atlassian.net
# Required scopes: "repo" for private repos, "public_repo" for public repos
GITHUB_TOKEN=your_github_pat
# Required scope: "api"
GITLAB_TOKEN=your_gitlab_pat
```

### Software dependencies

#### Required

| Tool | Min version | Install | Purpose |
|------|-------------|---------|---------|
| Python | 3.10+ | [python.org](https://www.python.org/) | Script execution |
| [uv](https://docs.astral.sh/uv/) | — | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Runs PEP 723 scripts with auto-managed deps |
| git | 2.0+ | System package manager | Version control |
| jq | — | System package manager | JSON processing in shell scripts |
| curl | — | System package manager | HTTP requests |

#### Conditional (per-feature)

| Tool | Install | Required for |
|------|---------|--------------|
| `gh` | `dnf install gh` / [cli.github.com](https://cli.github.com/) | GitHub PR/issue workflows |
| `glab` | `dnf install glab` / [gitlab.com](https://gitlab.com/gitlab-org/cli) | GitLab MR workflows |
| `gcloud` | [cloud.google.com/sdk](https://cloud.google.com/sdk/docs/install) | Google Docs export (`docs-convert-gdoc-md`) — alternative: configure [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) |
| [Vale](https://vale.sh/) | `dnf copr enable mczernek/vale && dnf install vale` / `brew install vale` | `lint-with-vale` style linting |

#### Development / linting

| Tool | Install | Used by |
|------|---------|---------|
| [ruff](https://docs.astral.sh/ruff/) | `uv tool install ruff` | `make lint` |
| [shellcheck](https://www.shellcheck.net/) | `dnf install shellcheck` | `make lint` |

#### Python packages (auto-managed by uv)

These are declared as PEP 723 inline metadata in their scripts and installed automatically by `uv run --script` — no manual `pip install` needed:

| Script | Packages |
|--------|----------|
| `jira-reader/scripts/jira_reader.py` | `jira`, `urllib3`, `ratelimit` |
| `jira-writer/scripts/jira_writer.py` | `jira`, `ratelimit` |
| `git-pr-reader/scripts/git_pr_reader.py` | `PyGithub`, `python-gitlab`, `pyyaml` |
| `article-extractor/scripts/article_extractor.py` | `requests`, `beautifulsoup4`, `html2text` |
| `redhat-docs-toc/scripts/toc_extractor.py` | `requests`, `beautifulsoup4` |
| `learn-code/scripts/extract_public_api_treesitter.py` | `tree-sitter`, `tree-sitter-go`, `tree-sitter-javascript`, `tree-sitter-python`, `tree-sitter-typescript` |
| `docs-convert-gdoc-md/scripts/gdoc2md.py` | `google-auth`, `python-pptx` |

## Quick Start

Run the docs orchestrator from the root of your documentation repository. For the
code-documentation generator, see [Documentation generator](#documentation-generator).

```bash
# Basic workflow from a JIRA ticket
/docs-orchestrator PROJ-123

# With source code analysis
/docs-orchestrator PROJ-123 --repo https://github.com/org/repo

# With PR context
/docs-orchestrator PROJ-123 --pr https://github.com/org/repo/pull/456

# Interactive guided start
/docs-workflow-start PROJ-123
```

## Workflow Customization

The orchestrator runs a YAML-defined step list. Customize per-repo by placing a workflow YAML in `.agent_workspace/`:

```bash
mkdir -p .agent_workspace
# Copy the default workflow and edit it
cp $(claude plugin path docs-skills)/skills/docs-orchestrator/defaults/docs-workflow.yaml \
   .agent_workspace/docs-workflow.yaml
```

See the workflow YAML for available steps, conditional execution (`when:` field), and dependency graph (`inputs:` field).

### Key flags

| Flag | Description |
|------|-------------|
| `--repo <url-or-path>` | Source code repository for learn-code analysis |
| `--pr <url>` | PR/MR URL to include in requirements analysis (repeatable) |
| `--no-source-repo` | Skip source resolution and all source-dependent steps |
| `--auto-discover-repos` | Skip confirmation when secondary repos are discovered |
| `--max-secondary-repos <N>` | Maximum secondary repos to clone (default: 3) |
| `--mkdocs` | Generate Material for MkDocs Markdown instead of AsciiDoc |
| `--create-merge-request` | Create branch, commit, push, and open MR/PR |
| `--workflow <name>` | Use a named workflow variant |
| `--draft` | Write output to `artifacts/` staging area |

## Development

### Validate changes

```bash
make lint       # skillsaw, ruff, shellcheck
make test       # pytest
```

The generator's tests run against a synthetic repository with a scripted
history, so every relevance verdict has one right answer. No model is involved:
the writer's `--llm-cmd` is a script returning a fixed document, which is what
makes the ownership guards testable.

```bash
python3 -m pytest tests/test_pipeline.py tests/test_ownership.py \
    tests/test_step_runner.py -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development workflow.

### Prerequisites

See [Software dependencies](#software-dependencies) above. For linting, also install `ruff` and `shellcheck`.

## Evaluation

The `eval/` directory contains test cases for evaluating skill quality using the [agent-eval-harness](https://github.com/opendatahub-io/agent-eval-harness).

## Architecture

See [AGENTS.md](AGENTS.md) for architecture details and conventions.

## Versioning

Use git tags (`v0.1.0`, `v0.2.0`, etc.) for releases. The `main` branch is the development head.

## License

[Apache License 2.0](LICENSE)

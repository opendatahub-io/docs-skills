# docs-skills

Claude Code plugin for documentation workflows. Provides orchestrator skills, review agents, code analysis tools, and style guide compliance checking for AsciiDoc and Markdown documentation.

## Overview

This plugin provides the documentation automation layer for Claude Code. It includes skills for requirements analysis, documentation planning and writing, code-grounded technical review, style guide compliance, and CI/CD integration with JIRA and Git platforms.

### Skills

| Category | Skills | Description |
|----------|--------|-------------|
| **Workflow** | `docs-orchestrator`, `docs-workflow-start`, `docs-workflow-requirements`, `docs-workflow-planning`, `docs-workflow-writing`, `docs-workflow-code-analysis`, `docs-workflow-pr-analysis`, `docs-workflow-scope-req-audit`, `docs-workflow-style-review`, `docs-workflow-tech-review`, `docs-workflow-create-merge-request`, `docs-workflow-create-jira`, `docs-workflow-jira-ready` | End-to-end documentation pipeline with YAML-defined step lists, conditional execution, and resume capability |
| **Code Analysis** | `learn-code`, `query-code`, `understand-pull-request` | Tree-sitter AST parsing, module registry, cross-module relationships, PR impact analysis |
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
| Node.js 18+ / npm | [nodejs.org](https://nodejs.org/) | `learn-code` tree-sitter AST parsing |
| `gh` | `dnf install gh` / [cli.github.com](https://cli.github.com/) | GitHub PR/issue workflows |
| `glab` | `dnf install glab` / [gitlab.com](https://gitlab.com/gitlab-org/cli) | GitLab MR workflows |
| `gcloud` | [cloud.google.com/sdk](https://cloud.google.com/sdk/docs/install) | Google Docs export (`docs-convert-gdoc-md`) |
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
| `docs-convert-gdoc-md/scripts/gdoc2md.py` | `python-pptx` |

## Quick Start

Run the docs orchestrator from the root of your documentation repository:

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
make lint
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

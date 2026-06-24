---
name: docs-orchestrator
description: Documentation workflow orchestrator. Uses a Python state machine driver for all deterministic logic (progress, args, post-processing, iteration). Claude runs the loop — invoke init, execute each skill action, call step-done, repeat.

argument-hint: <ticket> [--workflow <name>] [--pr <url>...] [--source-code-repo <url-or-path>...] [--no-source-repo] [--auto-discover-repos] [--max-secondary-repos <N>] [--mkdocs] [--draft] [--docs-repo-path <path>] [--create-jira <PROJECT>] [--create-merge-request]

allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Skill, AskUserQuestion
---

# Docs Orchestrator

**When the user invokes `/docs-orchestrator` or `/docs-tools:docs-orchestrator`, run THIS skill directly. Do NOT redirect to `docs-workflow-start` or any other skill.**

All deterministic logic — progress file management, step argument construction, post-processing, tech review iteration, when-condition evaluation — is handled by `docs_orchestrator.py`. Claude's role is: call the driver, run the skill it says, report the result back to the driver.

## Pre-flight

Install the workflow completion Stop hook (safe to re-run, skips if already installed):

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/setup-hooks.sh
```

**Do not** source `.env` files or check for tokens/CLIs here — Python scripts load `.env` files and validate prerequisites themselves, producing clear errors on failure.

## Arguments

When displaying available options to the user (e.g., on skill load or when asking for flags), reproduce the descriptions below **verbatim** — do not summarize or paraphrase them.

- `$1` — JIRA ticket ID (required). If missing, STOP and ask the user.
- `--workflow <name>` — Use `.agent_workspace/docs-<name>.yaml` instead of `docs-workflow.yaml`. Allows running alternative pipelines (e.g., writing-only, review-only). If the project-level file does not exist, fall back to the matching plugin default at `skills/docs-orchestrator/defaults/docs-<name>.yaml`
- `--pr <url>...` — PR/MR URLs (space-delimited, one or more). Accepts GitHub PRs (`gh` CLI) and GitLab MRs (`glab` CLI). Used both as requirements input (agent reads diffs/descriptions) and for source repo resolution (repo URL and branch derived from the first PR/MR). When multiple PRs from different repos are provided, all repos are resolved and treated equally as source material
- `--mkdocs` — Use Material for MkDocs format instead of AsciiDoc
- `--draft` — Write documentation to the staging area instead of directly into the repo
- `--docs-repo-path <path>` — Target documentation repository for UPDATE-IN-PLACE mode. **Precedence**: if both `--docs-repo-path` and `--draft` are passed, `--docs-repo-path` wins — the driver logs a warning
- `--source-code-repo <url-or-path>...` — Source code repository/repositories for code analysis and requirements enrichment (space-delimited, one or more)
- `--create-jira <PROJECT>` — Create a linked JIRA ticket in the specified project after the workflow completes. Runs as a standalone step
- `--create-merge-request` — Create a branch, commit, push, and open a merge request or pull request after reviews complete
- `--no-source-repo` — Skip source repo resolution and all source-dependent steps
- `--auto-discover-repos` — Skip the confirmation prompt when secondary repos are discovered
- `--max-secondary-repos <N>` — Maximum number of secondary repos to clone (default: 3)

### Examples

```bash
# Minimal — just a ticket
/docs-orchestrator PROJ-123

# PR-driven with MkDocs output
/docs-orchestrator PROJ-123 --pr https://github.com/org/repo/pull/42 --mkdocs

# Multiple PRs, written to a separate docs repo
/docs-orchestrator PROJ-123 \
  --pr https://github.com/org/backend/pull/10 https://gitlab.example.com/org/frontend/-/merge_requests/5 \
  --docs-repo-path /home/user/docs-repo

# Source repo without PRs, draft mode, with merge request creation
/docs-orchestrator PROJ-123 \
  --source-code-repo https://github.com/org/operator \
  --draft \
  --create-merge-request

# Local source repo + PR
/docs-orchestrator PROJ-123 \
  --source-code-repo /home/user/local-checkout \
  --pr https://github.com/org/repo/pull/99

# Custom workflow YAML
/docs-orchestrator PROJ-123 --workflow quick
```

## Execution

The orchestrator uses a simple loop driven by `docs_orchestrator.py`. All progress file writes, argument construction, post-processing logic, and iteration decisions are handled by the Python driver.

### Step 1: Initialize

Build the CLI args from the user's input and call init:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docs_orchestrator.py init <TICKET> [flags...]
```

Map user flags directly: `--pr`, `--source-code-repo`, `--mkdocs`, `--draft`, `--docs-repo-path`, `--create-merge-request`, `--create-jira <PROJECT>`, `--no-source-repo`, `--auto-discover-repos`, `--max-secondary-repos <N>`, `--workflow <name>`.

The driver returns a JSON action on stdout. Capture it.

### Step 2: Action loop

Read the action JSON. The `action` field determines what to do:

#### `action: "run_skill"`

The driver says to run a step skill. The JSON includes:
- `skill` — the qualified skill name to invoke (e.g., `docs-tools:docs-workflow-requirements`)
- `args` — the pre-built args string to pass to the skill
- `step` — the step name (for step-done reporting)
- `message` — a status message to display

1. Display the `message` to the user
2. Display any `warnings` or `messages` arrays if present
3. Invoke the skill:

```
Skill: <skill>, args: "<args>"
```

4. After the skill completes, report the result back to the driver:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docs_orchestrator.py step-done <TICKET> <step>
```

If the skill failed (threw an error, produced no output), add `--failed`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docs_orchestrator.py step-done <TICKET> <step> --failed
```

5. The driver returns the next action JSON. Go back to the top of the loop.

#### `action: "complete"`

The workflow is done. The JSON includes:
- `summary.steps_completed` — list of completed step names
- `summary.steps_skipped` — list of skipped step names
- `summary.mr_url` — MR/PR URL if created
- `summary.jira_url` / `summary.jira_key` — JIRA URL and key if created
- `summary.module_count` — number of modules from planning
- `summary.file_count` — number of files written
- `summary.warnings` — any warnings accumulated during the workflow

Display a completion summary to the user with all available fields.

#### `action: "fail"`

The workflow failed. The JSON includes:
- `step` — the step that failed
- `reason` — why it failed
- `message` — a message to display

Display the failure message and stop.

### Step 3: Confirmation gate (create-merge-request only)

Before executing the `create-merge-request` step, the action loop should prompt the user:

> The workflow is ready to create a merge request. Review the output and confirm:
> - Commit and push? (proceeds with create-merge-request)
> - Skip? (marks step as skipped)

If the user declines, call step-done with `--failed` and the driver handles the rest.

## Context management

The Python driver owns all workflow state in the progress file. After context compaction, the driver reconstructs everything it needs from disk — no conversation state is required to continue.

The orchestrator runs the entire pipeline in a single session. The progress file is the safety net for genuine session interruptions.

## Resume

To resume a prior workflow, call init again with the same ticket. The driver detects the existing progress file, validates completed steps still have output on disk, and returns the next action.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docs_orchestrator.py init <TICKET> [additional flags]
```

Additional flags on resume (e.g., `--create-jira`) are merged into the existing options.

---
name: docs-orchestrator
description: Documentation workflow orchestrator. Reads the step list from .agent_workspace/docs-workflow.yaml (or the plugin default). Runs steps sequentially, manages progress state, handles iteration and confirmation gates. Claude is the orchestrator — the YAML is a step list, not a workflow engine.

argument-hint: <ticket> [--workflow <name>] [--pr <url>...] [--source-code-repo <url-or-path>...] [--no-source-repo] [--auto-discover-repos] [--max-secondary-repos <N>] [--mkdocs] [--draft] [--docs-repo-path <path>] [--create-jira <PROJECT>] [--create-merge-request]

allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Skill, AskUserQuestion
---

# Docs Orchestrator

**When the user invokes `/docs-orchestrator`, run THIS skill directly. Do NOT redirect to `docs-workflow-start` or any other skill.**

Claude is the orchestrator. The YAML is a step list. The hook is a safety net.

This skill teaches you how to run a documentation workflow pipeline. You read the step list from YAML, run each step skill sequentially, manage progress state via a JSON file, and handle iteration loops and confirmation gates.

## Pre-flight

Install the workflow completion Stop hook (safe to re-run, skips if already installed):

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/setup-hooks.sh
```

**Do not** source `.env` files or check for tokens/CLIs here — Python scripts (`jira_reader.py`, `resolve_source.py`, etc.) load `.env` files and validate prerequisites themselves, producing clear errors on failure.

## Parse arguments

When displaying available options to the user (e.g., on skill load or when asking for flags), reproduce the descriptions below **verbatim** — do not summarize or paraphrase them.

- `$1` — JIRA ticket ID (required). If missing, STOP and ask the user.
- `--workflow <name>` — Use `.agent_workspace/docs-<name>.yaml` instead of `docs-workflow.yaml`. Allows running alternative pipelines (e.g., writing-only, review-only). If the project-level file does not exist, fall back to the matching plugin default at `skills/docs-orchestrator/defaults/docs-<name>.yaml`
- `--pr <url>...` — PR/MR URLs (space-delimited, one or more). Accepts GitHub PRs (`gh` CLI) and GitLab MRs (`glab` CLI). Used both as requirements input (agent reads diffs/descriptions) and for source repo resolution (repo URL and branch derived from the first PR/MR). When multiple PRs from different repos are provided, all repos are resolved and treated equally as source material
- `--mkdocs` — Use Material for MkDocs format instead of AsciiDoc. Propagates to the writing step (generates `.md` with MkDocs front matter) and style-review step (applies Markdown-appropriate rules). Sets `options.format` to `"mkdocs"` in the progress file
- `--draft` — Write documentation to the staging area (`.agent_workspace/<ticket>/writing/`) instead of directly into the repo. Uses DRAFT placement mode: no framework detection, no file placement into the target repo. Without this flag, UPDATE-IN-PLACE is the default
- `--docs-repo-path <path>` — Target documentation repository for UPDATE-IN-PLACE mode. The docs-writer explores this directory for framework detection (Antora, MkDocs, Docusaurus, etc.) and writes files there instead of the current working directory. Propagates to `writing` and `create-merge-request` steps (mapped to their internal `--repo-path` flag). **Precedence**: if both `--docs-repo-path` and `--draft` are passed, `--docs-repo-path` wins — log a warning and ignore `--draft`
- `--source-code-repo <url-or-path>...` — Source code repository/repositories for code analysis and requirements enrichment (space-delimited, one or more). Accepts remote URLs (https://, git@, ssh:// — each shallow-cloned to `.agent_workspace/<ticket>/code-repo/<repo_name>/`) or local paths (used directly). The first repo is treated as primary; additional repos are returned as `additional_repos` in the result. Passed to requirements, code-analysis, writing, and technical-review steps (mapped to their internal `--repo` flag). Without `--pr`, the entire repo is the subject matter; with `--pr`, the PR branch is checked out on the primary repo so code-analysis reflects the PR's state. Takes highest priority in source resolution, overriding `source.yaml` and PR-derived URLs
- `--create-jira <PROJECT>` — Create a linked JIRA ticket in the specified project after the planning step completes. Runs the standalone `docs-workflow-create-jira` workflow (use `--workflow workflow-create-jira`). Requires `JIRA_API_TOKEN` to be set
- `--create-merge-request` — Create a branch, commit, push, and open a merge request or pull request after reviews complete. Activates the `create-merge-request` workflow step (guarded by `when: create_merge_request`). Off by default
- `--no-source-repo` — Skip source repo resolution and all source-dependent steps (scope-req-audit). The workflow runs without source grounding. Use for tickets with no associated source code repository, or pass on resume after the workflow stops due to no repo being found
- `--auto-discover-repos` — Skip the confirmation prompt when secondary repos are discovered by scope-req-audit. Useful for CI/automation where interactive prompts are not available. Has no effect if no secondary repos are found
- `--max-secondary-repos <N>` — Maximum number of secondary repos to clone after scope-req-audit (default: 3). Repos are ranked by the number of associated requirements

### Examples

```bash
# Minimal — just a ticket
/docs-orchestrator PROJ-123

# PR-driven with MkDocs output
/docs-orchestrator PROJ-123 --pr https://github.com/org/repo/pull/42 --mkdocs

# Multiple PRs from different repos, written to a separate docs repo
/docs-orchestrator PROJ-123 \
  --pr https://github.com/org/backend/pull/10 https://gitlab.example.com/org/frontend/-/merge_requests/5 \
  --docs-repo-path /home/user/docs-repo

# Source repo without PRs, draft mode, with merge request creation
/docs-orchestrator PROJ-123 \
  --source-code-repo https://github.com/org/operator \
  --draft \
  --create-merge-request

# Local source repo + PR (checks out PR branch within repo)
/docs-orchestrator PROJ-123 \
  --source-code-repo /home/user/local-checkout \
  --pr https://github.com/org/repo/pull/99

# Custom workflow YAML
/docs-orchestrator PROJ-123 --workflow quick
```

## Resolve source repository

After parsing arguments and before running steps, resolve the source code repository if one is configured. This makes the repo available to all downstream steps that need it (requirements, code-analysis, writing).

All clone, verify, PR-resolution, and source.yaml logic is handled by the `resolve_source.py` script. The orchestrator calls the script and acts on the JSON result.

### Pre-flight resolution

Run the script with whatever source information is available from CLI args:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/resolve_source.py \
  --base-path <base_path> \
  [--repo <url-or-path>...] \
  [--pr <url>...]
```

The script checks sources in priority order:

1. **CLI `--source-code-repo` flag** — clone or verify the path
2. **Per-ticket `source.yaml`** — read and apply existing config
3. **PR-derived** — resolve repo URL and branch from `--pr` via `gh pr view` or `glab mr view`
4. **`discovered_repos.json`** — read repos discovered by the requirements step (from JIRA graph walk)
5. **No source** — exit code 2, defer resolution until after requirements

The script outputs JSON to stdout:

```json
{
  "status": "resolved",
  "repo_path": ".agent_workspace/proj-123/code-repo/operator",
  "repo_url": "https://github.com/org/operator",
  "ref": "pr-branch-name",
  "scope": null
}
```

### Handle the result

| Exit code | `status` | Action |
|---|---|---|
| 0 | `resolved` | Set `has_source_repo = true`. Record `options.source` in the progress file from the JSON fields (`repo_path`, `repo_url`, `ref`, `scope`) |
| 1 | `error` | **STOP** with the error `message` from the JSON |
| 2 | `no_source` | Mark steps with `when: has_source_repo` as `deferred`. Source resolution will be retried after requirements (see [Post-requirements source resolution](#post-requirements-source-resolution)) |

If `discovered_repos` is present in the result (multiple repos found), log all resolved repos. If `additional_repos` is present, record them in the progress file alongside the primary source. If `warnings` is present, log each warning.

### Per-ticket source config schema

Writers can create `<base-path>/source.yaml` before starting a workflow to pre-configure the source repo and scope. The script also writes this file after a successful clone so that resume picks it up automatically.

```yaml
# .agent_workspace/<ticket>/source.yaml
repo: https://github.com/org/operator   # URL or local path (required)
ref: main                                # branch, tag, or commit (default: HEAD)
scope:
  include:                               # glob patterns — what to index and search
    - "src/controllers/**"
    - "pkg/api/v1/**"
    - "README.md"
  exclude:                               # glob patterns — what to skip
    - "**/vendor/**"
    - "**/testdata/**"
    - "**/*_test.go"
```

All fields except `repo` are optional. If `scope` is omitted, the entire repository is in scope.

## Load the step list

### 1. Determine the YAML file

- If `--workflow <name>` was specified → `.agent_workspace/docs-<name>.yaml`
- If that project-level file doesn't exist → fall back to `skills/docs-orchestrator/defaults/docs-<name>.yaml`
- Otherwise → `.agent_workspace/docs-workflow.yaml`
- If that project-level file doesn't exist → fall back to `skills/docs-orchestrator/defaults/docs-workflow.yaml`

### 2. Read the YAML

Read the YAML file and extract the ordered step list. Each step has: `name`, `skill`, `description`, optional `when`, and optional `inputs`.

### 3. Evaluate `when` conditions

- `when: create_merge_request` → run this step only if `--create-merge-request` was passed
- `when: has_pr` → run this step only if a PR/MR URL is available (passed via `--pr` or discovered from JIRA by the requirements step). Evaluated after source resolution completes — if a PR URL was resolved from `options.source` or `options.pr_urls`, the condition is met
- `when: has_source_repo` → evaluation depends on timing:
  - If `--no-source-repo` was passed → mark as `skipped` immediately (source resolution was skipped entirely)
  - If a source repo was already resolved pre-flight (via `--source-code-repo`, `--pr`, or `source.yaml`) → step runs normally (`pending`)
  - If no source is resolved yet but post-requirements discovery is possible (case 4 above) → mark the step `deferred` (not `skipped`). The orchestrator re-evaluates after requirements completes
  - After post-requirements resolution: `deferred` steps become `pending` (source found) or the workflow stops (see [No source found](#3-no-source-found))
- `when: has_many_requirements` → deferred until the `requirements` step completes. Evaluated using `requirement_count` from the requirements sidecar (see [`when: has_many_requirements` condition](#when-has_many_requirements-condition))
- Steps with no `when` always run
- Steps that don't meet their `when` condition and cannot be deferred are marked `skipped` in the progress file

### 4. Validate the step list

All of the following must be true. If any check fails, **STOP** with a clear error:

- All step names are unique
- All `skill` references resolve to a known skill (bare names like `docs-workflow-writing` are preferred; fully qualified `plugin:skill` format is also accepted)
- Input dependencies are satisfied — for each step with `inputs`, every referenced step name must be present in the step list (unless it has a `when` condition that would skip it)

### Input dependencies

Steps declare their inputs as a list of upstream step names in the YAML:

```yaml
- name: writing
  skill: docs-workflow-writing
  inputs: [planning]

- name: create-merge-request
  skill: docs-workflow-create-merge-request
  when: create_merge_request
  inputs: [writing, style-review, technical-review]
```

The orchestrator validates at load time that every step name in `inputs` exists in the step list. Step skills read their input data from the upstream step's output folder by convention (see below).

**Conditional input dependencies**: If an upstream step in `inputs` has a `when` condition and was `skipped`, that dependency is considered satisfied. The downstream step is responsible for checking whether the optional input data actually exists (e.g., the writing step checks for `code-analysis/ONBOARDING.md` and uses it if present, but proceeds without it). Only upstream steps that ran and `failed` block downstream execution.

**Custom workflow validation**: If a step's `inputs` references a step that does not exist in the current YAML step list, fail at load time with an error (e.g., "Step 'writing' requires 'planning', but 'planning' is not in the step list").

## Output conventions

Every step writes to a predictable folder based on the ticket ID and step name:

```
.agent_workspace/<ticket>/<step-name>/
```

The ticket ID is converted to **lowercase** for directory names (e.g., `PROJ-123` → `proj-123`).

### Resolve base path

Resolve the base path to an absolute path so agents (which may run in a different working directory) can locate files correctly:

```bash
BASE_PATH="$(cd "$(git rev-parse --show-toplevel)" && pwd)/.agent_workspace/${TICKET_LOWER}"
```

Use this absolute `BASE_PATH` for the progress file's `base_path` field and for all `--base-path` arguments passed to step skills.

### Folder structure

```
.agent_workspace/proj-123/
  source.yaml                        (per-ticket source config, if applicable)
  code-repo/
    <repo-name>/                     (each repo gets its own subdirectory)
  requirements/
    requirements.md
    step-result.json                 (sidecar: title)
  code-analysis/                       (if source repo is available)
    ONBOARDING.md
    registry.json
    detection.json
    summaries/
    relationships/
    step-result.json                 (sidecar: module_count, relationship_count, languages_detected, repo_path)
  code-analysis-<repo-name>/           (additional repos, if any — same structure as code-analysis/)
    ONBOARDING.md
    registry.json
    detection.json
    summaries/
    relationships/
    step-result.json
  pr-analysis/                         (if PR is available)
    PR-<number>-ANALYSIS.md
    step-result.json                 (sidecar: pr_number, pr_url, modules_affected, platform)
  planning/
    plan.md
    step-result.json                 (sidecar: module_count)
  writing/
    _index.md
    step-result.json                 (sidecar: files, mode, format)
    assembly_*.adoc (or docs/*.md for mkdocs)
    modules/
  technical-review/
    review.md
    step-result.json                 (sidecar: confidence, severity_counts)
  style-review/
    review.md
    step-result.json                 (sidecar: common fields only)
  create-merge-request/
    step-result.json                 (sidecar: commit_sha, branch, pushed, url, action, platform, skipped)
  workflow/
    docs-workflow_proj-123.json
```

Each step skill knows its own output folder and writes there. Each step reads input from upstream step folders referenced in its `inputs` list. The orchestrator passes the base path `.agent_workspace/<ticket>/` — step skills derive everything else by convention.

### Step result sidecars

Every step that produces markdown output also writes a `step-result.json` sidecar with structured metadata. See [schema/step-result-schema.md](schema/step-result-schema.md) for the full schema. Downstream scripts and the orchestrator prefer sidecar data when present, falling back to parsing the markdown output for backward compatibility.

## Progress file

Claude writes the progress file directly using the Write tool. Create it after parsing arguments, before step 1. Update it after each step. Also write the active workflow marker at the same time (see [Active workflow marker](#active-workflow-marker)).

**Location**: `.agent_workspace/<ticket>/workflow/<workflow-type>_<ticket>.json`

The `workflow_type` field and filename prefix match the YAML's `workflow.name`. This allows multiple workflow types to run against the same ticket without conflict.

### Schema

```json
{
  "workflow_type": "<workflow.name from YAML>",
  "ticket": "<TICKET>",
  "base_path": "/absolute/path/to/.agent_workspace/<ticket>",
  "status": "in_progress",
  "created_at": "<ISO 8601>",
  "updated_at": "<ISO 8601>",
  "options": {
    "format": "adoc",
    "draft": false,
    "create_merge_request": false,
    "pr_urls": [],
    "source": null,
    "additional_sources": [],
    "no_source_repo": false,
    "auto_discover_repos": false,
    "max_secondary_repos": 3
  },
  "step_order": ["requirements", "code-analysis", "pr-analysis", "planning", "writing", ...],
  "steps": {
    "<step-name>": {
      "status": "pending",
      "output": null,
      "result": null
    }
  }
}
```

The `output` field records the step's output folder path (e.g., `.agent_workspace/proj-123/writing/`) once completed.

The `result` field stores selected sidecar data after each step completes. This lets the orchestrator make downstream decisions and display summaries without re-reading sidecar files from disk — especially important on resume. Set to `null` until the step completes; then populated from `step-result.json` (see [Step-specific post-processing](#step-specific-post-processing)).

### Status values

| Value | Meaning |
|---|---|
| `pending` | Not yet started |
| `in_progress` | Currently running |
| `completed` | Finished successfully |
| `failed` | Failed — needs retry |
| `skipped` | Conditional step not applicable |
| `deferred` | Waiting for upstream step to determine if condition is met |

### `step_order`

A top-level array listing steps in canonical order. This field exists so the Stop hook can determine step ordering without a hardcoded bash array. It **must** always be written by the orchestrator and kept in sync with the YAML step list.

## Active workflow marker

The active workflow marker tells the Stop hook which workflow (if any) is currently running in this session. Without the marker, the hook allows Claude to stop freely.

**Location**: `.agent_workspace/.active-workflow`

### When to write the marker

Write the marker file using the Write tool at the same time as creating or updating the progress file to `"in_progress"` — after parsing arguments, before step 1. If resuming an existing workflow, overwrite any existing marker.

### Schema

```json
{
  "ticket": "<TICKET>",
  "workflow_type": "<workflow.name from YAML>",
  "progress_file": ".agent_workspace/<ticket-lower>/workflow/<workflow-type>_<ticket-lower>.json"
}
```

The `progress_file` path must be relative to the project root (matching the path the hook uses to locate the file).

### When to delete the marker

Delete `.agent_workspace/.active-workflow` when:

1. The workflow completes — immediately after setting the progress file's `status` to `"completed"` in the [Completion](#completion) section
2. The workflow fails terminally — after setting `status` to `"failed"` (e.g., planning step produces 0 modules and user chooses to stop)

Do **not** delete the marker between steps. The marker must persist for the entire duration of the workflow so the Stop hook can block premature stops.

### Overwriting on resume or new workflow

If the user starts a new workflow (different ticket or different workflow type) or resumes an existing one, overwrite the marker with the new workflow's information. There is only ever one active workflow at a time. The previous marker is implicitly superseded.

### Edge cases

- **No marker exists**: The Stop hook allows Claude to stop. This is the correct default for sessions that don't involve a workflow.
- **Marker points to a missing progress file**: The Stop hook cleans up the stale marker and allows stop.
- **Marker exists but workflow status is `"completed"` or `"failed"`**: The Stop hook cleans up the marker and allows stop.

## Check for existing work

Before starting, check for a progress file at `.agent_workspace/<ticket>/workflow/<workflow-type>_<ticket>.json`.

**If a progress file exists:**

1. Read it and identify which steps have status `"completed"` or `"skipped"`
2. For each `"completed"` step, verify its output folder still exists on disk. If it has been deleted, reset that step to `"pending"` and reset all downstream dependent steps to `"pending"` as well
3. If `options.source` is `null`, rehydrate it from on-disk source state **before** choosing the resume step:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/resolve_source.py \
  --base-path <base_path> \
  --progress-file <progress_file> \
  [--scan-requirements --skip-deferred-on-no-source]
```

Use the bracketed flags only if the `requirements` step has already completed; this re-runs post-requirements source discovery against the persisted workflow artifacts (`discovered_repos.json`, `requirements.md`). Then re-read the progress file from disk before continuing. This ensures cached `source.yaml` and any already-cloned repo are reflected in `options.source` on resume.

4. Resume from the first step with status `"pending"` or `"failed"`
5. Before running the resume step, validate its input dependencies are satisfied
6. Tell the user: "Found existing work for `<ticket>`. Resuming from `<step>`."
7. If the user provided additional flags on resume (e.g., `--create-jira`), update the progress file options accordingly

**If no progress file exists**, start from step 1, create a new progress file, and write the active workflow marker.

In both cases (new or resume), write the [active workflow marker](#active-workflow-marker) with the current ticket and workflow type. This ensures the Stop hook tracks only this workflow.

## Running workflow steps

Run steps in the order defined by the YAML. For each step:

- If the step's status is `deferred`, skip it for now — it will be re-evaluated after post-requirements source resolution
- If the step's status is `skipped`, skip it permanently

### Before the step

1. Validate input dependencies — for each step name in the step's YAML `inputs`, check the upstream step's status:
   - `"completed"` — must also have a non-null `output` folder in the progress file
   - `"skipped"` (upstream step has a `when` condition) — treated as satisfied even though `output` is `null`. The downstream step is responsible for checking whether the optional input data actually exists
   - `"failed"` — **fail the current step immediately** with a clear error (e.g., "Step 'writing' requires 'planning', but planning has status 'failed'")
2. Update the step's status to `"in_progress"` in the progress file

### Construct arguments

Build the args string for the step skill. The orchestrator maps its user-facing flags to the internal flags that step skills expect: `--source-code-repo` → `--repo`, `--docs-repo-path` → `--repo-path`.

1. **Always**: `<ticket> --base-path <base_path>` — the ticket ID and the **absolute** base output path
2. **If source repo is resolved**: `--repo <repo_path>` — passed to steps that can use it
3. **From orchestrator context**: Step-specific args from parsed CLI flags:
   - `requirements`: `[--pr <url>]... [--repo <repo_path>]`
   - `code-analysis`: `--repo <repo_path>`
   - `pr-analysis`: `--repo <repo_path> [--pr <url>...]`
   - `writing`: `--format <adoc|mkdocs> [--draft] [--repo <repo_path>]... [--repo-path <path>]` — pass `--repo` for the primary source repo AND for each entry in `options.additional_sources` (in order)
   - `technical-review`: `[--repo <repo_path>]...` — pass `--repo` for the primary source repo AND for each entry in `options.additional_sources` (in order)
   - `style-review`: `--format <adoc|mkdocs>`
   - `create-merge-request`: `[--draft] [--repo-path <path>]`

Step skills derive their own output folder and input folders from `--base-path` and step name conventions. No per-input flag wiring needed.

### Invoke the step skill

```
Skill: <step.skill>, args: "<constructed args>"
```

### After the step

1. Verify the output folder exists (for steps that produce files). If the expected output folder is missing, mark the step as `failed` in the progress file and **STOP**
2. Read the step's `step-result.json` sidecar if it exists in the output folder. If present, store the step-specific fields in `steps.<step-name>.result` in the progress file (see [Step-specific post-processing](#step-specific-post-processing) for which fields to record per step). Log a warning if the sidecar is missing (the step still counts as completed — sidecars are expected but not required for backward compatibility)
3. Update the step's status to `"completed"` with the output folder path in the progress file
4. Update the progress file's `updated_at` timestamp
5. Do NOT read step output files (requirements.md, plan.md, review.md) into the orchestrator context. Read only step-result.json sidecars. Step skills and their dispatched agents read output files — the orchestrator reads metadata only
6. Run [step-specific post-processing](#step-specific-post-processing) for the just-completed step
7. **Post-step context refresh** — Re-read the progress file from disk before starting the next step. This ensures that if automatic context compaction has occurred (compressing earlier conversation turns), the orchestrator re-establishes workflow state from the authoritative source. The progress file, active workflow marker, and step output folders are the complete state — nothing essential is held only in conversation context

### Step-specific post-processing

After each step completes, apply the rules below. When rules reference sidecar fields, read from `steps.<step-name>.result` in the progress file (already recorded in the after-step logic above). If the sidecar was missing, fall back to parsing the step's primary output file where noted.

**requirements**
- Log the `title` field: `"Requirements extracted: <title>"`
- Record `requirement_count` from the sidecar. Log: `"Requirements: <requirement_count> requirements discovered"`
- Evaluate `when: has_many_requirements` for any deferred steps (see [`when: has_many_requirements` condition](#when-has_many_requirements-condition))
- If `options.source` is `null` → run [Post-requirements source resolution](#post-requirements-source-resolution). This may change `deferred` steps to `pending` or `skipped`

**code-analysis**
- Log: `"Code analysis completed: N modules, N relationships, languages: <languages_detected>"`
- Record `repo_path` from the sidecar for downstream steps
- **Multi-repo code analysis**: If `options.additional_sources` is non-empty, run code-analysis for each additional repo sequentially. For each additional source entry:
  1. Derive the repo name: `basename(additional_source.repo_path)`
  2. Invoke the code-analysis step skill with a custom output dir:
     ```
     Skill: docs-workflow-code-analysis, args: "--repo <additional_source.repo_path> --ticket <ticket> --output-dir <base_path>/code-analysis-<repo-name>"
     ```
  3. Log: `"Additional code analysis completed for <repo-name>"`
  These additional analyses are sub-tasks of the primary code-analysis step — do not create separate progress file entries. If an additional repo analysis fails, log a warning and continue (do not fail the entire code-analysis step)

**pr-analysis**
- Log: `"PR analysis completed: PR #<pr_number> — N modules affected"`

**planning**
- Log: `"Planning completed: N modules"`
- If `module_count` is 0, **warn**: `"Planning produced 0 modules — the plan may be empty. Review plan.md before continuing."` Ask the user whether to proceed or stop. If the user chooses to stop: mark the planning step as `failed` in the progress file, set the workflow status to `"failed"`, delete the active workflow marker (`.agent_workspace/.active-workflow`), log `"Planning stopped by user after 0 modules — workflow cancelled."`, and halt without running subsequent steps

**writing**
- If `result.files` is empty or missing, **warn**: `"Writing step produced no files."` Mark the `create-merge-request` step as `skipped` with `skip_reason: "no_files"` and record `result.commit_sha: null`, `result.branch: null`, `result.pushed: false`, `result.url: null`, `result.action: "skipped"`, `result.platform: "unknown"`, `result.skipped: true`. Log: `"Skipping create-merge-request: no files to commit."`

**technical-review**
- After the [Technical review iteration](#technical-review-iteration) loop completes, re-evaluate `when: has_many_requirements` Phase 2 for the quality-gate step (see [`when: has_many_requirements` condition](#when-has_many_requirements-condition))

**create-merge-request**
- Record `result.url`, `result.pushed`, and `result.branch`. If `result.pushed` is false and `result.skipped` is false, log warning: `"create-merge-request: branch was not pushed."` If `result.url` is present, record it for the [Completion](#completion) summary

**create-jira**
- Record `result.jira_url` and `result.jira_key` for the [Completion](#completion) summary

**quality-gate**
- Log: `"Quality gate: doc_quality=<N>/5, intent_alignment=<N>/5, passed=<true|false>, gaps=<N>"`
- If `passed` is false → enter [Quality gate iteration](#quality-gate-iteration) loop

## Post-requirements source resolution

This section triggers **only** when the `requirements` step completes AND `options.source` is still `null` (i.e., no source was resolved pre-flight).

### 1. Run resolve_source.py with `--progress-file`

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/resolve_source.py \
  --base-path <base_path> \
  --progress-file <progress_file> \
  --scan-requirements \
  --skip-deferred-on-no-source
```

The script reads `discovered_repos.json` (produced by the requirements step from the JIRA graph), then scans `requirements.md` for GitHub/GitLab PR/MR URLs as a fallback. When a repo is found, it clones/verifies it, writes `source.yaml`, records `options.source` in the progress file, and promotes deferred steps to `pending`.

### 2. Handle the result

| Exit code | `status` | Action |
|---|---|---|
| 0 | `resolved` | The script has already recorded `options.source` in the progress file (primary repo + any `additional_repos`) and updated all `deferred` steps to `pending`. Log all resolved repos |
| 1 | `error` / `clone_failed` | Log a warning: "Could not clone `<repo_url>`. Code-evidence will be skipped. To retry, run with `--source-code-repo <url-or-local-path>`." Leave the progress file unchanged |
| 2 | `no_source` | Skip code-analysis (see below) |

### 3. No source found

When the script returns `no_source`, skip code-analysis without prompting.

With `--skip-deferred-on-no-source`, the script has already updated all `deferred` steps to `skipped`. Continue without code-analysis and log: "No source code repository or PR discovered. Skipping code-analysis. To enable it, re-run with `--source-code-repo <url-or-path>` or `--pr <url>`."

## Technical review iteration

The technical review step runs in a loop until confidence is acceptable or three iterations are exhausted:

1. Invoke `docs-workflow-tech-review` with the standard args
2. Read the review metadata. **Prefer the sidecar** (`<base_path>/technical-review/step-result.json`) when present — read `confidence` and `severity_counts` directly. **Fall back** to using `grep` to extract the `Overall technical confidence: (HIGH|MEDIUM|LOW)` and `Severity counts:` lines from `review.md` if no sidecar exists — do not read the full review.md into context
   - If neither the sidecar nor the confidence line is found, treat it as a step failure — mark the step `failed` and stop iteration
   - Also update `steps.technical-review.result` from the latest sidecar (confidence, severity_counts, iteration). Values may change between iterations as review.md content changes after fixes
3. If `HIGH` → mark completed, proceed to next step
4. If `MEDIUM`, check the severity counts (from sidecar `severity_counts` object or from the `Severity counts:` line):
   - If both `critical=0` AND `significant=0` → treat as acceptable. Log: "MEDIUM confidence with zero critical/significant issues — proceeding (remaining items require SME review)." Mark completed and proceed to next step.
   - If severity counts are unavailable, or either `critical > 0` or `significant > 0` → continue to step 5 for iteration
5. If `MEDIUM` (with fixable issues) or `LOW` and fewer than 3 iterations completed → run the fix skill:
   ```
   Skill: docs-workflow-writing, args: "<ticket> --base-path <base_path> [--repo <repo_path>]... --fix-from <base_path>/technical-review/review.md"
   ```
   Pass `--repo` for the primary source repo and each additional source (same as the writing step's initial invocation) so the fix agent can verify review findings against source code.
   Then re-run the reviewer (go to step 1)
6. After 3 iterations without reaching `HIGH`:
   - `MEDIUM` is acceptable — proceed with a warning that manual review is recommended
   - `LOW` after max iterations — ask the user whether to proceed or stop

## Quality gate iteration

The quality gate step runs in a loop until scores are acceptable or two iterations are exhausted:

1. Invoke `docs-workflow-quality-gate` with the standard args
2. Read `quality-gate/step-result.json`. Extract `doc_quality`, `intent_alignment`, and `passed`
   - Also update `steps.quality-gate.result` from the sidecar
3. If `intent_alignment >= 4` → mark completed, proceed to create-merge-request. If `doc_quality < 4`, log a warning: "doc_quality=N/5 is below threshold — manual review recommended." (doc_quality is informational only)
4. If `intent_alignment < 4` and fewer than 2 iterations completed → dispatch the writer in fix mode using the feedback brief produced by the quality-gate skill:
   ```
   Skill: docs-workflow-writing, args: "<ticket> --base-path <base_path> [--repo <repo_path>]... --fix-from <BASE_PATH>/quality-gate/feedback-brief.md"
   ```
   The quality-gate skill writes `feedback-brief.md` when `passed = false` — the orchestrator does not build this file. Pass `--repo` for the primary source repo and each additional source (same as the writing step's initial invocation) so the fix agent can verify against source code.
   Then re-run the quality gate (go to step 1).
5. After 2 iterations with `intent_alignment` still below 4:
   - If `intent_alignment >= 3` → accept with warning: "Quality gate marginal (intent_alignment=N). Manual review recommended."
   - If `intent_alignment < 3` → ask the user whether to proceed or stop

### `when: has_many_requirements` condition

The `quality-gate` step uses `when: has_many_requirements`. This condition is evaluated in two phases:

**Phase 1 — After requirements step completes (initial evaluation):**

- Read `requirement_count` from `steps.requirements.result` in the progress file
- If `requirement_count < 6` → condition is not met, mark the step as `skipped` with `skip_reason: "few_requirements"`. Log: `"Skipping quality-gate: <requirement_count> requirements (threshold: 6)"`
- If `requirement_count >= 6` → mark as `deferred`. The gate is provisionally needed but the tech-review result may change that (see Phase 2)
- If `requirement_count` is missing from the sidecar (backward compatibility) → treat as `deferred`. Log a warning: `"requirement_count missing from requirements sidecar — defaulting to quality-gate enabled"`

**Phase 2 — After technical-review step completes (re-evaluation):**

- If the step was already `skipped` in Phase 1, no change
- Read `confidence` from `steps.technical-review.result`
- If `confidence` is `HIGH` → the tech review validated all claims against source code, indicating strong requirements comprehension by the writer. Intent drift is unlikely. Mark quality-gate as `skipped` with `skip_reason: "high_confidence_review"`. Log: `"Skipping quality-gate: technical review reached HIGH confidence"`
- If `confidence` is `MEDIUM` or `LOW` → condition is met, mark as `pending`. The tech review could not fully validate the writing, so an independent intent-alignment check adds value
- If technical-review was `skipped` → condition is met, mark as `pending` (no confidence signal available)

**Rationale:** The quality gate checks intent alignment — "did we write what was asked for?" — which is orthogonal to the tech review's accuracy check. However, both accuracy and completeness tend to follow from the same upstream quality: clear requirements, good code-analysis, and strong writer comprehension. When the tech review reaches HIGH, it signals that the writer had a solid grasp of the material, making coverage gaps less likely. Combining the requirement-count threshold (complexity filter) with the confidence signal (quality filter) skips the gate only when both indicators suggest it is unlikely to find gaps.

The threshold and confidence logic can be overridden by using a custom workflow YAML that either always includes or always excludes quality-gate.

## Commit confirmation gate

Before running the `create-merge-request` step, **ask the user to confirm** before committing. Show:
  - The target branch name — derived from the ticket ID (lowercase). If the repo is already on a feature branch, show the current branch name (from `git branch --show-current`)
  - The repository being committed to (current directory or `--docs-repo-path`)
  - The number of files — from `steps.writing.result.files` array length in the progress file. If unavailable, count files in the writing output folder

If the user declines, mark the `create-merge-request` step as `skipped` (with `skip_reason: "user_declined"`). Record `result.commit_sha: null`, `result.branch: null`, `result.pushed: false`, `result.url: null`, `result.action: "skipped"`, `result.platform: "unknown"`, `result.skipped: true`.

## Completion

After all steps complete (or are skipped):

1. Update the progress file: `status → "completed"`
2. Delete the active workflow marker: remove `.agent_workspace/.active-workflow`
3. Display a summary:
   - List all output folders with paths
   - Note any warnings (tech review didn't reach `HIGH`, planning had 0 modules, code-analysis had 0 modules, etc.)
   - Show MR/PR URL from `steps.create-merge-request.result.url` if present
   - Show JIRA URL from `steps.create-jira.result.jira_url` (with key `result.jira_key`) if present
   - Show module count from `steps.planning.result.module_count` and file count from `steps.writing.result.files` length

## Resume behavior

### Same session

The progress file is already in context. Skip completed steps and continue from the first `pending` or `failed` step. The Stop hook ensures Claude doesn't stop prematurely.

### New session

User says: `"Resume docs workflow for PROJ-123"`

1. Invoke this skill with the ticket
2. Check for an existing progress file
3. Read it, skip completed steps, resume from first `pending` or `failed` step
4. Before running the resume step, **validate its input dependencies** — every required upstream step must have `status: "completed"` and a non-null `output` folder. If a dependency is `failed` or `pending`, re-run that dependency first
5. For each upstream dependency, verify the output folder still exists on disk. If an output folder was deleted, mark that step as `pending` and re-run it
6. The user can provide additional flags on resume (e.g., add `--create-jira`) — update the progress file options accordingly

### After failure

Same as new session. The progress file shows which steps completed and which failed. Walk back to the earliest incomplete dependency and resume from there.

### Context management

The orchestrator relies on two complementary mechanisms for context management:

1. **Automatic compaction** — Claude Code automatically compresses prior conversation turns when approaching context limits. Because the orchestrator invokes step skills via the Skill tool, there are natural tool-call boundaries between steps where compaction can occur. No manual intervention is needed.

2. **Progress file as authoritative state** — After compaction, prior conversation turns (argument parsing, early step logs, sidecar data) may no longer be in context. The orchestrator handles this by re-reading the progress file from disk after each step completes (see "Post-step context refresh" in the after-step checklist). The progress file records everything the orchestrator needs to continue: ticket, options (format, draft, source, PR URLs), step_order, per-step status, output paths, and sidecar result data. No workflow state is held exclusively in conversation memory.

This design means the orchestrator runs the entire pipeline in a single session without forced stops. The progress file remains the safety net for genuine session interruptions (user closes the terminal, network failure, crash).

## Follow-on work

### Requirements-analyst agent: repo-aware analysis

When `--repo` is passed to the requirements step, the `requirements-analyst` agent uses the repo to enrich its analysis: verifying features exist in code, identifying existing documentation, extracting project metadata, and noting code references for downstream steps. See `agents/requirements-analyst.md` step 2 (Source repo enrichment).


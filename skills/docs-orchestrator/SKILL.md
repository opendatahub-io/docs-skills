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

- `$1` — JIRA ticket ID (required). If missing, STOP and ask the user.

All other flags are optional. See [argument reference](references/argument-reference.md) for full descriptions, precedence rules, and usage examples.

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

The script outputs JSON with `status`, `repo_path`, `repo_url`, `ref`, and `scope`.

### Handle the result

| Exit code | `status` | Action |
|---|---|---|
| 0 | `resolved` | Set `has_source_repo = true`. Record `options.source` in the progress file from the JSON fields (`repo_path`, `repo_url`, `ref`, `scope`) |
| 1 | `error` | **STOP** with the error `message` from the JSON |
| 2 | `no_source` | Mark steps with `when: has_source_repo` as `deferred`. Source resolution will be retried after requirements (see [Post-requirements source resolution](#post-requirements-source-resolution)) |

If `discovered_repos` is present in the result (multiple repos found), log all resolved repos. If `additional_repos` is present, record them in the progress file alongside the primary source. If `warnings` is present, log each warning.

### Per-ticket source config schema

Writers can pre-configure the source repo and scope in `<base-path>/source.yaml`. See [output and state reference](references/output-and-state.md#per-ticket-source-config-schema) for the full schema.

## Load the step list

### 1. Determine the YAML file

- If `--workflow <name>` was specified → `.agent_workspace/docs-<name>.yaml`
- If that project-level file doesn't exist → fall back to `skills/docs-orchestrator/defaults/docs-<name>.yaml`
- Otherwise → `.agent_workspace/docs-workflow.yaml`
- If that project-level file doesn't exist → fall back to `skills/docs-orchestrator/defaults/docs-workflow.yaml`

### 2. Read the YAML

Read the YAML file and extract the ordered step list. Each step has: `name`, `skill`, `description`, optional `when`, and optional `inputs`.

### 3. Evaluate `when` conditions

| Condition | Behavior |
|---|---|
| `create_merge_request` | Run only if `--create-merge-request` was passed |
| `has_pr` | Run only if a PR/MR URL is available (from `--pr`, JIRA discovery, or `options.pr_urls`) |
| `has_source_repo` | If `--no-source-repo` → `skipped`. If source resolved pre-flight → `pending`. Otherwise → `deferred` until post-requirements resolution |
| `has_many_requirements` | Deferred until requirements step completes. See [`when: has_many_requirements` condition](#when-has_many_requirements-condition) |
| _(none)_ | Always runs |

Steps that don't meet their condition and can't be deferred are marked `skipped`.

### 4. Validate the step list

All of the following must be true. If any check fails, **STOP** with a clear error:

- All step names are unique
- All `skill` references resolve to a known skill (bare names like `docs-workflow-writing` are preferred; fully qualified `plugin:skill` format is also accepted)
- Input dependencies are satisfied — for each step with `inputs`, every referenced step name must be present in the step list (unless it has a `when` condition that would skip it)

### Input dependencies

Steps declare `inputs` as a list of upstream step names. Validate at load time that all referenced names exist. If an upstream step was `skipped` (via `when`), the dependency is satisfied — the downstream step checks for optional input data itself. Only `failed` upstream steps block execution. Missing references fail at load time.

## Output conventions

Every step writes to `.agent_workspace/<ticket>/<step-name>/`. The ticket ID is lowercase for directory names. Resolve `BASE_PATH` to an absolute path via `git rev-parse --show-toplevel`.

See [output and state reference](references/output-and-state.md#output-conventions) for the folder structure tree, base path resolution formula, and [step-result schema](schema/step-result-schema.md) for sidecar format.

## Progress file

Claude writes the progress file directly using the Write tool. Create it after parsing arguments, before step 1. Update it after each step.

**Location**: `.agent_workspace/<ticket>/workflow/<workflow-type>_<ticket>.json`

See [output and state reference](references/output-and-state.md#progress-file) for the full JSON schema, status values (`pending`, `in_progress`, `completed`, `failed`, `skipped`, `deferred`), `step_order` array, and the [active workflow marker](references/output-and-state.md#active-workflow-marker) schema and lifecycle (when to write, delete, and overwrite).

## Check for existing work

Check for a progress file at `.agent_workspace/<ticket>/workflow/<workflow-type>_<ticket>.json`.

**If found**: Read it. Verify each `completed` step's output folder exists on disk — if missing, reset it and all downstream steps to `pending` and clear `steps.<step>.result` for the rewound step and all its downstream dependents (prevents stale sidecar data from being reused). If `options.source` is null, rehydrate via `resolve_source.py --base-path <base_path> --progress-file <progress_file>` (add `--scan-requirements --skip-deferred-on-no-source` if requirements already completed). Resume from the first `pending` or `failed` step after validating input dependencies.

**If not found**: Create a new progress file and start from step 1.

In both cases, write the active workflow marker.

## Running workflow steps

Run steps in the order defined by the YAML. For each step:

- If the step's status is `deferred`, skip it for now — it will be re-evaluated after post-requirements source resolution
- If the step's status is `skipped`, skip it permanently

### Before the step

Validate input dependencies: `completed` upstream needs a non-null `output` folder; `skipped` upstream is satisfied (downstream checks for data); `failed` upstream blocks immediately. Set step status to `in_progress`.

### Construct arguments and invoke

See [step post-processing](references/step-post-processing.md#construct-arguments) for the full flag mapping per step. Always pass `<ticket> --base-path <base_path>`. Add `--repo <repo_path>` if source is resolved. The orchestrator maps `--source-code-repo` → `--repo`, `--docs-repo-path` → `--repo-path`.

### Invoke the step skill

```
Skill: <step.skill>, args: "<constructed args>"
```

### After the step

1. Verify output folder exists — if missing, mark `failed` and **STOP**
2. Read `step-result.json` sidecar if present; store fields in `steps.<step-name>.result`. If missing, log warning and store default result: `{"module_count": 0, "files": [], "passed": true}` — downstream post-processing must handle these defaults gracefully
3. Set status to `completed` with output path. Get the real wall-clock timestamp by running `date -u +%Y-%m-%dT%H:%M:%SZ` and use it for `updated_at` and for the step's `completed_at` in the sidecar. **Do not estimate or round timestamps** — synthetic timestamps break duration calculations and bottleneck detection in pipeline diagnostics
4. Do NOT read step output files into orchestrator context — read only sidecars
5. Run [step-specific post-processing](#step-specific-post-processing)
6. Re-read the progress file from disk before the next step (post-step context refresh)

### Logging workarounds

When a step's build script fails but the orchestrator can work around the failure (e.g., by computing arguments manually, bypassing a broken script, or applying a manual fix), append an entry to the progress file's `workarounds` array **before proceeding with the step**:

```json
{
  "step": "<step-name>",
  "issue": "<what failed — e.g., build_writing_args.sh exit 1 due to set -e bug in find_code_analysis_dir>",
  "action": "<what the orchestrator did instead — e.g., computed JSON args manually and dispatched agent directly>",
  "timestamp": "<ISO 8601>"
}
```

This makes workarounds visible to pipeline-diagnostics, which surfaces them in the diagnostic report. Without this, script failures that the orchestrator silently works around appear as clean runs — masking bugs in the automation layer.

### Step-specific post-processing

After each step completes, apply the per-step rules from [step post-processing](references/step-post-processing.md). When rules reference sidecar fields, read from `steps.<step-name>.result` in the progress file. Key triggers: requirements triggers post-requirements source resolution if `options.source` is null; planning stops on 0 modules; writing skips create-merge-request if no files; quality-gate enters the iteration loop if `passed` is false.

## Post-requirements source resolution

Triggers only when requirements completes AND `options.source` is still null. Run `resolve_source.py --base-path <base_path> --progress-file <progress_file> --scan-requirements --skip-deferred-on-no-source`. The script reads `discovered_repos.json` and scans `requirements.md` for PR/MR URLs.

| Exit code | Action |
|---|---|
| 0 (`resolved`) | Script updated progress file and promoted deferred steps to `pending`. Log resolved repos |
| 1 (`error`) | Log warning. Leave progress unchanged. User can retry with `--source-code-repo` |
| 2 (`no_source`) | Script already set deferred steps to `skipped`. Log and continue without code-analysis |

## Technical review iteration

Loop up to 2 iterations until confidence is acceptable (one review, one fix-and-confirm):

1. Invoke `docs-workflow-tech-review`. Read confidence from the sidecar (`step-result.json`), falling back to grep on `review.md` for `Overall technical confidence:`. Update `steps.technical-review.result`
2. `HIGH` → done. `MEDIUM` with `critical=0` AND `significant=0` → acceptable (log, proceed). Otherwise continue
3. If `MEDIUM` (with fixable issues) or `LOW` → fix via `docs-workflow-writing --fix-from <base_path>/technical-review/review.md` (pass all `--repo` flags), then re-run reviewer. The re-run revalidates only the claims the fix changed (see the tech-review step's incremental claim validation), so the reviewer gets fresh evidence cheaply
4. After 2 iterations: `MEDIUM` → proceed with warning. `LOW` → ask user. A fix that has not reached acceptable confidence after one attempt is escalated here rather than retried again — a second failed automated fix is a signal for SME/human review, not another rewrite

## Quality gate iteration

Loop up to 2 iterations until `intent_alignment >= 4`:

1. Invoke `docs-workflow-quality-gate`. Read `quality-gate/step-result.json` — stop if missing or incomplete (needs `doc_quality`, `intent_alignment`, `passed`)
2. `intent_alignment >= 4` → done (warn if `doc_quality < 4`). Otherwise continue
3. Fix via `docs-workflow-writing --fix-from <BASE_PATH>/quality-gate/feedback-brief-<iteration>.md` (verify file exists first; pass all `--repo` flags), then re-run quality gate
4. After 2 iterations: `intent_alignment >= 3` → accept with warning. `< 3` → ask user

### `when: has_many_requirements` condition

The `quality-gate` step uses `when: has_many_requirements`. Evaluated in two phases: Phase 1 after requirements (threshold: `requirement_count >= 6`), Phase 2 after technical-review (skip if `confidence == HIGH`). See [quality gate conditions](references/quality-gate-conditions.md) for the full evaluation logic and rationale.

## Commit confirmation gate

Before `create-merge-request`, ask user to confirm. Show: branch name (from ticket ID or current branch), target repo, file count (from `steps.writing.result.files`). If declined, mark step `skipped` with `skip_reason: "user_declined"` and null result fields.

## Completion

Set progress `status → "completed"`, delete `.agent_workspace/.active-workflow`. Display summary: output folder paths, warnings, MR/PR URL, JIRA URL, module/file counts from step results.

For SME review comments on an existing MR/PR, use the standalone `action-comments` skill after the workflow completes. It can also be added to a custom workflow YAML as a step.

## Resume behavior

On resume (same or new session), read the progress file and skip completed steps. Resume from the first `pending` or `failed` step. Before running it, validate input dependencies — every upstream step must have `status: "completed"` and its output folder on disk. For each upstream dependency, verify the output folder still exists on disk. If an output folder was deleted, mark that step as `pending` and re-run it. Additional flags provided on resume (e.g., `--create-jira`) update the progress file options.

**Re-write the active workflow marker on every resume.** The marker may be absent after a session restart or context compaction — stop hooks and session teardown can delete it. Always re-write it after reading the progress file, before running any steps.

### Context management

The progress file is the authoritative state. After automatic compaction compresses earlier turns, re-read the progress file from disk (post-step context refresh). No workflow state is held only in conversation memory. Re-write the active workflow marker after re-reading the progress file — compaction may have triggered a session boundary that cleaned up the marker.


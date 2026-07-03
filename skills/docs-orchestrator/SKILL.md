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

Run `load_workflow.py` — it resolves the workflow YAML (project override → plugin default), evaluates the deterministic `when` conditions against the run options, and validates the step list. Do NOT read the YAML or evaluate conditions by hand.

First write the run options gathered from the CLI flags to a JSON file (reused by `progress.py init`), then run the loader:

```bash
uv run --script ${CLAUDE_SKILL_DIR}/scripts/load_workflow.py \
  --workflow <name> \
  --plugin-root ${CLAUDE_PLUGIN_ROOT} \
  --options <base_path>/workflow/options.json \
  --base-path <base_path> > <base_path>/workflow/steps.json
```

`--workflow` defaults to `workflow` (the bundled `docs-workflow.yaml`). The script **STOPs with a non-zero exit and a stderr error** if a skill reference is unknown, a step name is duplicated, or an `input` names a missing step — surface that error to the user and do not proceed with an invalid step list.

The emitted JSON has `workflow`, `yaml_path`, and an ordered `steps` array; each step carries `name`, `skill`, `description`, `when`, `inputs`, and an initial `status` of `pending` (will run), `skipped` (permanent), or `deferred` (`has_source_repo` unresolved or [`has_many_requirements`](#when-has_many_requirements-condition); re-evaluated after requirements). At run time a `skipped` upstream still satisfies a dependency; only a `failed` upstream blocks execution.

## Output conventions

Every step writes to `.agent_workspace/<ticket>/<step-name>/`. The ticket ID is lowercase for directory names. Resolve `BASE_PATH` to an absolute path via `git rev-parse --show-toplevel`.

See [output and state reference](references/output-and-state.md#output-conventions) for the folder structure tree, base path resolution formula, and [step-result schema](schema/step-result-schema.md) for sidecar format.

## Progress file

The progress file is the authoritative run state. Create it with `progress.py init` from the validated step list — do NOT hand-author the JSON:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/progress.py init \
  --base-path <base_path> \
  --ticket <TICKET> \
  --workflow <name> \
  --steps <base_path>/workflow/steps.json \
  --options <base_path>/workflow/options.json
```

This writes `<base_path>/workflow/<workflow>_<ticket-lower>.json` with each step's initial status from the step list, `status: "in_progress"`, and real wall-clock timestamps. It refuses to overwrite an existing progress file unless `--force`. Update the file after each step using the Write tool (see [After the step](#after-the-step)).

See [output and state reference](references/output-and-state.md#progress-file) for the full JSON schema, status values (`pending`, `in_progress`, `completed`, `failed`, `skipped`, `deferred`), `step_order` array, and the [active workflow marker](references/output-and-state.md#active-workflow-marker) schema and lifecycle (when to write, delete, and overwrite).

## Check for existing work

Check for a progress file at `.agent_workspace/<ticket>/workflow/<workflow-type>_<ticket>.json`.

**If found**: Read it, then run `progress.py rewind` to reconcile it with disk — it resets any `completed` step whose output folder is missing (plus every step ordered after it) back to `pending`, clearing stale results. Do NOT do this reset by hand.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/progress.py rewind --progress-file <progress_file>
```

The script prints `{"rewound_from": ..., "reset_steps": [...]}` and rewrites the file. If `options.source` is null, rehydrate via `resolve_source.py --base-path <base_path> --progress-file <progress_file>` (add `--scan-requirements --skip-deferred-on-no-source` if requirements already completed). Resume from the first `pending` or `failed` step after validating input dependencies.

**If not found**: Create a new progress file with `progress.py init` (see [Progress file](#progress-file)) and start from step 1.

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

When a step skill instructs you to dispatch an Agent, pass **`run_in_background: false`** for the step's primary agent (the one whose output file must exist before post-step verification). This runs the agent synchronously — the tool result contains the agent's final text, and the output file is guaranteed to exist when control returns. Without this, the agent runs in the background and the orchestrator may check for the output file before the agent finishes writing it, causing false "file not written" failures and unnecessary re-dispatches. Fan-out agents within a step (e.g., parallel claim validators, parallel requirement classifiers) should remain background — only the single primary agent that the step's "Verify output" gate checks needs `run_in_background: false`.

### After the step

1. Verify output folder exists — if missing, mark `failed` and **STOP**
2. Read `step-result.json` sidecar if present; store fields in `steps.<step-name>.result`. If missing, log warning and store default result: `{"module_count": 0, "files": [], "passed": true}` — downstream post-processing must handle these defaults gracefully
3. Set status to `completed` with output path. Use two different timestamp sources:
   - **`steps.<name>.result`**: copy the `completed_at` value verbatim from the step's `step-result.json` sidecar. This is the step's own completion time and must not be overwritten with a later timestamp
   - **`updated_at`** (top-level progress field): get the real wall-clock time by running `date -u +%Y-%m-%dT%H:%M:%SZ`. This reflects when the orchestrator recorded the completion, which is always equal to or later than the sidecar timestamp
   
   **Do not estimate or round timestamps** — synthetic timestamps break duration calculations and bottleneck detection in pipeline diagnostics. **Do not use `date -u` for the result's `completed_at`** — the gap between step completion and orchestrator bookkeeping inflates step durations in diagnostics
4. Do NOT read step output files into orchestrator context — read only sidecars
5. Run [step-specific post-processing](#step-specific-post-processing)
6. Re-read the progress file from disk before the next step (post-step context refresh)

**Never produce stub results.** If you cannot invoke a step's skill (e.g., due to context compaction removing the skill instructions), you MUST either (a) dispatch the step via an Agent subagent in a fresh context or (b) mark the step as `failed` with an error explaining why. Do NOT write a placeholder `step-result.json` or mark the step `completed` with a generic note like "no issues found" — this masks real failures from pipeline diagnostics and the user

### Logging workarounds

When the orchestrator works around a broken or mismatched part of the automation to make a step succeed, log it **before proceeding with the step** by running the script — never hand-edit the `workarounds` array in the progress JSON:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/progress.py log-workaround \
  --progress-file <progress_file> \
  --step "<step-name>" \
  --issue "<what failed — e.g., build_writing_args.sh exit 1 due to set -e bug in find_code_analysis_dir>" \
  --action "<what you did instead — e.g., computed JSON args manually and dispatched the agent directly>"
```

The script appends the entry (with an ISO 8601 timestamp), refreshes `updated_at`, and creates the `workarounds` array if absent; re-read the progress file afterward.

Not limited to build-script failures — log any manual substitute for automation that should have worked: bypassing a non-zero-exit script, computing args by hand after a helper failed, routing around a tool contract mismatch, or **quietly doing less than a skill prescribes** (e.g., batching where it says one-per-item). If you did something the scripted path was supposed to do for you, it is a workaround. This keeps workarounds visible to pipeline-diagnostics; without it, silently-worked-around failures look like clean runs and mask automation bugs.

**Re-dispatches are workarounds.** Any re-dispatch of a step's primary agent — whether due to empty output, incomplete output, or premature return — MUST be logged as a workaround **before** the re-dispatch. The `issue` field should describe what was missing (e.g., `"style-review agent returned empty review.md"`, `"scope-req-audit: 4/7 evidence files written after agent returned"`). The `action` field should describe the re-dispatch strategy (e.g., `"re-dispatched docs-reviewer agent with same prompt"`, `"re-dispatched 3 requirement-classifier agents for missing REQ-004, REQ-006, REQ-007"`). This includes partial re-dispatches where only a subset of fan-out agents are re-run.

### Step-specific post-processing

After each step completes, apply the per-step rules from [step post-processing](references/step-post-processing.md). When rules reference sidecar fields, read from `steps.<step-name>.result` in the progress file. Key triggers: requirements triggers post-requirements source resolution if `options.source` is null; planning stops on 0 modules; writing skips create-merge-request if no files; quality-gate enters the iteration loop if `passed` is false.

## Post-requirements source resolution

Triggers only when requirements completes AND `options.source` is still null. Run `resolve_source.py --base-path <base_path> --progress-file <progress_file> --scan-requirements --skip-deferred-on-no-source`. The script reads `discovered_repos.json` and scans `requirements.md` for PR/MR URLs.

| Exit code | Action |
|---|---|
| 0 (`resolved`) | Script updated progress file and promoted deferred steps to `pending`. Log resolved repos |
| 1 (`error`) | Log warning. Leave progress unchanged. User can retry with `--source-code-repo` |
| 2 (`no_source`) | Script already set deferred steps to `skipped`. Log and continue without code-analysis |

### Pre-resolved sources

To skip the source resolution round-trip (saves context and one script invocation), provide the source repo path upfront via either method:

- **CLI flag:** `--source-code-repo /path/to/cloned/repo`
- **source.yaml:** Create `<base-path>/../source.yaml` with:
  ```yaml
  repo_path: /path/to/cloned/repo
  ```

Both methods bypass `resolve_source.py` entirely. Use for repos you've already cloned or when the source is known in advance.

## Technical review iteration

Loop up to N iterations. The default `--max-iter` is 2. When the writing step produced more than 5 files (check `steps.writing.result.files` array length in the progress file), pass `--max-iter 3` to allow an additional fix-and-confirm pass for larger changes. The loop decision — the confidence/severity/iteration rules — is owned by `iteration_decision.py`; do NOT evaluate it by hand.

1. Invoke `docs-workflow-tech-review`. It writes `technical-review/step-result.json` (confidence, severity counts, auto-incremented iteration). Update `steps.technical-review.result` from the sidecar
2. Compute the dynamic `MAX_ITER` and **write it back** to the progress file so resume sessions see the actual value used:
   ```bash
   FILE_COUNT=$(python3 -c "import json; d=json.load(open('<progress_file>')); print(len(d.get('steps',{}).get('writing',{}).get('result',{}).get('files',[])))")
   MAX_ITER=$( [ "$FILE_COUNT" -gt 5 ] 2>/dev/null && echo 3 || echo 2 )
   ```
   Update `options.max_iter` in the progress file to `$MAX_ITER` if it differs from the current value. This ensures resume sessions and pipeline diagnostics see the effective iteration cap, not the CLI default.
3. Get the decision, then act on it:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/iteration_decision.py tech-review \
     --sidecar <base_path>/technical-review/step-result.json \
     --max-iter $MAX_ITER
   ```
   - `done` → proceed to the next step
   - `fix` → run the fix-and-confirm pass (step 4), then return to step 3
   - `proceed_with_warning` → emit the returned `warning`; since `list_findings` is true, append the title of each unresolved critical/significant finding from `technical-review/review.md`, and carry the counts into the Completion summary. Then proceed
   - `ask_user` → ask the user whether to proceed or stop for SME/human review
4. Fix-and-confirm pass (only when `decision == fix`):
   a. Fix via `docs-workflow-writing --fix-from <base_path>/technical-review/review.md` (pass all `--repo` flags)
   b. **Verify fixes landed.** After the fix agent returns, use **absolute paths** from `steps.writing.result.files` to verify modifications. Run `git diff --name-only` from the **docs repo root** (`git rev-parse --show-toplevel` of the docs repository, NOT of any cloned source repo). If no files changed, log a workaround entry and investigate — the fix agent may have written to the wrong directory
   c. **Delete the prior review report** before re-running the reviewer: `rm -f <base_path>/technical-review/review.md`. This prevents the iteration 2 reviewer from reading stale findings
   d. Re-run the reviewer. The re-run revalidates only the claims the fix changed (see the tech-review step's incremental claim validation), so the reviewer gets fresh evidence cheaply

## Quality gate iteration

Loop up to N iterations (same dynamic `--max-iter` as tech-review — 2 by default, 3 when writing produced >5 files). The loop decision — the `intent_alignment` thresholds — is owned by `iteration_decision.py`; do NOT evaluate it by hand.

1. Invoke `docs-workflow-quality-gate`. It writes `quality-gate/step-result.json` (`doc_quality`, `intent_alignment`, `passed`, `iteration`) and, when not passing, `feedback-brief-<iteration>.md` — stop if the sidecar is missing or incomplete
2. Reuse the `MAX_ITER` value computed and persisted in the tech-review loop (read `options.max_iter` from the progress file). If the quality gate runs without a prior tech-review loop (e.g., tech-review was skipped), compute it fresh using the same formula and write it back:
   ```bash
   MAX_ITER=$(python3 -c "import json; d=json.load(open('<progress_file>')); print(d.get('options',{}).get('max_iter', 2))")
   ```
3. Get the decision, then act on it:
   ```bash
   python3 ${CLAUDE_SKILL_DIR}/scripts/iteration_decision.py quality-gate \
     --sidecar <base_path>/quality-gate/step-result.json \
     --max-iter $MAX_ITER
   ```
   - `done` → proceed (if `secondary_warning` is set, emit it — `doc_quality < 4`, manual review recommended)
   - `fix` → fix via `docs-workflow-writing --fix-from <base_path>/quality-gate/feedback-brief-<iteration>.md` (verify the file exists first; pass all `--repo` flags), then re-run the quality gate (return to step 1)
   - `accept_with_warning` → emit a warning that `intent_alignment` is below target after max iterations, then proceed
   - `ask_user` → ask the user whether to proceed or stop

### `when: has_many_requirements` condition

The `quality-gate` step uses `when: has_many_requirements`. Evaluated in two phases: Phase 1 after requirements (threshold: `requirement_count >= 6`), Phase 2 after technical-review (skip if `confidence == HIGH`). See [quality gate conditions](references/quality-gate-conditions.md) for the full evaluation logic and rationale.

## Commit confirmation gate

Before `create-merge-request`, ask user to confirm. Show: branch name (from ticket ID or current branch), target repo, file count (from `steps.writing.result.files`). If declined, mark step `skipped` with `skip_reason: "user_declined"` and null result fields.

## Completion

Set progress `status → "completed"` and set `updated_at` to a **real wall-clock timestamp** from `date -u +%Y-%m-%dT%H:%M:%SZ` (same rule as every step — do not estimate or round, even on this final write). Delete `.agent_workspace/.active-workflow`. Display summary: output folder paths, warnings, MR/PR URL, JIRA URL, module/file counts from step results.

For SME review comments on an existing MR/PR, use the standalone `action-comments` skill after the workflow completes. It can also be added to a custom workflow YAML as a step.

## Resume behavior

On resume (same or new session), read the progress file and run `progress.py rewind` (see [Check for existing work](#check-for-existing-work)) to reset any completed step whose output folder was deleted, plus every step after it. Then resume from the first `pending` or `failed` step, validating input dependencies — every upstream step must be `completed` with its output folder on disk. Additional flags provided on resume (e.g., `--create-jira`) update the progress file options.

**Re-write the active workflow marker on every resume.** The marker may be absent after a session restart or context compaction — stop hooks and session teardown can delete it. Always re-write it after reading the progress file, before running any steps.

### Context management

The progress file is the authoritative state. After automatic compaction compresses earlier turns, re-read the progress file from disk (post-step context refresh). No workflow state is held only in conversation memory. Re-write the active workflow marker after re-reading the progress file — compaction may have triggered a session boundary that cleaned up the marker.


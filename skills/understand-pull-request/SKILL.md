---
name: understand-pull-request
description: Analyze a pull request or merge request. Fetches PR metadata via git-pr-reader, identifies affected modules, analyzes changes in context, and produces a PR-ANALYSIS.md document with a brief repo overview and detailed change analysis.
argument-hint: <pr-number-or-url> [--repo <path>]
allowed-tools: Read, Write, Bash, Glob, Grep, Agent
---

# Understand-Pull-Request — PR/MR Analysis

Fetches PR/MR metadata, identifies affected modules, analyzes changes in each module via fan-out agents, and produces a structured PR analysis document.

## Usage

```
/docs-skills:understand-pull-request 42
/docs-skills:understand-pull-request 42 --repo /path/to/repo
/docs-skills:understand-pull-request https://github.com/org/repo/pull/42
/docs-skills:understand-pull-request https://gitlab.com/org/repo/-/merge_requests/42
```

## Arguments

- `$1` — PR/MR reference (required). Accepts:
  - A bare number: `42`
  - A GitHub PR URL: `https://github.com/org/repo/pull/42`
  - A GitLab MR URL: `https://gitlab.com/org/repo/-/merge_requests/42`
- `--repo <path>` — Path to the local repository checkout (optional, defaults to current working directory)

## Pre-flight

### 1. Parse and validate arguments

Extract the PR reference from the first positional argument. Extract optional `--repo` value.

**If the argument is a URL:**

- GitHub URL (contains `/pull/`): extract the PR number from the URL path. Set `PLATFORM=github`. If `--repo` is not provided, try to find the repo locally or warn the user.
- GitLab URL (contains `/-/merge_requests/`): extract the MR number from the URL path. Set `PLATFORM=gitlab`.

**If the argument is a bare number:**

- Use it as `PR_NUMBER`.
- Platform is detected automatically from the git remote URL (see step 3).

### 2. Resolve repository path

**If `--repo` is provided:**

Validate the path exists and is a directory. Resolve to an absolute path. Set `REPO_PATH`.

**If `--repo` is NOT provided:**

Use the current working directory. Verify it is a git repository by checking for `.git/`.

If neither yields a valid git repository, STOP and report: `"No git repository found. Use --repo <path> to specify the repository."`.

Derive `REPO_NAME` from the basename of the repo path.

### 3. Detect platform and construct PR URL

**If `PLATFORM` and `PR_URL` were already set from a URL argument (step 1):** use them directly.

**Otherwise**, detect from the git remote and construct the URL:

```bash
REMOTE_URL=$(git -C "${REPO_PATH}" remote get-url origin 2>/dev/null || echo "")
```

- If `REMOTE_URL` contains `github.com`: set `PLATFORM=github`. Extract `<owner>/<repo>` from the remote URL (strip protocol, host, and `.git` suffix). Set `PR_URL="https://github.com/<owner>/<repo>/pull/${PR_NUMBER}"`.
- If `REMOTE_URL` contains `gitlab`: set `PLATFORM=gitlab`. Extract the host and project path from the remote URL. Set `PR_URL="https://<host>/<project_path>/-/merge_requests/${PR_NUMBER}"`.
- Otherwise: STOP and report: `"Cannot detect platform from git remote URL. Ensure the repository has a GitHub or GitLab origin remote."`.

### 4. Validate authentication

The git-pr-reader script requires API tokens. Verify that the relevant token is set:

- GitHub: `GITHUB_TOKEN` must be set in environment, `~/.env`, or `.env`
- GitLab: `GITLAB_TOKEN` must be set in environment, `~/.env`, or `.env`

The script loads `.env` files automatically. If neither token is available, warn: `"No API token found. Set GITHUB_TOKEN or GITLAB_TOKEN in ~/.env for authenticated access."`

### 5. Set paths

```bash
GIT_ROOT="$(cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" && pwd)"
BASE_PATH="${GIT_ROOT}/.agent_workspace/${REPO_NAME}"
PR_BASE="${BASE_PATH}/pr-${PR_NUMBER}"
mkdir -p "${PR_BASE}"
```

### 6. Check for existing progress (resume)

Look for an existing progress file:

```
${BASE_PATH}/workflow/understand-pr_${REPO_NAME}_${PR_NUMBER}.json
```

**If found and status is `in_progress`**:
- Read the progress file
- Log: `"Resuming PR analysis from last checkpoint"`
- Skip steps whose status is `completed`
- Start from the first step whose status is `pending` or `in_progress`

**If found and status is `completed`**:
- Ask the user: `"Previous analysis found for PR #${PR_NUMBER}. Re-run from scratch?"`
- If yes: reset all steps to `pending`, update `updated_at`
- If no: show the output file path and exit

**If not found**: create a new progress file (see below).

### 7. Create progress file

Write to `${BASE_PATH}/workflow/understand-pr_${REPO_NAME}_${PR_NUMBER}.json`. Fields: `workflow` ("understand-pull-request"), `target`, `pr_number`, `platform`, `repo_path`, `base_path`, `pr_base` (all absolute paths), `status` ("in_progress"), `created_at`/`updated_at` (ISO 8601 UTC), `step_order` (["pr-metadata", "repo-context", "change-analysis", "synthesis"]), `steps` (each with `status: "pending"`, `output: null`, `result: null`).

### 8. Show analysis plan

Log:

```
Understand-PR: Analyzing PR #<PR_NUMBER> in <REPO_NAME>
  Platform:   <github|gitlab>
  Repository: <absolute-path>
  Steps:      pr-metadata → repo-context → change-analysis → synthesis
```

---

## Step 1 — PR Metadata

Fetch PR/MR metadata and diffs using the platform CLI tool.

### 1.1 Set output path

```bash
OUTPUT_DIR="${PR_BASE}/pr-metadata"
mkdir -p "$OUTPUT_DIR"
```

### 1.2 Fetch PR metadata

```bash
GIT_PR_READER="${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py"

python3 "${GIT_PR_READER}" metadata "${PR_URL}" \
  --diff-output "${OUTPUT_DIR}/diff.patch"
```

Capture the JSON output. If it contains an `error` field, STOP and report the error.

### 1.3 Write metadata.json

Write the JSON output to `${OUTPUT_DIR}/metadata.json`.

### 1.4 Write step-result.json

Write to `${OUTPUT_DIR}/step-result.json` with: `schema_version: 1`, `step: "pr-metadata"`, `target`, `pr_number`, `completed_at` (ISO 8601 UTC), `title`, `author`, `state`, `files_changed`, `commits`.

### 1.5 Update progress

Update the progress file: set `steps.pr-metadata.status` to `completed`, set `steps.pr-metadata.output` to `${OUTPUT_DIR}/`. Update `updated_at`.

Log: `"PR metadata fetched: '<title>' by <author> — <file_count> files changed, <commit_count> commits"`.

---

## Step 2 — Repo Context

Detect language, build module map, and produce a brief repo overview.

### 2.1 Set output path

```bash
OUTPUT_DIR="${PR_BASE}/repo-context"
mkdir -p "$OUTPUT_DIR"
```

### 2.2 Detect language

Use the learn-code detection scripts (shared across skills):

```bash
LEARN_CODE_SCRIPTS="${CLAUDE_PLUGIN_ROOT}/skills/learn-code/scripts"
python3 ${LEARN_CODE_SCRIPTS}/detect_language.py --repo "${REPO_PATH}"
```

Capture the JSON output. Extract `primary_language`.

### 2.3 Build module map

```bash
python3 ${LEARN_CODE_SCRIPTS}/build_module_map.py \
  --repo "${REPO_PATH}" \
  --lang "${PRIMARY_LANGUAGE}"
```

Capture the JSON output.

### 2.4 Read config files

From the module map result, read each file listed in `config_files` from the repo. Truncate each to 5000 characters.

### 2.5 Write detection.json

Combine detection and module map results into a single detection JSON (same format as learn-code's detection.json). Write to `${OUTPUT_DIR}/detection.json`.

### 2.6 Produce repo overview

Check if a prior learn-code analysis exists:

```bash
ONBOARDING_FILE="${BASE_PATH}/synthesis/ONBOARDING.md"
```

**If `${ONBOARDING_FILE}` exists:**

Read the file. Extract the content between `## Architecture Overview` and the next `## ` heading. Write this section to `${OUTPUT_DIR}/repo-overview.md`.

Log: `"Reusing repo overview from existing learn-code analysis"`.

**If `${ONBOARDING_FILE}` does not exist:**

Dispatch `subagent_type: docs-skills:pr-repo-summarizer`. Include in the prompt: DETECTION_DATA (primary_language, modules, module_count as JSON), CONFIG_CONTENTS (each config file with headers), REPO_PATH, and OUTPUT_FILE (`<OUTPUT_DIR>/repo-overview.md`). Request a 2-3 paragraph overview.

Verify `${OUTPUT_DIR}/repo-overview.md` was written. If the agent failed, create a minimal overview:

```markdown
Repository: <REPO_NAME>
Language: <primary_language>
Modules: <module_count>

No detailed overview available. Run /docs-skills:learn-code for a full analysis.
```

### 2.7 Write step-result.json

Write to `${OUTPUT_DIR}/step-result.json` with: `schema_version: 1`, `step: "repo-context"`, `target`, `completed_at`, `primary_language`, `module_count`, `overview_source` (one of "learn-code", "pr-repo-summarizer", "fallback").

### 2.8 Update progress

Update progress file for `repo-context` step. Log: `"Repo context ready: <primary_language>, <module_count> modules, overview from <source>"`.

---

## Step 3 — Change Analysis

Identify affected modules, then fan-out pr-change-analyzer agents.

### 3.1 Set paths

```bash
METADATA_FILE="${PR_BASE}/pr-metadata/metadata.json"
DETECTION_FILE="${PR_BASE}/repo-context/detection.json"
DIFF_FILE="${PR_BASE}/pr-metadata/diff.patch"
OUTPUT_DIR="${PR_BASE}/change-analysis"
mkdir -p "$OUTPUT_DIR"
```

### 3.2 Identify affected modules

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/identify_affected_modules.py \
  --metadata "${METADATA_FILE}" \
  --detection "${DETECTION_FILE}"
```

Capture the JSON output. Write to `${OUTPUT_DIR}/affected-modules.json`.

If `total_modules_affected` is 0 and there are `unmatched_files`, log a note that all changes are outside detected modules (config/docs/CI changes).

Log: `"Affected modules: <count> modules, <unmatched_count> files outside modules"`.

### 3.3 Prepare per-module data

For each module in `affected_modules`:

**Load module source**: Concatenate source files with `### FILE:` headers. Use the file list from `detection.modules.<module-name>.files`. If the module has > 3000 total lines, run the appropriate API extraction script instead:

**Python:**
```bash
python3 ${LEARN_CODE_SCRIPTS}/extract_public_api.py \
  --files <file1> <file2> ... \
  --lang python --module <module-name>
```

**Go, JavaScript, TypeScript:**
```bash
uv run --script ${LEARN_CODE_SCRIPTS}/extract_public_api_treesitter.py -- \
  --files <file1> <file2> ... \
  --lang <lang> --module <module-name>
```

**Extract module diffs**: From the full diff file (`diff.patch`), extract only the hunks that affect files in this module. Read the diff file and filter sections matching the module's file paths.

**Load PR metadata**: Read `metadata.json` for title, description, and commit messages.

### 3.4 Batch dispatch pr-change-analyzer agents

Group affected modules into batches of **max 10 agents per batch**. Dispatch each batch as a single message for parallel execution. Wait for the batch to complete before dispatching the next.

Each agent uses `subagent_type: docs-skills:pr-change-analyzer`. Include in the prompt: MODULE name, LANGUAGE, SOURCE (concatenated with `### FILE:` headers or API surface), DIFFS (filtered hunks), PR_METADATA (title, description, commits), a note to trust code changes over descriptions, REPO_PATH, and OUTPUT_FILE (`<OUTPUT_DIR>/<safe-module-name>.json`). For large modules (>3000 lines), note that source is API-only.

**Critical**: All Agent tool calls within a single batch MUST be in a single message for parallel execution.

### 3.5 Collect and merge results

After all batches complete, read each `<OUTPUT_DIR>/<safe-module-name>.json` file.

For modules where the agent failed or produced invalid JSON, create a fallback entry with `module`, `change_purpose: "Analysis failed — review changes manually"`, empty arrays for `files_analyzed`, `breaking_changes`, `depends_on_modules`, `impact: "Unknown"`, and `risks: ["Automated analysis failed for this module"]`.

### 3.6 Write change-summary.json

Combine all module change results into a single JSON array. Write to `${OUTPUT_DIR}/change-summary.json`.

### 3.7 Write step-result.json

Write to `${OUTPUT_DIR}/step-result.json` with: `schema_version: 1`, `step: "change-analysis"`, `target`, `pr_number`, `completed_at`, `modules_analyzed`, `modules_failed`, `unmatched_files`, `total_risks`, `breaking_changes`.

### 3.8 Update progress

Update progress file for `change-analysis` step. Log: `"Change analysis complete: <analyzed> modules (failed: N), <risk_count> risks identified"`.

---

## Step 4 — Synthesis

Combine all data and produce the final PR analysis document.

### 4.1 Set output path

```bash
OUTPUT_DIR="${PR_BASE}/synthesis"
mkdir -p "$OUTPUT_DIR"
```

### 4.2 Build synthesis context

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/build_pr_context.py \
  --pr-base "${PR_BASE}" \
  --max-size 80000 > "${OUTPUT_DIR}/context.json"
```

If the output contains an `error` field, STOP and report the error.

Log: `"Synthesis context: <context_size_bytes> bytes (truncated: <yes|no>)"`.

### 4.3 Dispatch pr-synthesis-writer agent

Dispatch `subagent_type: docs-skills:pr-synthesis-writer`. The context is at `${OUTPUT_DIR}/context.json` — the agent reads it from disk. Tell the agent to write `PR-<PR_NUMBER>-ANALYSIS.md` to OUTPUT_DIR, following `${CLAUDE_PLUGIN_ROOT}/reference/pr-analysis-template.md`.

### 4.4 Verify output

Confirm `${OUTPUT_DIR}/PR-${PR_NUMBER}-ANALYSIS.md` exists. If it does not, STOP and report the synthesis agent failed.

### 4.5 Write step-result.json

Write to `${OUTPUT_DIR}/step-result.json` with: `schema_version: 1`, `step: "synthesis"`, `target`, `pr_number`, `completed_at`, `output_file` ("PR-<PR_NUMBER>-ANALYSIS.md"), `context_size_bytes`.

### 4.6 Update progress

Update progress file for `synthesis` step. Log: `"Synthesis complete: PR-${PR_NUMBER}-ANALYSIS.md written"`.

---

## Failure Handling

If any step fails (script error, agent failure, missing output):

- Set `steps.<step-name>.status` to `failed` in the progress file
- Log the error
- Ask the user: `"Step <step-name> failed. Retry or skip?"`
- If retry: reset to `pending` and re-run the step
- If skip: mark as `failed` and continue (downstream steps may also fail)

---

## Completion

After all steps complete, set `status` to `completed`, update `updated_at`, write the progress file, and display the completion summary. See [completion template](references/completion-template.md) for the exact output format and suggested next steps.

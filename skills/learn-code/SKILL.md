---
name: learn-code
description: Analyze a codebase for engineer onboarding. Detects language, maps modules, analyzes each module in parallel, discovers cross-module relationships, and produces an ONBOARDING.md guide.
argument-hint: <repo-path-or-url> [--exclude <glob>...]
allowed-tools: Read, Write, Bash, Glob, Grep, Agent
---

# Learn-Code — Codebase Analysis for Onboarding

Single-skill pipeline that detects language, maps modules, analyzes each module in parallel via fan-out agents, discovers cross-module relationships, and produces a structured onboarding guide.

## Usage

```
/docs-skills:learn-code /path/to/repo
/docs-skills:learn-code https://github.com/user/repo
/docs-skills:learn-code /path/to/repo --exclude "test/*" "vendor/*"
```

## Arguments

- `$1` — Path or URL of the repository to analyze (required). Local path or git URL. URLs are cloned to `.agent_workspace/<repo-name>/_clone/`
- `--exclude <glob>...` — Glob patterns to exclude from analysis

## Pre-flight

### 1. Parse and validate arguments

Extract the repo path from the first positional argument. Extract any `--exclude` patterns.

### 2. Resolve repo path

**Git URL** (matches `https://`, `http://`, `git@`, `git://`): Derive `REPO_NAME` from the last path segment (strip `.git`). Set `GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"`. Clone to `${GIT_ROOT}/.agent_workspace/${REPO_NAME}/_clone` via `git_pr_reader.py clone`. If clone dir exists, ask user to pull or use as-is. STOP on clone failure.

**Local path**: Validate it exists, is a directory, and has files. Resolve to absolute. Derive `REPO_NAME` from basename. STOP if path not found.

### 3. Set base path

```bash
GIT_ROOT="$(cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)" && pwd)"
BASE_PATH="${GIT_ROOT}/.agent_workspace/${REPO_NAME}"
mkdir -p "${BASE_PATH}"
```

### 4. Check for existing progress (resume)

Check for `${BASE_PATH}/workflow/learn-code_${REPO_NAME}.json`. If found and `in_progress`: resume from first `pending`/`in_progress` step. If `completed`: ask user to re-run or show existing results. If not found: create new progress file.

### 5. Create progress file

Write to `${BASE_PATH}/workflow/learn-code_${REPO_NAME}.json`. See [output schemas](references/output-schemas.md#progress-file) for the JSON structure.

### 6. Show analysis plan

Log the repo name, absolute path, step order, and exclude patterns.

---

## Step 1 — Detection

Detect the primary language, walk the file tree to build a module map, and read config files.

### 1.1 Set output path

```bash
OUTPUT_DIR="${BASE_PATH}/detection"
mkdir -p "$OUTPUT_DIR"
```

### 1.2 Detect language

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/detect_language.py --repo <REPO_PATH>
```

Capture the JSON output. If it contains an `error` field, STOP and report the error.

Extract `primary_language` from the result.

### 1.3 Build module map

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/build_module_map.py --repo <REPO_PATH> --lang <PRIMARY_LANGUAGE> [--exclude <PATTERNS>...]
```

Capture the JSON output. If it contains an `error` field, STOP and report the error.

### 1.4 Read config files

From the module map result, read each file listed in `config_files`. Read the actual file content from the repo (e.g., `<REPO_PATH>/pyproject.toml`). Truncate each config file to 5000 characters.

### 1.5 Write detection.json

Combine all detection and module map results. Write to `${OUTPUT_DIR}/detection.json`. See [output schemas](references/output-schemas.md#detectionjson) for the JSON structure.

### 1.6 Write step-result.json

Write to `${OUTPUT_DIR}/step-result.json`. See [output schemas](references/output-schemas.md#step-resultjson-detection) for the JSON structure.

### 1.7 Update progress

Update the progress file: set `steps.detection.status` to `completed`, set `steps.detection.output` to `${OUTPUT_DIR}/`, set `steps.detection.result` to the step-result data. Update `updated_at`.

Log: `"Detection complete: <primary_language>, <module_count> modules, <total_source_files> source files"`.

---

## Step 2 — Module Registry

Dispatch the repo-mapper agent to produce a per-module registry with tailored analysis questions.

### 2.1 Set paths

```bash
INPUT_FILE="${BASE_PATH}/detection/detection.json"
OUTPUT_DIR="${BASE_PATH}/module-registry"
mkdir -p "$OUTPUT_DIR"
```

### 2.2 Read detection data

Read `${INPUT_FILE}`. If it does not exist, STOP and report that the detection step must complete first.

Extract `primary_language`, `modules`, `config_contents`, `module_count`.

If `module_count` is 0, write an empty registry and step-result, then skip to Step 3.

### 2.3 Dispatch repo-mapper agent

Use `subagent_type: docs-skills:repo-mapper`. Include in the prompt: DETECTION_DATA (modules, module_count, config_files as JSON), CONFIG_CONTENTS (each config file with filename header), and REPO_PATH. Request a JSON array of module entries.

### 2.4 Parse agent response

The agent should return a JSON array. Parse it into `registry.json`.

If the agent response is not valid JSON:
1. Try to extract a JSON array from the response (look for `[` ... `]`)
2. If that fails, create a fallback registry with minimal entries for each module

### 2.5 Write registry.json

Write the parsed JSON array to `${OUTPUT_DIR}/registry.json`.

### 2.6 Write registry.md

Generate a human-readable markdown table. Write to `${OUTPUT_DIR}/registry.md`. See [output templates](references/output-templates.md#registrymd-step-2) for the format.

### 2.7 Write step-result.json

Write to `${OUTPUT_DIR}/step-result.json`. See [output schemas](references/output-schemas.md#step-resultjson-module-registry) for the JSON structure.

### 2.8 Update progress

Update progress file for `module-registry` step. Log: `"Registry complete: <module_count> modules (low: N, medium: N, high: N)"`.

---

## Step 3 — Module Analysis

Fan-out module-analyzer agents with size-aware tiering and batched dispatch.

### 3.1 Set paths

```bash
REGISTRY_FILE="${BASE_PATH}/module-registry/registry.json"
DETECTION_FILE="${BASE_PATH}/detection/detection.json"
OUTPUT_DIR="${BASE_PATH}/module-analysis"
mkdir -p "$OUTPUT_DIR"
```

### 3.2 Read upstream data

Read `${REGISTRY_FILE}` and `${DETECTION_FILE}`.

Extract `primary_language`, module file lists from `detection.modules`, and registry entries.

### 3.3 Classify modules into tiers

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/classify_modules.py \
  --detection "${DETECTION_FILE}" \
  --registry "${REGISTRY_FILE}"
```

Capture the JSON output. This produces three tiers:

| Tier | Criteria | Agent strategy |
|------|----------|----------------|
| `full` | ≤3000 lines, non-low complexity | Full source in prompt |
| `api-guided` | 3001–8000 lines, or low-complexity multi-file | API + truncated source (first 2000 lines). Agent reads more from disk if needed |
| `api-only` | >8000 lines, or auto-generated code, or single low-complexity file | No agent dispatch — generate entry from API + registry |

Log: `"Module tiers: <full_count> full, <api_guided_count> api-guided, <api_only_count> api-only"`.

### 3.4 Pre-extract public API (AST-aware)

For each module, run the language-appropriate AST extraction: Python uses `extract_public_api.py --files <files> --lang python --module <name>`. Go/JS/TS use `uv run --script ${CLAUDE_SKILL_DIR}/scripts/extract_public_api_treesitter.py -- --files <files> --lang <lang> --module <name>`. Log warning and continue if extraction fails for a module.

### 3.5 Generate api-only entries (no agent dispatch)

For each module in the `api-only` tier, generate a summary entry directly from the pre-extracted API and registry data. Write each to `${OUTPUT_DIR}/<safe-module-name>.json`. See [output schemas](references/output-schemas.md#api-only-fallback-entry) for the JSON structure.

### 3.6 Load source for agent-analyzed modules

For `full` and `api-guided` tiers, concatenate source files with `### FILE: <relative-path>` headers. Keep all import statements (relationship signal). For `api-guided`: truncate to first 2000 lines with a `### [TRUNCATED]` note.

### 3.7 Batch dispatch module-analyzer agents

Group `full` and `api-guided` modules into batches of **max 10 agents per batch**. Dispatch each batch as a single message for parallel execution. Wait for the batch to complete before dispatching the next.

Each agent uses `subagent_type: docs-skills:module-analyzer`. Include in the prompt: MODULE name, LANGUAGE, QUESTION from registry, PUBLIC_API (pre-extracted AST JSON or "Not available"), SOURCE (concatenated with `### FILE:` headers), and output path `<OUTPUT_DIR>/<safe-module-name>.json`. For `api-guided` modules, add REPO_PATH and a note that source is truncated.

**Critical**: All Agent tool calls within a single batch MUST be in a single message for parallel execution.

### 3.8 Collect and merge results

After all batches complete, read each `<OUTPUT_DIR>/<safe-module-name>.json` file.

For modules where the agent failed or produced invalid JSON, create a fallback entry. See [output schemas](references/output-schemas.md#agent-failure-fallback-entry) for the JSON structure.

### 3.9 Write summary.json

Combine all module results (api-only, agent-analyzed, and fallback) into a single JSON array. Write to `${OUTPUT_DIR}/summary.json`.

### 3.10 Write summary.md

Generate a human-readable summary. Write to `${OUTPUT_DIR}/summary.md`. See [output templates](references/output-templates.md#summarymd-step-3) for the format.

### 3.11 Write step-result.json

Write to `${OUTPUT_DIR}/step-result.json`. See [output schemas](references/output-schemas.md#step-resultjson-module-analysis) for the JSON structure.

### 3.12 Update progress

Update progress file for `module-analysis` step. Log: `"Module analysis complete: <analyzed> modules (full: N, api-guided: N, api-only: N, failed: N)"`.

---

## Step 4 — Relationships

Cross-module dependency analysis with prioritized pair selection and batched dispatch.

### 4.1 Set paths

```bash
SUMMARY_FILE="${BASE_PATH}/module-analysis/summary.json"
DETECTION_FILE="${BASE_PATH}/detection/detection.json"
REGISTRY_FILE="${BASE_PATH}/module-registry/registry.json"
OUTPUT_DIR="${BASE_PATH}/relationships"
mkdir -p "$OUTPUT_DIR"
```

### 4.2 Read upstream data

Read `${SUMMARY_FILE}`, `${DETECTION_FILE}`, and `${REGISTRY_FILE}`.

### 4.3 Build dependency pairs

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/build_dep_pairs.py \
  --summaries "${SUMMARY_FILE}" \
  --registry "${REGISTRY_FILE}"
```

Capture JSON output. If `total_pairs` is 0, write empty results and step-result, then skip to Step 5.

### 4.4 Prioritize pairs

**Priority** (max 20): at least one module is "high" complexity or "read-first" priority, AND both have `analysis_depth` != "api-only". Sort by: both "high" first. **Lightweight**: all remaining pairs — generate entries directly (see [output schemas](references/output-schemas.md#lightweight-pair-entry)).

### 4.5 Prepare source data for priority pairs

For each pair `(module_a, module_b)`: **Module A**: if ≤3000 lines, concatenate source with `### FILE:` headers; otherwise use pre-extracted API. **Module B**: always API surface only (via `extract_public_api.py` or `extract_public_api_treesitter.py`).

### 4.6 Read language guidance

Read language-specific relationship analysis guidance from `${CLAUDE_PLUGIN_ROOT}/reference/language-configs.md`.

### 4.7 Batch dispatch relationship-analyzer agents

Group priority pairs into batches of **max 10 agents per batch**. Dispatch each batch as a single message for parallel execution. Wait for the batch to complete before dispatching the next.

Each agent uses `subagent_type: docs-skills:relationship-analyzer`. Include in the prompt: MODULE_A, MODULE_B, LANGUAGE, SOURCE_A (full source or API surface), API_B (public API JSON), LANGUAGE_GUIDANCE (from language-configs.md), REPO_PATH, and output path `<OUTPUT_DIR>/<mod_a>--<mod_b>.json`. For large module A (>3000 lines), note that source is API-only and agent should read from REPO_PATH.

**Critical**: All Agent tool calls within a single batch MUST be in a single message for parallel execution.

### 4.8 Collect and merge results

After all batches complete, read each `<OUTPUT_DIR>/<mod_a>--<mod_b>.json` file. For failed agents or missing files, create a fallback entry. See [output schemas](references/output-schemas.md#agent-failure-fallback-entry-1) for the JSON structure.

Combine agent results with the lightweight entries from step 4.4.

### 4.9 Write relationships.json

Write the array of all relationship results (priority + lightweight) to `${OUTPUT_DIR}/relationships.json`.

### 4.10 Write dependency-graph.json

Build a graph structure from the summaries and relationships. Write to `${OUTPUT_DIR}/dependency-graph.json`. See [output schemas](references/output-schemas.md#dependency-graphjson) for the JSON structure.

### 4.11 Write relationships.md

Generate a human-readable summary. Write to `${OUTPUT_DIR}/relationships.md`. See [output templates](references/output-templates.md#relationshipsmd-step-4) for the format.

### 4.12 Write step-result.json

Write to `${OUTPUT_DIR}/step-result.json`. See [output schemas](references/output-schemas.md#step-resultjson-relationships) for the JSON structure.

### 4.13 Update progress

Update progress file for `relationships` step. Log: `"Relationship analysis complete: <priority_count> priority + <lightweight_count> lightweight pairs (tight: N, loose: N, none: N)"`.

---

## Step 5 — Synthesis

Combine all module summaries and relationship data to produce the final ONBOARDING.md.

### 5.1 Set output path

```bash
OUTPUT_DIR="${BASE_PATH}/synthesis"
mkdir -p "$OUTPUT_DIR"
```

### 5.2 Build synthesis context

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/build_synthesis_context.py \
  --base-path "${BASE_PATH}" \
  --max-size 80000 > "${OUTPUT_DIR}/context.json"
```

If the output contains an `error` field, STOP and report the error.

The `--max-size 80000` flag ensures the context stays within agent context limits by progressively compacting summaries and relationships.

Log: `"Synthesis context: <context_size_bytes> bytes (truncated: <truncated or 'no'>)"`.

### 5.3 Dispatch synthesis-writer agent

Dispatch `subagent_type: docs-skills:synthesis-writer`. The context is written to `${OUTPUT_DIR}/context.json` — the agent reads it from disk. Tell the agent to write ONBOARDING.md (and dependency-graph.json if relationships exist) to OUTPUT_DIR, following the template from `${CLAUDE_PLUGIN_ROOT}/reference/onboarding-template.md`.

### 5.4 Verify output

Confirm `${OUTPUT_DIR}/ONBOARDING.md` exists. If it does not, STOP and report the synthesis agent failed.

### 5.5 Write step-result.json

Scan ONBOARDING.md for level-2 headings (`##`) to determine sections. Write to `${OUTPUT_DIR}/step-result.json`. See [output schemas](references/output-schemas.md#step-resultjson-synthesis) for the JSON structure.

### 5.6 Update progress

Update progress file for `synthesis` step. Log: `"Synthesis complete: ONBOARDING.md written to ${OUTPUT_DIR}"`.

---

## Failure Handling

If any step skill fails (throws an error or does not produce output):
- Set `steps.<step-name>.status` to `failed` in the progress file
- Log the error
- Ask the user: `"Step <step-name> failed. Retry or skip?"`
- If retry: reset to `pending` and re-run the step
- If skip: mark as `failed` and continue (downstream steps with this as input may also fail)

---

## Completion

After all steps complete:

### Update workflow status

Set `status` to `completed`. Update `updated_at`. Write progress file.

### Print completion summary and suggest next steps

See [output templates](references/output-templates.md#completion-summary) for the summary format and suggested next steps.

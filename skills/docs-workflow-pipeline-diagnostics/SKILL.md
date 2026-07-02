---
name: docs-workflow-pipeline-diagnostics
description: Diagnose a docs-orchestrator pipeline run for failures, bottlenecks, and context-pressure risks. Runs the diagnostics script, drills into failures, and writes a diagnostic report with actionable recommendations.
argument-hint: <ticket> --base-path <path> [--ci-log <path>]
allowed-tools: Read, Write, Bash, Glob, Grep
---

# Pipeline Diagnostics Step

Step skill for the docs-orchestrator pipeline. Follows the step skill contract: **parse args → run diagnostics script → analyze results → write output**.

## Arguments

- `$1` — JIRA ticket ID (required)
- `--base-path <path>` — Base output path (e.g., `.agent_workspace/proj-123`)
- `--ci-log <path>` — Path to a CI session log (optional). Enables CI-specific analysis

## Input

Reads the progress file and step-result sidecars from all upstream steps:

```
<base-path>/workflow/*.json
<base-path>/*/step-result.json
```

## Output

```
<base-path>/pipeline-diagnostics/report.md
<base-path>/pipeline-diagnostics/diagnostics.json
<base-path>/pipeline-diagnostics/step-result.json
```

## Execution

### 1. Parse arguments

Extract the ticket ID, `--base-path`, and optional `--ci-log` from the args string.

Set the paths:

```bash
OUTPUT_DIR="${BASE_PATH}/pipeline-diagnostics"
REPORT_FILE="${OUTPUT_DIR}/report.md"
DIAGNOSTICS_FILE="${OUTPUT_DIR}/diagnostics.json"
mkdir -p "$OUTPUT_DIR"
```

### 2. Run the diagnostics script

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline_diagnostics.py <TICKET> \
  --workspace "$(dirname "${BASE_PATH}")" \
  --format json \
  --emit-sidecar "${OUTPUT_DIR}/step-result.json" > "$DIAGNOSTICS_FILE"
```

If a direct progress file path is known, use `--progress-file` instead:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline_diagnostics.py \
  --progress-file <path-to-progress-json> \
  --format json \
  --emit-sidecar "${OUTPUT_DIR}/step-result.json" > "$DIAGNOSTICS_FILE"
```

`--emit-sidecar` writes the schema-conformant `step-result.json` directly from the computed
analysis — every field is derived, and `completed_at` is a real wall-clock timestamp. This is the
authoritative sidecar; do **not** hand-author it later (see step 8).

Check the exit code. If the script failed, write an error to the report and exit.

### 3. Read and analyze the diagnostics output

Read `$DIAGNOSTICS_FILE`. The script produces structured JSON with these sections:

1. **summary** — ticket, workflow type, status, total duration
2. **context_pressure** — risk level, score, contributing factors
3. **failures** — failed steps, missing outputs, missing sidecars, quality issues
4. **bottlenecks** — steps that took disproportionately long
5. **orchestrator_health** — self-introspection issues (computed by the script; see step 6)
6. **recommendations** — actionable next steps

### 4. Drill into failures

For each failure in the diagnostics output, examine the root cause:

| Failure type | Where to look |
|---|---|
| `step_failed` | Re-read the step's output folder for error messages. Check if an upstream dependency (`inputs`) was not met |
| `missing_output` | The step was marked completed but its output folder is gone. Likely manual deletion or filesystem issue |
| `missing_sidecar` | Step completed without writing `step-result.json`. May indicate context compaction lost the sidecar-write instruction |
| `step_deferred` | Upstream `when` condition was never resolved. Check if source resolution failed |
| `low_confidence` | Read `technical-review/review.md` for specific issues |
| `quality_gate_low` | Read `quality-gate/judge-results.md` for the judge's rationale |
| `empty_plan` | Requirements may be too vague or code-analysis found nothing relevant |
| `no_files_written` | Check if the plan was empty or if the writer agent failed |

### 5. CI log analysis (optional)

If `--ci-log` was provided, also analyze the session log:

```bash
rg -n 'ERROR:|FAILED|Traceback|exit code [1-9]' <ci-log-path>
tail -20 <ci-log-path>
rg -n 'compact|context.*limit|token.*limit' <ci-log-path>
```

Check for: error patterns, session aborts, context compaction markers, stop hook blocks.

### 6. Orchestrator self-introspection

Self-introspection covers orchestrator-level problems — not content quality, but the
docs-orchestrator machinery itself. **The script already computes the deterministic checks** and
returns them in the `orchestrator_health` array of `$DIAGNOSTICS_FILE`. Read that array; do NOT
re-derive these checks by hand:

| Check (`check` field) | Severity |
|---|---|
| `schema_drift` — required progress fields missing/null, or no resolvable `workflow` type | high / medium |
| `missing_sidecar` — step is `completed` but wrote no `step-result.json` | high |
| `null_result` — step is `completed` but `.steps[name].result` is `null` | medium |
| `stuck_in_progress` — step never left `in_progress` | high |
| `deferred_unresolved` — a `deferred` step remained deferred at workflow end | medium |
| `workarounds_applied` — the progress file's `workarounds` array is non-empty | medium |
| `active_marker_left` — `.agent_workspace/.active-workflow` still exists after `status=completed` | low |
| `timestamp_gap` — > 10 min elapsed before a step completed | low |

**Two checks the script cannot compute — add them yourself** only when the inputs are available,
appending to the health list you carry into the report:

| Check | How to detect | Severity |
|---|---|---|
| **Step order vs YAML mismatch** | Compare the progress `step_order` against the workflow YAML's step list. Missing or extra entries indicate manual edits or schema rot | medium |
| **Hook errors during run** | If `--ci-log` was provided, grep for `Stop hook error:` or `hook.*error` lines | high |

The combined list (script `orchestrator_health` + any of the two checks above) is what you tabulate
in the report. The sidecar's `orchestrator_issue_count` reflects only the script-computed subset.

### 7. Write the diagnostic report

Write `$REPORT_FILE` using this template:

```markdown
# Pipeline Diagnostic Report: <TICKET>

## Run summary
- **Status**: completed | failed | in_progress
- **Duration**: N minutes
- **Steps**: N/M completed
- **Context pressure**: LOW | MODERATE | HIGH | CRITICAL (score N)

## Failures
<!-- For each failure -->
### <step-name>: <failure type>
- **Root cause**: ...
- **Fix**: ...

## Workarounds
<!-- For each workaround in progress file -->
- **<step>**: <issue> — Orchestrator action: <action>

<!-- If no workarounds: -->
No script workarounds were applied.

## Bottlenecks
<!-- For each bottleneck -->
- **<step>**: N min (Nx average) — <mitigation>

## Context pressure
- **Level**: ... (score N)
- **Risk factors**: ...
- **Symptoms observed**: ...

## Orchestrator health

<!-- One row per entry in the combined health list (script orchestrator_health + step-6 additions) -->

| Step | Check | Severity | Detail |
|---|---|---|---|
| — | active_marker_left | low | `.active-workflow` still present after status=completed |

<!-- If no problems found: -->
No orchestrator issues detected.

## Recommendations
1. ...
2. ...
```

### 8. Verify the step-result.json sidecar

The `--emit-sidecar` flag in step 2 **already wrote** `${OUTPUT_DIR}/step-result.json` from the
computed analysis, with every field derived and a real wall-clock `completed_at`. Do **not**
hand-author or overwrite it — a hand-written sidecar drifts from the schema.

Verify the file exists and contains the required fields:

```bash
jq -e '.schema_version and .pipeline_status and (.orchestrator_issue_count != null)' \
  "${OUTPUT_DIR}/step-result.json" >/dev/null || echo "ERROR: sidecar missing or malformed"
```

If the file is missing or malformed, the script did not emit it — re-run step 2 with
`--emit-sidecar`. Do not substitute a stub.

The sidecar fields, all populated by the script:

| Field | Source |
|---|---|
| `pipeline_status` | `summary.status` |
| `context_pressure_level` / `context_pressure_score` | `context_pressure` |
| `failure_count` / `high_severity_failure_count` | `failures` |
| `bottleneck_count` | `bottlenecks` |
| `orchestrator_issue_count` | `orchestrator_health` (script-computed subset) |
| `workaround_count` | `workarounds` |
| `recommendation_count` | `recommendations` |
| `total_duration_min` | `summary.total_duration_min` |

## Context pressure reference

See [context-pressure.md](reference/context-pressure.md) for the full context pressure detection model, risk score calculation, and mitigation strategies.

| Level | Score | Meaning |
|---|---|---|
| **low** | 0–2 | Normal operation. No intervention needed |
| **moderate** | 3–5 | Some context accumulation. Monitor for compaction behavior |
| **high** | 6–8 | Significant risk of compaction-related issues. Consider workflow splitting |
| **critical** | 9+ | Near-certain compaction will occur. Split the workflow or reduce step count |

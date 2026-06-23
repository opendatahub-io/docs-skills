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
  --format json > "$DIAGNOSTICS_FILE"
```

If a direct progress file path is known, use `--progress-file` instead:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/pipeline_diagnostics.py \
  --progress-file <path-to-progress-json> \
  --format json > "$DIAGNOSTICS_FILE"
```

Check the exit code. If the script failed, write an error to the report and exit.

### 3. Read and analyze the diagnostics output

Read `$DIAGNOSTICS_FILE`. The script produces structured JSON with these sections:

1. **summary** — ticket, workflow type, status, total duration
2. **context_pressure** — risk level, score, contributing factors
3. **failures** — failed steps, missing outputs, missing sidecars, quality issues
4. **bottlenecks** — steps that took disproportionately long
5. **recommendations** — actionable next steps

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

Analyze the workflow run for orchestrator-level problems — not content quality, but the docs-orchestrator machinery itself. Read the progress file and each step's sidecar, then check for the issues below.

| Check | How to detect | Severity |
|---|---|---|
| **Progress file schema drift** | Fields the orchestrator wrote that hooks/scripts don't expect (e.g., `workflow` vs `workflow_type`), or required fields that are `null` | high |
| **Missing step-result sidecar** | Step status is `completed` but `<base-path>/<step>/step-result.json` does not exist | high |
| **Null result in progress** | Step is `completed` but `.steps[name].result` is `null` — downstream steps lose structured context | medium |
| **Step stuck in `in_progress`** | A step never transitioned to `completed`/`failed` — suggests agent crash or context compaction mid-step | high |
| **Step order vs YAML mismatch** | Compare `step_order` array against the workflow YAML's step list. Missing or extra entries indicate manual edits or schema rot | medium |
| **Deferred step never resolved** | A `deferred` step remained deferred at workflow end — its `when` condition was never evaluated | medium |
| **Hook errors during run** | If `--ci-log` was provided, grep for `Stop hook error:` or `hook.*error` lines | high |
| **Active-workflow marker left behind** | `.agent_workspace/.active-workflow` still exists after workflow completed — will block future sessions | low |
| **Timestamp gaps** | File mtime gap > 10 min between consecutive steps suggests context compaction or manual intervention | low |

Tabulate every problem found. For each, record: step name (if applicable), check name, severity, and a one-line description.

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

## Bottlenecks
<!-- For each bottleneck -->
- **<step>**: N min (Nx average) — <mitigation>

## Context pressure
- **Level**: ... (score N)
- **Risk factors**: ...
- **Symptoms observed**: ...

## Orchestrator health

| Step | Check | Severity | Detail |
|---|---|---|---|
| — | example: active-workflow marker left behind | low | `.active-workflow` still present after status=completed |

<!-- If no problems found: -->
No orchestrator issues detected.

## Recommendations
1. ...
2. ...
```

### 8. Write step-result.json

Write the sidecar to `${OUTPUT_DIR}/step-result.json`:

```json
{
  "schema_version": 1,
  "step": "pipeline-diagnostics",
  "ticket": "<TICKET>",
  "completed_at": "<current ISO 8601 timestamp>",
  "pipeline_status": "completed | failed | in_progress",
  "context_pressure_level": "low | moderate | high | critical",
  "context_pressure_score": 0,
  "failure_count": 0,
  "high_severity_failure_count": 0,
  "bottleneck_count": 0,
  "orchestrator_issue_count": 0,
  "recommendation_count": 0,
  "total_duration_min": 0
}
```

Replace placeholders with actual values from the diagnostics output.

## Context pressure reference

See [context-pressure.md](reference/context-pressure.md) for the full context pressure detection model, risk score calculation, and mitigation strategies.

| Level | Score | Meaning |
|---|---|---|
| **low** | 0–2 | Normal operation. No intervention needed |
| **moderate** | 3–5 | Some context accumulation. Monitor for compaction behavior |
| **high** | 6–8 | Significant risk of compaction-related issues. Consider workflow splitting |
| **critical** | 9+ | Near-certain compaction will occur. Split the workflow or reduce step count |

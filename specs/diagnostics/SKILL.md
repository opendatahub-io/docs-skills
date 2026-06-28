---
name: docs-pipeline-diagnostics
description: Diagnose docs-orchestrator pipeline runs. Analyzes progress files, step-result sidecars, and artifact sizes to identify failures, bottlenecks, and context pressure. Use when triaging a failed or slow pipeline run, or when investigating context window limits during long workflows.
disable-model-invocation: true

argument-hint: [<ticket>] [--progress-file <path>] [--all] [--ci-log <path>]
---

# Pipeline Diagnostics

Triage failures, identify bottlenecks, and detect context-pressure risks in docs-orchestrator pipeline runs.

## Quick start

Run the diagnostics script against a ticket's pipeline run:

```bash
python3 plugins/docs-tools/skills/docs-pipeline-diagnostics/scripts/pipeline_diagnostics.py <TICKET> --format summary
```

For structured JSON output (for further processing):

```bash
python3 plugins/docs-tools/skills/docs-pipeline-diagnostics/scripts/pipeline_diagnostics.py <TICKET>
```

If no ticket is specified, all runs under `.agent_workspace/` are analyzed.

## Parse arguments

- `$1` — JIRA ticket ID (optional). Searches `.agent_workspace/<ticket>/workflow/` for progress files
- `--progress-file <path>` — Direct path to a progress JSON file. Overrides ticket search
- `--all` — Analyze all pipeline runs found under `.agent_workspace/`
- `--ci-log <path>` — Path to a CI session log (e.g., `.work/cron-runs/<timestamp>-<TICKET>.log`). Enables CI-specific analysis: error extraction, timing from tool-call boundaries, and session abort detection

## Analysis procedure

### Step 1 — Run the diagnostics script

```bash
python3 plugins/docs-tools/skills/docs-pipeline-diagnostics/scripts/pipeline_diagnostics.py \
  <TICKET or --progress-file path> \
  --format summary
```

Read the output. The script produces five sections:

1. **Summary** — ticket, workflow type, status, total duration
2. **Context pressure** — risk level, score, contributing factors
3. **Failures** — failed steps, missing outputs, missing sidecars, quality issues
4. **Bottlenecks** — steps that took disproportionately long
5. **Recommendations** — actionable next steps

### Step 2 — Drill into failures

For each failure identified by the script, examine the root cause:

| Failure type | Where to look |
|---|---|
| `step_failed` | Re-read the step's SKILL.md error-handling section. Check if the failure was an upstream dependency (`inputs` not met) or an internal error |
| `missing_output` | The step was marked completed but its output folder is gone. Likely a manual deletion or filesystem issue. Reset the step to `pending` and re-run |
| `missing_sidecar` | Step completed without writing `step-result.json`. May indicate context compaction lost the sidecar-write instruction. Re-run the step or manually create the sidecar from the step's markdown output |
| `step_deferred` | Upstream `when` condition was never resolved. Check if source resolution failed silently or if `--no-source-repo` should have been passed |
| `low_confidence` | Technical review could not reach acceptable confidence. Read `technical-review/review.md` for specific issues. Check `claim-validation.json` for claim-level detail |
| `quality_gate_low` | Quality gate scored below threshold. Read `quality-gate/judge-results.md` for the judge's rationale. Check gap entries in the sidecar |
| `empty_plan` | Planning produced 0 modules. Requirements may be too vague or code-analysis may have found nothing relevant |
| `no_files_written` | Writing step produced no files. Check if the plan was empty or if the writer agent failed to produce output |

### Step 3 — Assess context pressure

Read [context-pressure.md](reference/context-pressure.md) for the full context pressure detection model.

Key thresholds from the script output:

| Level | Score | Meaning |
|---|---|---|
| **low** | 0–2 | Normal operation. No intervention needed |
| **moderate** | 3–5 | Some context accumulation. Monitor for compaction behavior |
| **high** | 6–8 | Significant risk of compaction-related issues. Consider workflow splitting |
| **critical** | 9+ | Near-certain compaction will occur. Split the workflow or reduce step count |

When context pressure is high or critical, check for these symptoms:

1. **Missing sidecars on late steps** — compaction may have lost the instruction to write `step-result.json`
2. **Repeated step re-reads on resume** — progress file re-reads increase after compaction removes earlier conversation context
3. **Degraded output quality in later steps** — writing or review steps that run after compaction may lack context from early steps (requirements nuance, code-analysis details)

### Step 4 — Check for bottlenecks

For each bottleneck identified:

- **code-analysis >10 min**: The source repo is large. Use `source.yaml` with `scope.include` to limit analysis to relevant directories
- **technical-review >15 min**: Many claims to validate. Reduce plan module count or tighten source code scope
- **writing >15 min**: Many modules to write. Consider splitting the ticket into smaller documentation units
- **scope-req-audit >10 min**: Gap classification is running against many requirements. This is expected for tickets with 15+ requirements

### Step 5 — CI log analysis (optional)

If `--ci-log` is provided, also analyze the session log for:

1. **Error patterns**: Search for `ERROR:`, `FAILED`, `Traceback`, `exit code [^0]`
2. **Session abort**: Check if the log ends abruptly without a completion summary
3. **Tool-call timing**: Parse Skill tool-call boundaries to estimate per-step wall-clock time (more accurate than sidecar `completed_at` differences)
4. **Context compaction markers**: Search for `[context compacted]` or similar system messages that indicate automatic compaction occurred
5. **Stop hook blocks**: Search for `workflow-completion-check` stderr output indicating the Stop hook prevented premature session termination

```bash
# Error extraction from CI log
rg -n 'ERROR:|FAILED|Traceback|exit code [1-9]' <ci-log-path>

# Check for abrupt termination
tail -20 <ci-log-path>

# Context compaction signals
rg -n 'compact|context.*limit|token.*limit' <ci-log-path>
```

### Step 6 — Produce the diagnostic report

After completing the analysis, write a diagnostic report summarizing:

1. **Run status**: Pass/fail, duration, which steps completed
2. **Root causes**: For each failure, the identified root cause and fix
3. **Context pressure assessment**: Current level and whether it contributed to failures
4. **Bottleneck analysis**: Slow steps and recommended mitigations
5. **Actionable recommendations**: Ordered list of next steps

Use this template:

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

## Recommendations
1. ...
2. ...
```

## Interpreting context pressure scores

The diagnostics script uses a weighted heuristic to estimate context pressure. It does not measure actual token counts (those are not available inside the pipeline). Instead, it uses proxy signals:

- **Step count**: Each completed step adds conversation turns, tool calls, and sidecar reads to the context window
- **Artifact size**: Larger artifacts (code-analysis output, requirements docs) contribute more context when steps read them as input
- **Weighted context load**: Some steps are heavier than others — writing and technical-review consume the most context due to full-document generation and claim-by-claim validation
- **Iteration overhead**: Each tech-review or quality-gate retry loop adds a full pass of context (re-read artifacts, re-invoke agents, re-write sidecars)

These are heuristics, not measurements. A "moderate" score means compaction is plausible; "high" means it is likely. See [context-pressure.md](reference/context-pressure.md) for the full model and calibration notes.

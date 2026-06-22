---
name: docs-workflow-review
description: Reflect on the completed workflow run — what went well, what failed or iterated, what patterns emerged — and write a concise summary to the ticket's workspace folder. Final step in the docs-orchestrator pipeline.
argument-hint: <ticket> --base-path <path>
allowed-tools: Read, Write, Glob
---

# Workflow Review

Produce a post-run summary of the docs-orchestrator workflow. Reads step results from the workspace, reflects on what happened during the session, and writes a `review.md` plus `step-result.json` sidecar.

## Arguments

- `$1` — Ticket ID (required). Must contain only alphanumeric characters, hyphens, and underscores (`[A-Za-z0-9_-]+`). Reject values containing path separators, `..`, or whitespace.
- `--base-path <path>` — Base output path (required, e.g., `.agent_workspace/proj-123`). Must be an absolute path containing no `..` sequences. Must not traverse symlinks outside the workspace root.

## Inputs

Reads from the workspace by convention:

| Source | Path | Required |
|--------|------|----------|
| Progress file | `<base-path>/workflow/*_<ticket>.json` | Yes |
| Step result sidecars | `<base-path>/*/step-result.json` | Yes (at least one) |

**Path safety:** Validate both `--base-path` and the ticket ID against the constraints above before constructing any glob pattern or file path. This prevents path traversal outside the intended workspace directory.

## Execution

### 1. Parse arguments

Extract `TICKET` from `$1` and `BASE_PATH` from `--base-path`.

### 2. Read workflow state

Read the progress file from `<BASE_PATH>/workflow/`. Extract:

- `workflow_type`, `created_at`, `updated_at`
- `options` (format, draft, source, PR URLs)
- Per-step status and result data from `steps`

### 3. Read step sidecars

For each step with status `completed`, read its `step-result.json` from `<BASE_PATH>/<step-name>/step-result.json`. Collect key metrics.

**Missing or malformed sidecars:** If a completed step's `step-result.json` does not exist or fails to parse as valid JSON, skip metric extraction for that step and record its key metric as `"unavailable (missing sidecar)"` in the Metrics table. Do not fail the review — this is the final pipeline step and must produce output even with partial data. Log each missing sidecar in the Observations section under "Issues and iterations."

**Field validation:** Before extracting per-step fields, verify that `schema_version`, `step`, and `ticket` are present and that `schema_version` equals `1`. If any common field is missing or has the wrong type, treat the sidecar as malformed (same handling as above). For the expected per-step fields and types, see `skills/docs-orchestrator/schema/step-result-schema.md`.

Per-step metrics to collect:

- **requirements**: `title`, `requirement_count`
- **code-analysis**: `module_count`, `relationship_count`, `languages_detected`
- **pr-analysis**: `pr_number`, `pr_url`
- **planning**: `module_count`
- **writing**: file count from `files` array, `mode`, `format`
- **technical-review**: `confidence`, `severity_counts`, `iteration` count
- **style-review**: completed (no extra fields)
- **quality-gate**: `doc_quality`, `intent_alignment`, `passed`, gap count
- **resolve-feedback**: `gaps_resolved`, `gaps_deferred`
- **create-merge-request**: `url`, `pushed`, `branch`

### 4. Reflect on the session

Think about the full workflow run and note:

- **Steps that iterated** — any step that ran more than once (iteration > 1 in its sidecar). What caused the iteration?
- **Steps that were skipped** — why (condition not met, no source repo, user declined)
- **Steps that failed** — what went wrong
- **Patterns worth noting** — recurring review findings, markup issues, requirement gaps, domain knowledge that was missing
- **What went well** — high-confidence reviews, clean first-pass writing, smooth source resolution

### 5. Write review.md

Create the output directory before writing:

```bash
mkdir -p "${BASE_PATH}/workflow-review"
```

Write the summary to `<BASE_PATH>/workflow-review/review.md`:

```markdown
# Workflow Review: <TICKET>

## Summary

<1-2 sentence overview: what was documented, outcome>

## Metrics

| Step | Status | Key metric |
|------|--------|------------|
| requirements | completed | <requirement_count> requirements |
| ... | ... | ... |

## Observations

### What went well
<bullet list>

### Issues and iterations
<bullet list — what caused iterations, failures, or skipped steps>

### Patterns
<bullet list — recurring themes, markup issues, domain gaps worth noting for future runs>
```

Keep the entire file under 80 lines. Be specific and concise — this is a reference for future runs on similar tickets, not a narrative.

### 6. Write step-result.json

Write the sidecar to `<BASE_PATH>/workflow-review/step-result.json`:

```json
{
  "schema_version": 1,
  "step": "workflow-review",
  "ticket": "<TICKET>",
  "completed_at": "<ISO 8601>",
  "steps_completed": <count>,
  "steps_skipped": <count>,
  "steps_failed": <count>,
  "iterations": {
    "<step_name>": <iteration count>
  },
  "observation_count": <total bullet points in Observations>
}
```

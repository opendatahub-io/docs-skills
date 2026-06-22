---
name: docs-workflow-review
description: Reflect on the completed workflow run — what went well, what failed or iterated, what patterns emerged — and write a concise summary to the ticket's workspace folder. Final step in the docs-orchestrator pipeline.
argument-hint: <ticket> --base-path <path>
allowed-tools: Read, Write, Glob
---

# Workflow Review

Produce a post-run summary of the docs-orchestrator workflow. Reads step results from the workspace, reflects on what happened during the session, and writes a `review.md` plus `step-result.json` sidecar.

## Arguments

- `$1` — Ticket ID (required)
- `--base-path <path>` — Base output path (required, e.g., `.agent_workspace/proj-123`)

## Inputs

Reads from the workspace by convention:

| Source | Path | Required |
|--------|------|----------|
| Progress file | `<base-path>/workflow/*_<ticket>.json` | Yes |
| Step result sidecars | `<base-path>/*/step-result.json` | Yes (at least one) |

## Execution

### 1. Parse arguments

Extract `TICKET` from `$1` and `BASE_PATH` from `--base-path`.

### 2. Read workflow state

Read the progress file from `<BASE_PATH>/workflow/`. Extract:

- `workflow_type`, `created_at`, `updated_at`
- `options` (format, draft, source, PR URLs)
- Per-step status and result data from `steps`

### 3. Read step sidecars

For each step with status `completed`, read its `step-result.json` from `<BASE_PATH>/<step-name>/step-result.json`. Collect key metrics:

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

- **Steps that iterated** — technical-review or quality-gate that ran more than once (iteration > 1). What caused the iteration?
- **Steps that were skipped** — why (condition not met, no source repo, user declined)
- **Steps that failed** — what went wrong
- **Patterns worth noting** — recurring review findings, markup issues, requirement gaps, domain knowledge that was missing
- **What went well** — high-confidence reviews, clean first-pass writing, smooth source resolution

### 5. Write review.md

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
    "technical_review": <iteration count or 0>,
    "quality_gate": <iteration count or 0>
  },
  "observation_count": <total bullet points in Observations>
}
```

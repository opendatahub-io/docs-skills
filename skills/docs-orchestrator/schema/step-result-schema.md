# Step Result Sidecar Schema

Workflow steps write a `step-result.json` file alongside their primary output. The orchestrator and downstream scripts use this sidecar to read structured metadata without parsing markdown.

## Common fields

All sidecars share these fields:

```json
{
  "schema_version": 1,
  "step": "<step-name>",
  "ticket": "<TICKET>",
  "completed_at": "<ISO 8601>"
}
```

| Field | Type | Description |
|---|---|---|
| `schema_version` | integer | Always `1`. Bump when the schema changes incompatibly |
| `step` | string | Step name matching the YAML step list (e.g., `"requirements"`) |
| `ticket` | string | JIRA ticket ID as provided by the user (preserves original case) |
| `completed_at` | string | ISO 8601 timestamp of when the step finished. **Must be obtained from** `datetime.now(timezone.utc).isoformat()` (Python) — do not estimate or round. Accurate timestamps are required for pipeline diagnostics duration calculations |

## Per-step schemas

Every `docs-workflow-*` skill must have both an input and output JSON Schema in its `schema/` directory.

### Output schemas (step-result.json)

Each step's output JSON Schema defines the sidecar contract:

| Step | Schema file |
|---|---|
| requirements | `skills/docs-workflow-requirements/schema/requirements.json` |
| scope-req-audit | `skills/docs-workflow-scope-req-audit/schema/scope-req-audit.json` |
| planning | `skills/docs-workflow-planning/schema/planning.json` |
| code-analysis | `skills/docs-workflow-code-analysis/schema/code-analysis.json` |
| pr-analysis | `skills/docs-workflow-pr-analysis/schema/pr-analysis.json` |
| writing | `skills/docs-workflow-writing/schema/writing.json` |
| technical-review | `skills/docs-workflow-tech-review/schema/technical-review.json` |
| style-review | `skills/docs-workflow-style-review/schema/style-review.json` |
| security-review | `skills/docs-workflow-security-review/schema/security-review.json` |
| create-merge-request | `skills/docs-workflow-create-merge-request/schema/create-merge-request.json` |
| create-jira | `skills/docs-workflow-create-jira/schema/create-jira.json` |
| quality-gate | `skills/docs-workflow-quality-gate/schema/quality-gate.json` |
| action-comments | `skills/action-comments/schema/action-comments.json` |
| pipeline-diagnostics | `skills/docs-workflow-pipeline-diagnostics/schema/pipeline-diagnostics.json` |
| jira-ready | `skills/docs-workflow-jira-ready/schema/jira-ready.json` |

### Input schemas (CLI args contract)

Each step's input JSON Schema defines what `build_step_args()` in the orchestrator produces:

| Step | Schema file |
|---|---|
| requirements | `skills/docs-workflow-requirements/schema/requirements-input.json` |
| code-analysis | `skills/docs-workflow-code-analysis/schema/code-analysis-input.json` |
| scope-req-audit | `skills/docs-workflow-scope-req-audit/schema/scope-req-audit-input.json` |
| pr-analysis | `skills/docs-workflow-pr-analysis/schema/pr-analysis-input.json` |
| planning | `skills/docs-workflow-planning/schema/planning-input.json` |
| writing | `skills/docs-workflow-writing/schema/writing-input.json` |
| technical-review | `skills/docs-workflow-tech-review/schema/technical-review-input.json` |
| style-review | `skills/docs-workflow-style-review/schema/style-review-input.json` |
| security-review | `skills/docs-workflow-security-review/schema/security-review-input.json` |
| quality-gate | `skills/docs-workflow-quality-gate/schema/quality-gate-input.json` |
| pipeline-diagnostics | `skills/docs-workflow-pipeline-diagnostics/schema/pipeline-diagnostics-input.json` |
| create-merge-request | `skills/docs-workflow-create-merge-request/schema/create-merge-request-input.json` |
| create-jira | `skills/docs-workflow-create-jira/schema/create-jira-input.json` |
| start | `skills/docs-workflow-start/schema/start-input.json` |
| jira-ready | `skills/docs-workflow-jira-ready/schema/jira-ready-input.json` |

## Backward compatibility

Downstream consumers use a sidecar-first pattern: read from `step-result.json` when present, fall back to parsing the markdown output when absent. This ensures in-flight workflows from before sidecar adoption continue to work.

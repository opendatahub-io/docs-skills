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
| requirements | `skills/docs-workflow-requirements/schema/requirements-output.json` |
| scope-req-audit | `skills/docs-workflow-scope-req-audit/schema/scope-req-audit-output.json` |
| planning | `skills/docs-workflow-planning/schema/planning-output.json` |
| code-analysis | `skills/docs-workflow-code-analysis/schema/code-analysis-output.json` |
| pr-analysis | `skills/docs-workflow-pr-analysis/schema/pr-analysis-output.json` |
| writing | `skills/docs-workflow-writing/schema/writing-output.json` |
| technical-review | `skills/docs-workflow-tech-review/schema/tech-review-output.json` |
| style-review | `skills/docs-workflow-style-review/schema/style-review-output.json` |
| security-review | `skills/docs-workflow-security-review/schema/security-review-output.json` |
| create-merge-request | `skills/docs-workflow-create-merge-request/schema/create-merge-request-output.json` |
| create-jira | `skills/docs-workflow-create-jira/schema/create-jira-output.json` |
| quality-gate | `skills/docs-workflow-quality-gate/schema/quality-gate-output.json` |
| action-comments | `skills/action-comments/schema/action-comments-output.json` |
| pipeline-diagnostics | `skills/docs-workflow-pipeline-diagnostics/schema/pipeline-diagnostics-output.json` |
| jira-ready | `skills/docs-workflow-jira-ready/schema/jira-ready-output.json` |

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
| technical-review | `skills/docs-workflow-tech-review/schema/tech-review-input.json` |
| style-review | `skills/docs-workflow-style-review/schema/style-review-input.json` |
| security-review | `skills/docs-workflow-security-review/schema/security-review-input.json` |
| quality-gate | `skills/docs-workflow-quality-gate/schema/quality-gate-input.json` |
| pipeline-diagnostics | `skills/docs-workflow-pipeline-diagnostics/schema/pipeline-diagnostics-input.json` |
| create-merge-request | `skills/docs-workflow-create-merge-request/schema/create-merge-request-input.json` |
| create-jira | `skills/docs-workflow-create-jira/schema/create-jira-input.json` |
| start | `skills/docs-workflow-start/schema/start-input.json` |
| jira-ready | `skills/docs-workflow-jira-ready/schema/jira-ready-input.json` |

## Schema conformance tests

`tests/test_schema_conformance.py` validates that all schemas and sidecars stay in sync. It uses `tests/schema_helpers.py` for schema discovery and validation. Tests run in CI via `make test`.

### What the tests cover

| Layer | What it checks |
|---|---|
| **Schema validity** | Every `.json` schema file parses as valid JSON Schema 2020-12. Output schemas require the four common fields (`schema_version`, `step`, `ticket`, `completed_at`). All schemas set `additionalProperties: false`. |
| **Golden examples** | A minimal valid sidecar dict per output schema and a minimal valid args dict per input schema are validated against their schemas. Catches regressions when a required field is added to a schema but producers aren't updated. |
| **Required-field rejection** | For each required field in every output schema, removes that field from the golden example and asserts validation fails. Proves schemas enforce their contracts. |
| **Extra-field rejection** | Adds an unexpected field to each golden example and asserts validation fails. Proves `additionalProperties: false` is working. |

### When to update the tests

- **Adding a new step**: add a golden output example to `GOLDEN_EXAMPLES` and a golden input example to `GOLDEN_INPUT_EXAMPLES` in `test_schema_conformance.py`. The discovery is automatic — the test will fail if a schema exists without a golden example.
- **Adding a required field to a schema**: update the step's golden example to include the new field. The required-field rejection test auto-discovers it.
- **Removing a field from a schema**: remove it from the golden example.

### Reusing validation in other tests

Import `validate_sidecar` from `schema_helpers` to validate sidecar dicts constructed in orchestrator tests:

```python
from schema_helpers import validate_sidecar

validate_sidecar("requirements", my_sidecar_dict)
```

## Backward compatibility

Downstream consumers use a sidecar-first pattern: read from `step-result.json` when present, fall back to parsing the markdown output when absent. This ensures in-flight workflows from before sidecar adoption continue to work.

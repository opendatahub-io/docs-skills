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
| `completed_at` | string | ISO 8601 timestamp of when the step finished. **Must be obtained from** `date -u +%Y-%m-%dT%H:%M:%SZ` — do not estimate or round. Accurate timestamps are required for pipeline diagnostics duration calculations |

## Per-step extensions

### requirements

```json
{
  "schema_version": 1,
  "step": "requirements",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T14:30:00Z",
  "title": "Add installation guide for the Operator",
  "requirement_count": 8
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `title` | string | First heading from requirements.md (max 80 chars, ticket prefix stripped) | `create_merge_request.sh` — PR/MR title |
| `requirement_count` | integer | Number of requirements discovered in pass 1 | Informational (orchestrator summary) |

### scope-req-audit

```json
{
  "schema_version": 1,
  "step": "scope-req-audit",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T14:35:00Z",
  "recommendation": "proceed",
  "grounded": 8,
  "partial": 2,
  "absent": 1,
  "total": 11,
  "discovered_repos_count": 2,
  "secondary_repos_count": 1
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `recommendation` | string | `"proceed"`, `"gather-more"`, or `"review-needed"` | Orchestrator — post-step logging |
| `grounded` | integer | Count of grounded requirements | Orchestrator — post-step logging |
| `partial` | integer | Count of partial requirements | Orchestrator — post-step logging |
| `absent` | integer | Count of absent requirements | Orchestrator — post-step logging |
| `total` | integer | Total requirements classified | Orchestrator — post-step logging |
| `discovered_repos_count` | integer | Count of repos found in README/docs | Orchestrator — post-step logging |
| `secondary_repos_count` | integer | Count of repos from gap classification actions | Orchestrator — post-step logging |

### planning

```json
{
  "schema_version": 1,
  "step": "planning",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T14:45:00Z",
  "module_count": 5
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `module_count` | integer | Number of documentation modules in the plan | Informational (orchestrator summary) |

### code-analysis

```json
{
  "schema_version": 1,
  "step": "code-analysis",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T14:40:00Z",
  "module_count": 12,
  "relationship_count": 8,
  "languages_detected": ["go", "python"],
  "repo_path": "/home/user/docs-repo/.agent_workspace/proj-123/code-repo/my-project"
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `module_count` | integer | Number of modules analyzed by learn-code | Informational (orchestrator summary) |
| `relationship_count` | integer | Number of cross-module relationships discovered | Informational (orchestrator summary) |
| `languages_detected` | string[] | Programming languages found in the repo | Informational |
| `repo_path` | string | Absolute path to the analyzed source repository | Informational |

### pr-analysis

```json
{
  "schema_version": 1,
  "step": "pr-analysis",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T14:50:00Z",
  "pr_number": 42,
  "pr_url": "https://github.com/org/repo/pull/42",
  "modules_affected": 3,
  "platform": "github"
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `pr_number` | integer | PR/MR number | Informational |
| `pr_url` | string | Full URL to the PR/MR | Informational |
| `modules_affected` | integer | Number of modules with changes in the PR | Informational (orchestrator summary) |
| `platform` | string | `"github"` or `"gitlab"` | Informational |

### writing

```json
{
  "schema_version": 1,
  "step": "writing",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T15:10:00Z",
  "files": [
    "/home/user/docs-repo/modules/proc-installing-operator.adoc",
    "/home/user/docs-repo/modules/con-operator-overview.adoc",
    "/home/user/docs-repo/assemblies/assembly-operator-guide.adoc"
  ],
  "mode": "update-in-place",
  "format": "adoc"
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `files` | string[] | Absolute paths of all files written or modified | `create_merge_request.sh` — file staging |
| `mode` | string | `"update-in-place"`, `"draft"`, or `"fix"` | Informational |
| `format` | string | `"adoc"` or `"mkdocs"` | Informational |

### technical-review

```json
{
  "schema_version": 1,
  "step": "technical-review",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T15:30:00Z",
  "confidence": "MEDIUM",
  "severity_counts": {
    "critical": 0,
    "significant": 0,
    "minor": 3,
    "sme": 2
  },
  "iteration": 1,
  "code_grounded": true
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `confidence` | string | `"HIGH"`, `"MEDIUM"`, or `"LOW"` | Orchestrator — iteration logic |
| `severity_counts` | object | Issue counts by severity level | Orchestrator — iteration logic |
| `severity_counts.critical` | integer | Critical issues found | Orchestrator |
| `severity_counts.significant` | integer | Significant issues found | Orchestrator |
| `severity_counts.minor` | integer | Minor issues found | Orchestrator |
| `severity_counts.sme` | integer | Issues requiring SME verification | Orchestrator |
| `iteration` | integer | Which iteration of review this represents (1-based) | Orchestrator |
| `code_grounded` | boolean | Whether code-learner analysis was available for claim validation (code-analysis step completed) | Informational |

### style-review

```json
{
  "schema_version": 1,
  "step": "style-review",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T15:45:00Z"
}
```

No extra fields. Common schema only.

### security-review

```json
{
  "schema_version": 1,
  "step": "security-review",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T15:50:00Z",
  "scanner_findings": 7,
  "critical_findings": 1,
  "agent_findings": 2,
  "categories": {
    "ip": 3,
    "email": 2,
    "credential": 1,
    "url": 1,
    "mac": 0,
    "internal_hostname": 0
  },
  "context_size_bytes": 4096
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `scanner_findings` | integer | Total findings from the deterministic PII scanner | Orchestrator — iteration logic |
| `critical_findings` | integer | Critical-severity findings (credentials, private keys) | Orchestrator — iteration logic |
| `agent_findings` | integer | Findings from the Layer 2 agent analysis checklist | Informational |
| `categories` | object | Finding counts by category | Informational |
| `context_size_bytes` | integer | Total bytes of step output files | Orchestrator — size logging |

### create-merge-request

```json
{
  "schema_version": 1,
  "step": "create-merge-request",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T16:05:00Z",
  "commit_sha": "abc1234",
  "branch": "proj-123",
  "pushed": true,
  "url": "https://github.com/org/repo/pull/42",
  "action": "created",
  "platform": "github",
  "skipped": false,
  "skip_reason": null
}
```

When skipped (draft mode, no changes, or user declined):

```json
{
  "schema_version": 1,
  "step": "create-merge-request",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T16:05:00Z",
  "commit_sha": null,
  "branch": null,
  "pushed": false,
  "url": null,
  "action": "skipped",
  "platform": "unknown",
  "skipped": true,
  "skip_reason": "draft"
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `commit_sha` | string\|null | Git commit SHA (null when skipped) | Informational |
| `branch` | string\|null | Branch name committed to (null when skipped) | Orchestrator |
| `pushed` | boolean | Whether the branch was pushed to the remote | Orchestrator |
| `url` | string\|null | MR/PR URL (null when skipped or not pushed) | Orchestrator (final summary) |
| `action` | string | `"created"`, `"found_existing"`, or `"skipped"` | Orchestrator |
| `platform` | string | `"github"`, `"gitlab"`, or `"unknown"` | Informational |
| `skipped` | boolean | Whether the step was skipped | Orchestrator |
| `skip_reason` | string\|null | `"draft"`, `"no_changes"`, `"no_files"`, `"user_declined"`, `"on_default_branch"`, `"push_failed"`, `"commit_failed"`, `"create_failed"`, or `"unknown_platform"` when skipped | Orchestrator |

### create-jira

```json
{
  "schema_version": 1,
  "step": "create-jira",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T16:10:00Z",
  "jira_url": "https://redhat.atlassian.net/browse/DOCS-456",
  "jira_key": "DOCS-456",
  "action": "created",
  "skipped": false,
  "skip_reason": null
}
```

When an existing linked ticket is found:

```json
{
  "schema_version": 1,
  "step": "create-jira",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T16:10:00Z",
  "jira_url": "https://redhat.atlassian.net/browse/DOCS-456",
  "jira_key": "DOCS-456",
  "action": "found_existing",
  "skipped": false,
  "skip_reason": null
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `jira_url` | string\|null | URL of the created or found JIRA ticket (null on failure) | Orchestrator (final summary) |
| `jira_key` | string\|null | JIRA issue key (e.g., `DOCS-456`) | Orchestrator |
| `action` | string | `"created"`, `"found_existing"`, or `"skipped"` | Orchestrator |
| `skipped` | boolean | Whether JIRA creation was skipped | Orchestrator |
| `skip_reason` | string\|null | Reason when skipped (e.g., `"existing_link"`) | Orchestrator |

### quality-gate

```json
{
  "schema_version": 1,
  "step": "quality-gate",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T15:50:00Z",
  "doc_quality": 4,
  "intent_alignment": 3,
  "passed": false,
  "iteration": 1,
  "evidence_expected": true,
  "evidence_warning": null,
  "coverage_check": {
    "total": 12,
    "covered": 9,
    "uncovered": 3
  },
  "gaps": [
    {
      "ac_item": "Document confidence scores",
      "judge": "intent_alignment",
      "evidence_status": "absent",
      "action": "document_as_unsupported",
      "file": "proc-deploying-model.adoc",
      "section": "After 'Verifying the deployment' — add a note about confidence scores"
    }
  ],
  "rationales": {
    "doc_quality": "Full judge rationale text...",
    "intent_alignment": "Full judge rationale text with per-acceptance-criteria coverage assessments..."
  }
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `doc_quality` | integer | Doc quality score (1-5) from Opus judge agent | Orchestrator — iteration logic |
| `intent_alignment` | integer | Intent alignment score (1-5) from Opus judge agent | Orchestrator — iteration logic |
| `passed` | boolean | Whether intent_alignment >= 4 (doc_quality is informational only) | Orchestrator — iteration logic |
| `iteration` | integer | Which iteration of the quality gate loop (1-based) | Orchestrator |
| `evidence_expected` | boolean | Whether scope-req-audit ran and evidence-status.json was expected | Pipeline diagnostics |
| `evidence_warning` | string\|null | Warning message when evidence was expected but not found; null otherwise | Pipeline diagnostics, orchestrator logging |
| `coverage_check` | object\|null | Per-AC quote-based coverage verification summary (null if no AC items found) | Quality gate iteration |
| `coverage_check.total` | integer | Total acceptance criteria checked | Informational |
| `coverage_check.covered` | integer | acceptance criteria items with verified quotes in the documentation | Quality gate iteration |
| `coverage_check.uncovered` | integer | acceptance criteria items not covered or with unverified quotes | Quality gate iteration |
| `gaps` | array | Identified gaps with evidence status and recommended action | Quality gate iteration — inline fix dispatch |
| `gaps[].ac_item` | string | The acceptance criteria item that was missed | Quality gate iteration |
| `gaps[].judge` | string | Which judge flagged the gap: `"intent_alignment"` or `"coverage_check"` | Informational |
| `gaps[].evidence_status` | string | Cross-referenced against scope-req-audit: `"grounded"`, `"partial"`, `"absent"`, or `"unknown"` | Quality gate iteration — determines fix strategy |
| `gaps[].action` | string | Recommended action: `"document_as_unsupported"`, `"expand_with_evidence"`, `"add_missing_section"`, or `"investigate"` | Quality gate iteration |
| `gaps[].file` | string\|null | AsciiDoc filename where the fix should be applied | Quality gate iteration — targeted file edits |
| `gaps[].section` | string\|null | Section heading or insertion point within the file | Quality gate iteration — targeted section edits |
| `rationales` | object | Full judge rationale texts for the feedback brief | Quality gate iteration |
| `rationales.doc_quality` | string | Complete doc_quality judge rationale | Quality gate iteration — included verbatim in feedback brief |
| `rationales.intent_alignment` | string | Complete intent_alignment judge rationale with per-acceptance-criteria coverage assessments, missing artifacts, scope analysis | Quality gate iteration — included verbatim in feedback brief |

### action-comments

Used by the standalone `action-comments` skill.

```json
{
  "schema_version": 1,
  "step": "action-comments",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T16:00:00Z",
  "ci_mode": true,
  "comments_resolved": 3,
  "comments_skipped": 2,
  "comments_outdated": 1,
  "comments_replied": 3,
  "files_modified": ["modules/proc-installing-operator.adoc"]
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `ci_mode` | boolean | Whether the skill ran in autonomous CI mode | Informational |
| `comments_resolved` | integer | Number of review comments applied or edited | Informational |
| `comments_skipped` | integer | Number of comments skipped by user (or autonomously in CI) | Informational |
| `comments_outdated` | integer | Number of comments auto-skipped as outdated | Informational |
| `comments_replied` | integer | Number of reply comments posted to the PR/MR (CI mode only, 0 in interactive) | Informational |
| `files_modified` | string[] | Paths of files modified | Informational |

### pipeline-diagnostics

```json
{
  "schema_version": 1,
  "step": "pipeline-diagnostics",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T16:15:00Z",
  "pipeline_status": "completed",
  "context_pressure_level": "moderate",
  "context_pressure_score": 4,
  "failure_count": 1,
  "high_severity_failure_count": 0,
  "bottleneck_count": 1,
  "orchestrator_issue_count": 2,
  "recommendation_count": 3,
  "total_duration_min": 25.3
}
```

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `pipeline_status` | string | Overall pipeline status from the progress file | Orchestrator (final summary) |
| `context_pressure_level` | string | `"low"`, `"moderate"`, `"high"`, or `"critical"` | Orchestrator (final summary) |
| `context_pressure_score` | integer | Numeric risk score from the diagnostics heuristic | Informational |
| `failure_count` | integer | Total failures detected across all steps | Orchestrator (final summary) |
| `high_severity_failure_count` | integer | High-severity failures only | Orchestrator (final summary) |
| `bottleneck_count` | integer | Number of steps flagged as bottlenecks | Informational |
| `orchestrator_issue_count` | integer | Number of orchestrator-level problems found by self-introspection | Informational |
| `recommendation_count` | integer | Number of actionable recommendations generated | Informational |
| `total_duration_min` | number | Total pipeline duration in minutes (from file mtimes) | Informational |

## Backward compatibility

Downstream consumers use a sidecar-first pattern: read from `step-result.json` when present, fall back to parsing the markdown output when absent. This ensures in-flight workflows from before sidecar adoption continue to work.

# Output Conventions and State Management

## Per-ticket source config schema

Writers can create `<base-path>/source.yaml` before starting a workflow to pre-configure the source repo and scope. The script also writes this file after a successful clone so that resume picks it up automatically.

```yaml
# .agent_workspace/<ticket>/source.yaml
repo: https://github.com/org/operator   # URL or local path (required)
ref: main                                # branch, tag, or commit (default: HEAD)
scope:
  include:                               # glob patterns — what to index and search
    - "src/controllers/**"
    - "pkg/api/v1/**"
    - "README.md"
  exclude:                               # glob patterns — what to skip
    - "**/vendor/**"
    - "**/testdata/**"
    - "**/*_test.go"
```

All fields except `repo` are optional. If `scope` is omitted, the entire repository is in scope.

## Output conventions

Every step writes to a predictable folder based on the ticket ID and step name:

```
.agent_workspace/<ticket>/<step-name>/
```

The ticket ID is converted to **lowercase** for directory names (e.g., `PROJ-123` → `proj-123`).

### Resolve base path

Resolve the base path to an absolute path so agents (which may run in a different working directory) can locate files correctly:

```bash
BASE_PATH="$(cd "$(git rev-parse --show-toplevel)" && pwd)/.agent_workspace/${TICKET_LOWER}"
```

Use this absolute `BASE_PATH` for the progress file's `base_path` field and for all `--base-path` arguments passed to step skills.

### Folder structure

```
.agent_workspace/proj-123/
  source.yaml                        (per-ticket source config, if applicable)
  code-repo/
    <repo-name>/                     (each repo gets its own subdirectory)
  requirements/
    requirements.md
    step-result.json                 (sidecar: title)
  code-analysis/                       (if source repo is available)
    ONBOARDING.md
    registry.json
    detection.json
    summaries/
    relationships/
    step-result.json                 (sidecar: module_count, relationship_count, languages_detected, repo_path)
  code-analysis-<repo-name>/           (additional repos, if any — same structure as code-analysis/)
    ONBOARDING.md
    registry.json
    detection.json
    summaries/
    relationships/
    step-result.json
  pr-analysis/                         (if PR is available)
    PR-<number>-ANALYSIS.md
    step-result.json                 (sidecar: pr_number, pr_url, modules_affected, platform)
  planning/
    plan.md
    step-result.json                 (sidecar: module_count)
  writing/
    _index.md
    step-result.json                 (sidecar: files, mode, format)
    assembly_*.adoc (or docs/*.md for mkdocs)
    modules/
  technical-review/
    review.md
    step-result.json                 (sidecar: confidence, severity_counts)
  style-review/
    review.md
    step-result.json                 (sidecar: common fields only)
  create-merge-request/
    step-result.json                 (sidecar: commit_sha, branch, pushed, url, action, platform, skipped)
  workflow/
    docs-workflow_proj-123.json
```

Each step skill knows its own output folder and writes there. Each step reads input from upstream step folders referenced in its `inputs` list. The orchestrator passes the base path `.agent_workspace/<ticket>/` — step skills derive everything else by convention.

### Step result sidecars

Every step that produces markdown output also writes a `step-result.json` sidecar with structured metadata. See [schema/step-result-schema.md](../schema/step-result-schema.md) for the full schema. Downstream scripts and the orchestrator prefer sidecar data when present, falling back to parsing the markdown output for backward compatibility.

## Progress file

Claude writes the progress file directly using the Write tool. Create it after parsing arguments, before step 1. Update it after each step. Also write the active workflow marker at the same time (see [Active workflow marker](#active-workflow-marker)).

**Location**: `.agent_workspace/<ticket>/workflow/<workflow-type>_<ticket>.json`

The `workflow_type` field and filename prefix match the YAML's `workflow.name`. This allows multiple workflow types to run against the same ticket without conflict.

### Schema

```json
{
  "workflow_type": "<workflow.name from YAML>",
  "ticket": "<TICKET>",
  "base_path": "/absolute/path/to/.agent_workspace/<ticket>",
  "status": "in_progress",
  "created_at": "<ISO 8601>",
  "updated_at": "<ISO 8601>",
  "options": {
    "format": "adoc",
    "draft": false,
    "create_merge_request": false,
    "pr_urls": [],
    "source": null,
    "additional_sources": [],
    "no_source_repo": false,
    "auto_discover_repos": false,
    "max_secondary_repos": 3
  },
  "step_order": ["requirements", "code-analysis", "pr-analysis", "planning", "writing", ...],
  "steps": {
    "<step-name>": {
      "status": "pending",
      "output": null,
      "result": null
    }
  }
}
```

The `output` field records the step's output folder path (e.g., `.agent_workspace/proj-123/writing/`) once completed.

The `result` field stores selected sidecar data after each step completes. This lets the orchestrator make downstream decisions and display summaries without re-reading sidecar files from disk — especially important on resume. Set to `null` until the step completes; then populated from `step-result.json` (see Step-specific post-processing in the main skill file).

### Status values

| Value | Meaning |
|---|---|
| `pending` | Not yet started |
| `in_progress` | Currently running |
| `completed` | Finished successfully |
| `failed` | Failed — needs retry |
| `skipped` | Conditional step not applicable |
| `deferred` | Waiting for upstream step to determine if condition is met |

### `step_order`

A top-level array listing steps in canonical order. This field exists so the Stop hook can determine step ordering without a hardcoded bash array. It **must** always be written by the orchestrator and kept in sync with the YAML step list.

## Active workflow marker

The active workflow marker tells the Stop hook which workflow (if any) is currently running in this session. Without the marker, the hook allows Claude to stop freely.

**Location**: `.agent_workspace/.active-workflow`

### When to write the marker

Write the marker file using the Write tool at the same time as creating or updating the progress file to `"in_progress"` — after parsing arguments, before step 1. If resuming an existing workflow, overwrite any existing marker.

### Schema

```json
{
  "ticket": "<TICKET>",
  "workflow_type": "<workflow.name from YAML>",
  "progress_file": ".agent_workspace/<ticket-lower>/workflow/<workflow-type>_<ticket-lower>.json"
}
```

The `progress_file` path must be relative to the project root (matching the path the hook uses to locate the file).

### When to delete the marker

Delete `.agent_workspace/.active-workflow` when:

1. The workflow completes — immediately after setting the progress file's `status` to `"completed"` in the Completion section
2. The workflow fails terminally — after setting `status` to `"failed"` (e.g., planning step produces 0 modules and user chooses to stop)

Do **not** delete the marker between steps. The marker must persist for the entire duration of the workflow so the Stop hook can block premature stops.

### Overwriting on resume or new workflow

If the user starts a new workflow (different ticket or different workflow type) or resumes an existing one, overwrite the marker with the new workflow's information. There is only ever one active workflow at a time. The previous marker is implicitly superseded.

### Edge cases

- **No marker exists**: The Stop hook allows Claude to stop. This is the correct default for sessions that don't involve a workflow.
- **Marker points to a missing progress file**: The Stop hook cleans up the stale marker and allows stop.
- **Marker exists but workflow status is `"completed"` or `"failed"`**: The Stop hook cleans up the marker and allows stop.

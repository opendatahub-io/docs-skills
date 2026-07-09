---
name: docs-workflow-scope-req-audit
description: Classify JIRA requirements by code evidence status before planning. Uses learn-code analysis data and source code inspection to determine if each requirement is grounded, partial, or absent. Fans out one subagent per requirement for isolated classification. Prevents hallucinated documentation for unimplemented features and surfaces gaps for implemented ones. Conditional on has_source_repo.
argument-hint: <ticket> --base-path <path> --repo <path>
allowed-tools: Read, Write, Glob, Grep, Bash, Agent, Skill
---

# Scope Requirements Audit Step

Step skill for the docs-orchestrator pipeline. Follows the step skill contract: **parse args → fan out → merge → write output**.

This skill classifies each JIRA requirement from the requirements step as grounded, partial, or absent by dispatching one subagent per requirement. Each subagent receives learn-code analysis context (module registry, summaries, onboarding guide) and can inspect the actual source code with Read/Grep/Glob. The planning step then uses these classifications to scope documentation modules — grounded requirements get full specs, partial ones are flagged for SME review, and absent ones are deferred to prevent documenting unimplemented features.

## Arguments

- `$1` — JIRA ticket ID (required)
- `--base-path <path>` — Base output path (e.g., `.agent_workspace/proj-123`)
- `--repo <path>` — Path to the source code repository (required, provided by orchestrator)

## Input

```text
<base-path>/requirements/requirements.md
<repo-path>/
```

## Output

```text
<base-path>/scope-req-audit/evidence-status.json
<base-path>/scope-req-audit/summary.md
<base-path>/scope-req-audit/step-result.json
```

## Execution

### 1. Parse arguments and validate inputs

Extract the ticket ID, `--base-path`, and `--repo` from the args string.

Set the paths:

```bash
REQUIREMENTS_FILE="${BASE_PATH}/requirements/requirements.md"
OUTPUT_DIR="${BASE_PATH}/scope-req-audit"
EVIDENCE_STATUS_FILE="${OUTPUT_DIR}/evidence-status.json"
SUMMARY_FILE="${OUTPUT_DIR}/summary.md"
mkdir -p "$OUTPUT_DIR"
```

Validate:
- Verify `--repo` was provided. If not, STOP with error: "scope-req-audit requires --repo. The orchestrator should provide the repo path."
- Verify `$REQUIREMENTS_FILE` exists. If not, STOP with error: "Requirements step must complete before scope-req-audit."
- Verify the repo path exists and is a directory. If not, STOP with error: "Repo path does not exist: `<path>`."


### 2. Discover related repos

Scan the source repo's top-level markdown files for GitHub and GitLab repository URLs that are not the current repo. This provides context for recommended actions when requirements are absent.

Files to scan:
- `README.md`, `README.rst`, `README`
- `CONTRIBUTING.md`
- `docs/*.md` (one level only)

For each file, extract URLs matching:
- `https://github.com/<org>/<repo>` (GitHub)
- `https://gitlab.<host>/<path>` (GitLab)

Filter out:
- The current repo URL (discover the remote with `git -C "$REPO_PATH" remote -v` — which reads the repo without changing the shell's working directory — and use the first available remote's URL). Normalize before comparing: strip trailing `.git`, convert `git@<host>:<org>/<repo>` SSH URLs to `https://<host>/<org>/<repo>` form
- Duplicate URLs (after normalization)
- URLs that are clearly not repos (e.g., GitHub issue links, badge URLs)

Store the results as a list of `discovered_repos` entries, each with:
- `url` — the repository URL
- `source` — the file and approximate location where it was found (e.g., `README.md`)
- `relevance` — a brief note on why it might be relevant (e.g., "Python SDK referenced in project README")

### 3. Parse requirements

Read `$REQUIREMENTS_FILE` and extract each requirement. The requirements-analyst produces requirements in this pattern:

```
### REQ-NNN: [title]

**Summary**: [description]
```

For each requirement, extract:
- `id` — the REQ-NNN identifier
- `title` — the requirement title
- `summary` — the summary text

If no requirements are found matching this pattern, STOP with error: "No requirements found in requirements.md. Expected REQ-NNN pattern."

### 4. Pre-flight: resolve and load learn-code analysis data

Resolve and load the structured code analysis produced by learn-code. This data provides module-level understanding of the codebase that classifiers use alongside direct source inspection.

#### 4a. Resolve analysis location

Derive the repo name and check for existing analysis:

```bash
REPO_NAME="$(basename "$REPO_PATH")"
# Derive the docs-repo root from BASE_PATH (<docs-root>/.agent_workspace/<ticket>)
# by stripping from `.agent_workspace` onward. Do NOT use `git rev-parse`, which
# returns whichever repo the cwd is inside and points at the wrong root if the
# agent drifted into the source repo.
GIT_ROOT="${BASE_PATH%%/.agent_workspace/*}"
ANALYSIS_PATH="${GIT_ROOT}/.agent_workspace/${REPO_NAME}"
```

Check for existing analysis at `${ANALYSIS_PATH}/synthesis/ONBOARDING.md`.

**If it does not exist:**

Check if `${ANALYSIS_PATH}/workflow/` contains a progress file with `status: "in_progress"`.

- If a progress file exists with in-progress status: report that a learn-code analysis is incomplete and offer to resume it.
- If no progress file exists or analysis directory does not exist: run learn-code:

```
Skill: learn-code, args: "${REPO_PATH}"
```

Wait for it to complete. If it fails, STOP with error including the failure details.

After learn-code completes (or if analysis already existed), verify `${ANALYSIS_PATH}/synthesis/ONBOARDING.md` exists. If not, STOP with error: "learn-code analysis failed to produce ONBOARDING.md at `${ANALYSIS_PATH}/synthesis/ONBOARDING.md`."

#### 4b. Verify analysis files and record paths

Verify that the expected analysis files exist at `${ANALYSIS_PATH}/`. Do **not** read their contents into context — agents read them directly from disk.

Check these files:

| File | Required |
|------|----------|
| `detection/detection.json` | Yes |
| `module-registry/registry.json` | Yes |
| `module-analysis/summary.json` | Yes |
| `relationships/relationships.json` | No (may not exist for small repos) |
| `synthesis/ONBOARDING.md` | Yes (verified in 4a) |

For each missing required file (other than ONBOARDING.md, already verified in 4a), log a warning but continue — agents handle missing data gracefully. For missing optional files, log a note.

Write the discovered repos list from step 2 to a shared file so agents can read it from disk instead of receiving it inline:

```bash
# Write to disk — agents read from DISCOVERED_REPOS_FILE
cat > "${OUTPUT_DIR}/discovered-repos.json" << 'JSONEOF'
<JSON array of discovered_repos from step 2, or [] if none>
JSONEOF
```

Record `ANALYSIS_PATH` for use in agent prompts. Do not read or assemble any analysis file contents.

### 5. Fan out: dispatch one agent per requirement

For each requirement extracted in step 3, dispatch one Agent call. Launch ALL requirement agents in a **single message** (parallel execution).

Each agent reads analysis data from disk and writes its result to `<OUTPUT_DIR>/evidence-<NNN>.json`. Where `<NNN>` is the zero-padded requirement number extracted from the REQ-NNN id (e.g., REQ-001 produces evidence-001.json).

See [agent prompts](references/agent-prompts.md#fan-out-classifier-prompt) for the full classifier prompt template.

**Important:** All Agent calls MUST be in a single message so they run in parallel. Do not dispatch them sequentially.

### 6. Collect results from disk

After all agents complete, verify that the expected per-requirement JSON files were written to disk.

```bash
EXPECTED_COUNT=<number of requirements from step 3>
ACTUAL_COUNT=$(ls ${OUTPUT_DIR}/evidence-*.json 2>/dev/null | wc -l)
echo "Evidence files: ${ACTUAL_COUNT}/${EXPECTED_COUNT}"
```

**HARD GATE — do NOT proceed to step 7 (merge) until `ACTUAL_COUNT` equals `EXPECTED_COUNT`.** If any agents are still running, wait for them to complete. After all agents have returned, if files are still missing:

1. Identify which REQ IDs have no corresponding `evidence-<NNN>.json`
2. Log: `"Missing evidence files for: REQ-003, REQ-007"` (list actual missing IDs)
3. The merge agent (step 7) will create fallback entries for missing files — proceed to step 7 only after confirming the missing IDs

### 7. Assemble output via merge agent

Delegate the assembly of `evidence-status.json` and `summary.md` to a merge subagent. This keeps the full classification data (~20-50KB) out of the orchestrator's context.

See [agent prompts](references/agent-prompts.md#merge-agent-prompt) for the full merge agent prompt template.

### 8. Verify merge output

Verify that `$EVIDENCE_STATUS_FILE` and `$SUMMARY_FILE` were written by the merge agent:

```bash
test -f "$EVIDENCE_STATUS_FILE" && test -f "$SUMMARY_FILE" && echo "OK" || echo "MISSING"
```

If either file is missing, treat it as a step failure.

The sidecar script in step 10 reads evidence-status.json directly, so no inline extraction is needed.

### 9. Extract secondary repo references

After writing evidence-status.json, run the secondary repo extraction script to identify repos referenced in gap classification actions:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/docs-workflow-scope-req-audit/scripts/extract_secondary_repos.py \
  --evidence-status "$EVIDENCE_STATUS_FILE" \
  --primary-repo "$REPO_PATH" \
  --fetch-pr-paths \
  --max-repos 3
```

The script parses `recommended_action` fields from partial/absent requirements, extracts GitHub/GitLab repo URLs, groups requirements by target repo, and optionally fetches PR file paths to derive `suggested_scope` directories.

Read the JSON array output and merge it into `evidence-status.json` as a `secondary_repos` field:

```json
{
  "secondary_repos": [
    {
      "url": "https://github.com/org/companion-repo",
      "source": "gap_classification",
      "requirements": ["REQ-002", "REQ-004"],
      "pr_refs": ["#262", "#317"],
      "priority": "secondary",
      "suggested_scope": ["pkg/controller/", "pkg/mutator/"]
    }
  ]
}
```

If the script returns an empty array, set `secondary_repos: []` in evidence-status.json. The field must always be present so downstream consumers (orchestrator, planning) can check it without guarding against missing keys.

Also update `summary.md` to include a "Secondary Repos (from gap analysis)" section if any were found:

```markdown
## Secondary Repos (from gap analysis)

- [https://github.com/org/companion-repo](https://github.com/org/companion-repo) — REQ-002, REQ-004 (3 PRs, scope: pkg/controller/, pkg/mutator/)
```

### 10. Write step-result.json

Do **not** hand-author the sidecar — a hand-written sidecar drifts from the schema and uses an
orchestrator-delayed timestamp instead of a real wall-clock one. Run the script:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/write_step_result.py \
  --ticket "<TICKET>" \
  --evidence-status "$EVIDENCE_STATUS_FILE" \
  --sidecar "${OUTPUT_DIR}/step-result.json"
```

The script reads evidence-status.json to extract recommendation, summary counts,
discovered_repos length, and secondary_repos length. It writes the conformant `step-result.json`
with a real wall-clock `completed_at`. If the script exits non-zero, fix the arguments and re-run;
do not substitute a stub.

### 11. Verify output

Verify that `$EVIDENCE_STATUS_FILE`, `$SUMMARY_FILE`, and `${OUTPUT_DIR}/step-result.json` exist.

## How downstream steps use the output

The **planning step** checks for `<base-path>/scope-req-audit/evidence-status.json`. If it exists, the planner uses evidence status when scoping modules:

- **Grounded** requirements get full module specifications
- **Partial** requirements get module specifications with a gap note flagging SME review
- **Absent** requirements are listed in a "Deferred requirements (no code evidence)" section — no module specs are created for them

If `evidence-status.json` does not exist (step was skipped or not configured), the planning step works exactly as before — all requirements are included. This preserves composability.

## Notes

- **Fanout pattern:** Each requirement is classified by an independent subagent with a clean context window. This prevents context degradation when processing many requirements — classification quality for REQ-015 is identical to REQ-001
- **Disk-based data flow:** Agents write their JSON classifications to per-requirement files (`evidence-NNN.json`) on disk instead of returning them to the orchestrator context. The merge agent reads from disk to assemble `evidence-status.json` and `summary.md`. This prevents 15+ agent results and ~300KB of analysis context from accumulating in the orchestrator's context window
- **Compact prompts:** Agent prompts reference `ANALYSIS_PATH` by path instead of embedding the full analysis JSON. Each agent reads analysis files directly from disk. This reduces per-agent prompt size from ~200KB to ~0.3KB
- **Learn-code analysis:** Analysis data is produced by learn-code and cached at `.agent_workspace/<repo-name>/`. If analysis already exists from a prior run, it is reused. The first workflow run for a repo pays the analysis cost; subsequent runs skip it. Analysis files are referenced by path in agent prompts — never read into the orchestrator context
- **Source inspection:** Subagents inspect actual source files using Read/Grep/Glob. The learn-code analysis provides a structural map (modules, APIs, relationships) that guides where to look, but the final classification is based on direct evidence in the source code
- **Parallel execution:** All subagent Agent calls are dispatched in a single message for parallel execution. The orchestrator waits for all to complete before merging
- **Error isolation:** A failed subagent does not affect other requirements — the merge agent creates a fallback entry with `"status": "absent"` and an `"error"` field for diagnostics
- This step queries the primary source repo only. The `secondary_repos` output enables the orchestrator to clone and index companion repos if needed
- `discovered_repos` (step 2) surfaces repos found in README/docs. `secondary_repos` (step 9) surfaces repos referenced in gap classification actions — these are more targeted because they're tied to specific absent/partial requirements

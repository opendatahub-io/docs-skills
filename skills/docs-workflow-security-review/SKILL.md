---
name: docs-workflow-security-review
description: Security and PII scan of documentation drafts before publication. Runs the deterministic PII scanner, then applies the docs-review-security checklist for agent-based analysis. Iteration logic is owned by the orchestrator, not this skill.
argument-hint: <ticket> --base-path <path>
allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Skill, Agent
---

# Security Review Step

Step skill for the docs-orchestrator pipeline. Follows the step skill contract: **parse args → run scanner → apply checklist → write output**.

## Arguments

- `$1` — JIRA ticket ID (required)
- `--base-path <path>` — Base output path (e.g., `.agent_workspace/proj-123`)

## Input

```
<base-path>/writing/
```

## Output

```
<base-path>/security-review/review.md
<base-path>/security-review/scanner-results.json
<base-path>/security-review/step-result.json
```

## Execution

### 1. Parse arguments

Extract the ticket ID and `--base-path` from the args string.

Set the paths:

```bash
OUTPUT_DIR="${BASE_PATH}/security-review"
OUTPUT_FILE="${OUTPUT_DIR}/review.md"
SCANNER_FILE="${OUTPUT_DIR}/scanner-results.json"
mkdir -p "$OUTPUT_DIR"
```

### 2. Determine source files

Read the writing step's sidecar at `${BASE_PATH}/writing/step-result.json` to determine the writing mode and file list.

**If the sidecar exists and `mode` is `"update-in-place"` with a non-empty `files` array:**

Build a file list from the `files` array.

**Otherwise** (draft mode, missing sidecar, or empty files array):

Set `DRAFTS_DIR="${BASE_PATH}/writing"` and glob for `.adoc`, `.md`, `.dita`, and `.ditamap` files.

### 3. Run PII scanner

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/docs-review-security/scripts/pii_scanner.py scan <file1> <file2> ... > "$SCANNER_FILE"
```

Check the exit code. If the scanner failed (non-zero exit), write an error to the report and exit with a non-zero status:

```bash
if [ $? -ne 0 ]; then
  echo "ERROR: PII scanner failed. See output above." >&2
  exit 1
fi
```

Validate the JSON output is well-formed before parsing:

```bash
jq empty "$SCANNER_FILE" 2>/dev/null
if [ $? -ne 0 ]; then
  echo "ERROR: Scanner produced invalid JSON output." >&2
  exit 1
fi
```

Read and parse the JSON output. Note the total findings count and whether any are `critical`.

### 4. Build report header

Start the review report with the scanner results:

```markdown
# Security and PII Review — <TICKET>

## Automated scan results

**Scanner findings:** N total (C critical, W warnings)

[If findings > 0, list them grouped by severity]

## Agent analysis

[Apply the checklist from step 5 and add findings here]
```

### 5. Dispatch the security-reviewer agent (Layer 2)

**You MUST use the Agent tool** to invoke the `security-reviewer` subagent. Do NOT read the checklist or apply it yourself — the agent reads the source files and the Layer 2 checklist in its own isolated context and appends findings directly to the report, so neither the doc content nor the checklist enters the orchestrator's context.

**Agent tool parameters:**
- `subagent_type`: `docs-skills:security-reviewer`
- `description`: `Security Layer 2 review for <TICKET>`

**Prompt** (substitute `<SOURCE_FILES>` with the file list from step 2 and `<OUTPUT_FILE>` with the report path):

> Apply the Layer 2 agent-analysis checklist to the documentation for ticket `<TICKET>`.
>
> **Source files** — review each of these:
> <SOURCE_FILES>
>
> **Report file**: `<OUTPUT_FILE>` — this file already contains the report header and scanner results. Append your findings to its **Agent analysis** section by editing it in place. Do NOT overwrite the existing content and do NOT write to any other location.
>
> After appending all findings, do NOT print the report contents. Print ONLY these two lines:
>
> ```
> Written <OUTPUT_FILE>
> Agent findings: N
> ```

### 6. Verify output

After the agent completes, verify the review report exists at `<OUTPUT_FILE>`.

### 7. Write step-result.json

Parse the scanner results from `$SCANNER_FILE` to extract counts.

Write the sidecar to `${OUTPUT_DIR}/step-result.json`:

```json
{
  "schema_version": 1,
  "step": "security-review",
  "ticket": "<TICKET>",
  "completed_at": "<current ISO 8601 timestamp>",
  "scanner_findings": 0,
  "critical_findings": 0,
  "agent_findings": 0,
  "categories": {
    "ip": 0,
    "email": 0,
    "credential": 0,
    "url": 0,
    "mac": 0,
    "internal_hostname": 0
  },
  "context_size_bytes": 0
}
```

Replace the `0` placeholders with actual counts: scanner counts come from `$SCANNER_FILE`, and `agent_findings` comes from the `Agent findings: N` line the security-reviewer agent printed (do not read the full report back to recount). All numeric fields must be integers, not strings.

After writing the sidecar, sum the byte sizes of all output files in the step's output folder and add `context_size_bytes` to the sidecar.

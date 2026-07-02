---
name: docs-workflow-quality-gate
description: Score documentation quality and intent alignment using LLM judge agents (Opus). Dispatches two judge agents in parallel (doc_quality, intent_alignment), extracts specific gaps from AC coverage analysis, and cross-references against scope-req-audit evidence. Produces pass/fail gate with actionable gap list. Iteration logic is owned by the orchestrator, not this skill.
argument-hint: <ticket> --base-path <path>
allowed-tools: Read, Write, Bash, Glob, Grep, Agent
---

# Quality Gate

Score the pipeline's documentation output before creating a merge request. This skill dispatches two judge agents in parallel — one for doc_quality, one for intent_alignment — using the same model as the eval harness (Opus). The agents return structured JSON via schema validation.

The quality gate produces a pass/fail verdict and, when intent alignment is below threshold, a structured list of gaps with recommended actions and a feedback brief (`feedback-brief.md`) ready for the orchestrator to dispatch the writer in fix mode.

## Arguments

- `$1` — Ticket ID (required, e.g., `RHAIENG-2620`)
- `--base-path <path>` — Base output path (required, e.g., `.agent_workspace/rhaieng-2620`)

## Inputs

Reads from upstream steps by convention:

| Source | Path | Required |
|--------|------|----------|
| Writing output | `<base-path>/writing/step-result.json` | Yes — files array lists AsciiDoc paths |
| Requirements context | `<base-path>/requirements/discovery.json` | Yes — ticket summary and AC items |
| Evidence status | `<base-path>/scope-req-audit/evidence-status.json` or `<base-path>/validate/evidence-status.json` | No — used to classify gaps by code evidence |

## Execution

### 1. Parse arguments

Extract `TICKET` from `$1` and `BASE_PATH` from `--base-path`.

### 2. Prepare judge prompts

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py prepare \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}"
```

This reads the writing output and ticket context, then writes two prompt files:
- `${BASE_PATH}/quality-gate/dq-prompt.md` — doc_quality judge prompt with doc content interpolated
- `${BASE_PATH}/quality-gate/ia-prompt.md` — intent_alignment judge prompt with doc content and ticket context interpolated

### 3. Per-AC coverage verification

Per-AC coverage check before the judge agents. Each AC item gets its own subagent with only that one AC item and the full documentation — no other ACs, no judge context.

#### 3a. Prepare coverage check prompts

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py verify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --prepare
```

This reads `discovery.json` and the documentation content, then writes one prompt file per AC item to `${BASE_PATH}/quality-gate/coverage-prompts/` and a manifest to `${BASE_PATH}/quality-gate/coverage-prompts/manifest.json`.

If the manifest `items` array is empty (no AC items found), skip steps 3b and 3c.

#### 3b. Dispatch coverage check agents

Read the manifest JSON output from 3a. For each item in the `items` array, dispatch one agent. Launch **all agents in a single message** (parallel execution).

Each agent:

- **Model**: (default — not Opus; these are simple yes/no+quote tasks)
- **Prompt**: Read the contents of the item's `prompt_file` and follow the instructions
- **Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "covered": {"type": "boolean", "description": "Whether the documentation addresses this acceptance criterion"},
      "quote": {"type": ["string", "null"], "description": "Verbatim supporting sentence from the documentation, or null if not covered"}
    },
    "required": ["covered", "quote"]
  }
  ```

After **all** agents return, write each agent's structured JSON output to the corresponding `result_file` path from the manifest. Schema-validated agents return their JSON inline (not to disk), so the orchestrator must write the results:

```bash
mkdir -p "${BASE_PATH}/quality-gate/coverage-results"
```

For each item, write a JSON file containing the agent's `{"covered": ..., "quote": ...}` output to the item's `result_file`. Use a single bash command with heredocs to write all files at once, keeping context lean.

Verify the expected number of files were written:

```bash
ls "${BASE_PATH}/quality-gate/coverage-results/" | wc -l
```

If the count does not match the manifest item count, log a warning listing which items are missing.

#### 3c. Classify coverage results

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py verify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --classify
```

Validates quotes against the documentation (whitespace-normalized substring match), joins to scope-req-audit evidence status, and writes `${BASE_PATH}/quality-gate/coverage-check.json`.

Classifications:
- `covered` — AC is addressed with a verified quote. No action needed.
- `real_defect` — AC is not in the documentation but code evidence exists (grounded or partial). Fix it.
- `correctly_absent` — AC is not in the documentation and code evidence is absent. Document as unsupported.
- `unverified` — Agent claimed coverage but the quote was not found in the document. Investigate.
- `investigate` — AC is not covered and evidence status is unknown.

### 4. Dispatch judge agents

Dispatch **two agents in parallel** (both are independent reads of the same docs):

#### doc_quality agent

- **Model**: opus
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/dq-prompt.md` and use it as the agent prompt
- **Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "score": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Quality score 1-5"},
      "rationale": {"type": "string", "description": "Detailed rationale for the score"}
    },
    "required": ["score", "rationale"]
  }
  ```

#### intent_alignment agent

- **Model**: opus
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/ia-prompt.md` and use it as the agent prompt
- **Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "score": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Intent alignment score 1-5"},
      "rationale": {"type": "string", "description": "Detailed rationale including per-AC-item coverage assessments"},
      "missed_items": {
        "type": "array",
        "description": "AC items not adequately covered, with location for targeted fixes",
        "items": {
          "type": "object",
          "properties": {
            "ac_item": {"type": "string", "description": "The acceptance criteria item text"},
            "severity": {"type": "string", "enum": ["missing", "incomplete"], "description": "Whether the item is entirely missing or partially covered"},
            "file": {"type": "string", "description": "AsciiDoc filename where the fix should be applied (e.g., proc-deploying-model.adoc)"},
            "section": {"type": "string", "description": "Section heading or location within the file where content should be added or expanded. For new sections, describe where to insert relative to existing sections"}
          },
          "required": ["ac_item", "severity", "file", "section"]
        }
      }
    },
    "required": ["score", "rationale", "missed_items"]
  }
  ```

### 5. Write judge results

After both agents return, write their structured outputs to `${BASE_PATH}/quality-gate/judge-results.json`:

```json
{
  "doc_quality": { "score": <N>, "rationale": "<text>" },
  "intent_alignment": { "score": <N>, "rationale": "<text>", "missed_items": [...] }
}
```

### 6. Classify gaps and write step-result.json

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py classify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --judge-results "${BASE_PATH}/quality-gate/judge-results.json"
```

The script:
1. Reads the judge results from the JSON file
2. Reads `coverage-check.json` if it exists (from step 3c) and merges coverage defects into the gaps array, deduplicating by AC text (coverage check classification takes precedence)
3. Cross-references `missed_items` against evidence status to classify each gap:
   - `absent` → `document_as_unsupported` (add "not supported in this release" note)
   - `partial` → `expand_with_evidence` (expand with available code evidence)
   - `grounded` → `add_missing_section` (writing step missed it — re-include from plan)
   - `unknown` → `investigate` (evidence status unavailable)
3. Writes `quality-gate/step-result.json` and `quality-gate/judge-results.md`
4. Outputs the step-result JSON to stdout

### 7. Build feedback brief (when `passed = false`)

If `passed` is false, build `${BASE_PATH}/quality-gate/feedback-brief-<iteration>.md` (e.g., `feedback-brief-1.md`) so the orchestrator can dispatch the writer in fix mode. Read the `iteration` value from the step-result.json written in step 6. Skip this step if `passed` is true.

```markdown
# Feedback Brief for <TICKET> (iteration <N>)

## Intent Alignment Judge Assessment

[Insert rationales.intent_alignment from step-result.json verbatim.
This contains per-AC-item coverage assessments with severity levels, specific missing
artifacts, scope balance analysis, and audience alignment — all directly actionable.]

## Doc Quality Judge Assessment

[Insert rationales.doc_quality from step-result.json verbatim.]

## Coverage Check Results

[If coverage-check.json exists, read it from ${BASE_PATH}/quality-gate/coverage-check.json:]

AC coverage: <covered>/<total> acceptance criteria addressed with verified quotes.

### Uncovered AC Items

[For each item in coverage_check.items where classification != "covered":]

- **<ac_text>** (from <req_id>)
  - Classification: <classification>
  - Evidence status: <evidence_status>
  - Action: <action description>

[Map classification to fix instructions — same mappings as step 3c plus:]
- `unverified` → "Quote could not be verified in the document. Review whether this criterion is actually addressed."

[If coverage-check.json does not exist, omit this section.]

## Classified Gaps with Recommended Actions

[For each gap in the gaps array:]

### Gap: <ac_item>
- **File**: <file>
- **Section**: <section>
- **Evidence status**: <evidence_status>
- **Action**: <action description>

[Map action codes to instructions:]
- `document_as_unsupported` → "Add a note stating that this capability is not supported in this release. Place it in the most relevant existing module — do not create a new module."
- `expand_with_evidence` → "Expand the existing content with available code evidence. Check the source repo for relevant API fields, flags, or config options."
- `add_missing_section` → "This content was in the plan but was not included in the writing output. Add the missing section based on the requirements and plan."
- `investigate` → "This gap could not be classified. Review the requirements and determine whether to document it or note it as out of scope."

## Prior attempts

[If iteration > 1:]
This is iteration <N>. A previous fix pass was attempted but did not resolve these gaps.
The writer must try a DIFFERENT approach — do not repeat the same fix. Consider:
- Adding more concrete detail (specific API fields, config values, command examples)
- Restructuring the section rather than appending
- Checking source code for evidence that was missed in the first attempt

[If iteration == 1, omit this section.]

## Priority

Address gaps in this order:
1. Items the judge flagged as "missing" or "barely covered" — these are the largest scoring deductions
2. Items flagged as "weakly covered" or "partially covered" — expand existing content
3. Scope rebalancing — if the judge flagged over-indexing on one area, tighten that section rather than expanding others
```

Include the **full judge rationale text**, not just the classified gap list. The rationale contains per-AC-item severity assessments ("partially covered", "weakly covered", "barely covered", "mostly missing"), names specific missing artifacts, identifies scope imbalance, and diagnoses audience gaps. This gives the fix agent precise, nuanced instructions instead of flat action codes.

### 8. Verify output (always runs)

Read `${BASE_PATH}/quality-gate/step-result.json` and verify it contains:
- `doc_quality` (integer 1-5)
- `intent_alignment` (integer 1-5)
- `passed` (boolean)
- `gaps` (array)

If the file is missing or malformed, report the error.

### 9. Report results

Report the scores and pass/fail status:
- "Quality gate: doc_quality=N/5, intent_alignment=N/5, passed=true/false, gaps=N"
- If coverage check ran: "Coverage: N/M AC items addressed with verified quotes"
- If gaps exist, list each gap's `ac_item`, `judge`, and `action`

## Output

### coverage-check.json

```json
{
  "total": 12,
  "covered": 9,
  "uncovered": 3,
  "items": [
    {
      "id": "REQ-001_AC00",
      "req_id": "REQ-001",
      "ac_index": 0,
      "ac_text": "Users can configure custom CA bundles following the procedure",
      "covered": true,
      "quote": "To configure a custom CA bundle, set the `ca_bundle_path` parameter.",
      "quote_verified": true,
      "evidence_status": "grounded",
      "classification": "covered",
      "action": null
    }
  ]
}
```

### step-result.json

```json
{
  "schema_version": 1,
  "step": "quality-gate",
  "ticket": "PROJ-123",
  "completed_at": "2026-06-11T16:00:00+00:00",
  "doc_quality": 5,
  "intent_alignment": 4,
  "passed": false,
  "iteration": 1,
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
    "intent_alignment": "Full judge rationale text with per-AC coverage assessments..."
  }
}
```

### judge-results.md

Human-readable summary with rationales from both judges and the gap list.

### coverage-prompts/ and coverage-results/

Per-AC prompt files (`coverage-prompts/<id>.md`), manifest (`coverage-prompts/manifest.json`), and agent results (`coverage-results/<id>.json`). Written by the coverage verification step (step 3).

### `feedback-brief-<iteration>.md` (when `passed = false`)

Structured feedback document containing full judge rationales and classified gaps with fix instructions. Iteration-numbered (e.g., `feedback-brief-1.md`, `feedback-brief-2.md`) so prior briefs are preserved for debugging. Iteration 2+ briefs include a "Prior attempts" section instructing the writer to try a different approach. Consumed by the orchestrator's quality gate iteration loop via `docs-workflow-writing --fix-from`.

## Thresholds

- `intent_alignment >= 4` → `passed = true`
- `doc_quality` is reported but does **not** trigger a fix pass. If `doc_quality < 4`, the orchestrator logs a warning ("manual review recommended") but proceeds. Only intent_alignment gaps — specific missed AC items — are actionable via targeted rewrites
- When `passed = false`, this skill produces `feedback-brief-<iteration>.md` alongside the sidecar. The orchestrator dispatches the writer in fix mode with this file, or accepts with warning after max iterations

## Model

Judge agents use Opus to match the eval harness judge configuration. The model is specified via the Agent tool's `model` parameter — no separate API key or credentials required.

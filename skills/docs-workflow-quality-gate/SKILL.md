---
name: docs-workflow-quality-gate
description: Score documentation quality and intent alignment using LLM judge agents. Dispatches two judge agents in parallel (doc_quality, intent_alignment), extracts specific gaps from acceptance criteria coverage analysis, and cross-references against scope-req-audit evidence. Produces pass/fail gate with actionable gap list. Iteration logic is owned by the orchestrator, not this skill.
argument-hint: <ticket> --base-path <path>
allowed-tools: Read, Write, Bash, Glob, Grep, Agent
---

# Quality Gate

Score the pipeline's documentation output before creating a merge request. This skill dispatches two judge agents in parallel — one for doc_quality, one for intent_alignment. The agents return structured JSON via schema validation.

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
| Evidence status | `<base-path>/scope-req-audit/evidence-status.json` or `<base-path>/validate/evidence-status.json` | No — used to classify gaps by code evidence. When scope-req-audit ran but the file is missing, the gate warns and records `evidence_warning` in the sidecar |

## Execution

### 1. Parse arguments

Extract `TICKET` from `$1` and `BASE_PATH` from `--base-path`.

### 2. Prepare judge prompts

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py prepare \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}"
```

This reads the writing output and ticket context, then writes two prompt files and reports where each judge must write its result. The prompt files already instruct each judge to write its result JSON to the path below and to print only a confirmation — so the (large) rationale never enters the orchestrator's context. The script's JSON output includes:
- `dq_prompt` / `ia_prompt` — judge prompt file paths
- `dq_result` (`${BASE_PATH}/quality-gate/dq-result.json`) / `ia_result` (`${BASE_PATH}/quality-gate/ia-result.json`) — where each judge writes its structured result

### 3. Per-acceptance-criteria coverage verification

Per-acceptance-criteria coverage check before the judge agents. Each acceptance criteria item gets its own subagent with only that one item and the full documentation — no other acceptance criteria, no judge context.

#### 3a. Prepare coverage check prompts

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py verify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --prepare
```

This reads `discovery.json` and the documentation content, then writes one prompt file per acceptance criteria item to `${BASE_PATH}/quality-gate/coverage-prompts/` and a manifest to `${BASE_PATH}/quality-gate/coverage-prompts/manifest.json`.

If the manifest `items` array is empty (no acceptance criteria items found), skip steps 3b and 3c.

#### 3b. Dispatch coverage check agents

Read the manifest from the file at `${BASE_PATH}/quality-gate/coverage-prompts/manifest.json` using the Read tool (do NOT parse from stdout — stdout may truncate or serialize incorrectly). Extract the `items` array. For each item, dispatch one agent. Launch **all agents in a single message** (parallel execution).

**Use the Agent tool — not the Workflow tool.** Each coverage result must map back to a specific manifest item so its output can be written to that item's `result_file` (step 3b, below). The Agent tool preserves that one-dispatch-to-one-result association directly. The Workflow tool's journal keys entries by hash rather than by item label, so mapping journal entries back to manifest items is unreliable and has caused repeated extraction failures — do not use it here. Dispatch one Agent per item, all in a single message.

Each agent:

- **Model**: (default — not Opus; these are simple yes/no+quote tasks)
- **Prompt**: Read the contents of the item's `prompt_file` and follow the instructions
- **Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "covered": {"type": "boolean", "description": "Whether the documentation addresses this acceptance criteria item"},
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

Determine whether code evidence was expected: check if `${BASE_PATH}/scope-req-audit/` or `${BASE_PATH}/validate/` exists as a directory. If either exists, add `--evidence-expected` to the command.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py verify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --classify \
  [--evidence-expected]
```

Validates quotes against the documentation (whitespace-normalized substring match), joins to scope-req-audit evidence status, and writes `${BASE_PATH}/quality-gate/coverage-check.json`.

Classifications:
- `covered` — acceptance criteria item is addressed with a verified quote. No action needed.
- `real_defect` — acceptance criteria item is not in the documentation but code evidence exists (grounded or partial). Fix it.
- `correctly_absent` — acceptance criteria item is not in the documentation and code evidence is absent. Document as unsupported.
- `unverified` — Agent claimed coverage but the quote was not found in the document. Investigate.
- `investigate` — acceptance criteria item is not covered and evidence status is unknown.

### 4. Dispatch judge agents

Dispatch **two agents in parallel** (both are independent reads of the same docs). Each judge writes its own result file to disk and returns only a two-line confirmation (`Written <path>` + `score=<N>`) — do **not** request schema output, and do **not** read the result files back here.

#### doc_quality agent

- **Model**: opus
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/dq-prompt.md` and use it as the agent prompt. The prompt directs the agent to write `{score, rationale}` to `dq_result` and print only the confirmation.

#### intent_alignment agent

- **Model**: opus
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/ia-prompt.md` and use it as the agent prompt. The prompt directs the agent to write `{score, rationale, missed_items}` to `ia_result` and print only the confirmation.

### 5. Verify judge result files

Confirm both `dq_result` and `ia_result` files exist on disk before classifying. If either is missing, the corresponding judge failed — report the error and stop. Do not read their contents into context; the classify script reads and validates them.

### 6. Classify gaps and write outputs

Determine whether code evidence was expected: check if `${BASE_PATH}/scope-req-audit/` or `${BASE_PATH}/validate/` exists as a directory. If either exists, add `--evidence-expected` to the command.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py classify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --judge-results "${BASE_PATH}/quality-gate/judge-results.json" \
  [--evidence-expected]
```

The script reads `dq-result.json` and `ia-result.json` from `${BASE_PATH}/quality-gate/` by default (override with `--dq-result`/`--ia-result`). It:
1. Reads and validates both judge result files (fails loudly on a missing or malformed result)
2. Reads `coverage-check.json` if it exists (from step 3c) and merges coverage defects into the gaps array, deduplicating by acceptance criteria text (coverage check classification takes precedence)
3. Cross-references `missed_items` against evidence status to classify each gap:
   - `absent` → `document_as_unsupported` (add "not supported in this release" note)
   - `partial` → `expand_with_evidence` (expand with available code evidence)
   - `grounded` → `add_missing_section` (writing step missed it — re-include from plan)
   - `unknown` → `investigate` (evidence status unavailable)
3. Writes `quality-gate/judge-results.json` (assembled artifact), `quality-gate/step-result.json`, and `quality-gate/judge-results.md`
4. When `passed` is false, also writes `quality-gate/feedback-brief-<iteration>.md` (see step 6)
5. Outputs the step-result JSON to stdout

The iteration number is determined automatically from the briefs already on disk (first run → `1`, after one fix pass → `2`), so the brief and sidecar match the orchestrator's `feedback-brief-<iteration>.md` reference without an extra argument. Override with `--iteration <N>` only if you need to force a value.

### 7. Feedback brief (when `passed = false`)

When `passed` is false, render the feedback brief with the script — do NOT hand-render the template. It reads `step-result.json` (rationales and classified gaps) and `coverage-check.json` (if present) and writes `feedback-brief-<iteration>.md`:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py brief \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --iteration <N>
```

Use the `iteration` value from the step-result.json written in step 6. Skip this step when `passed` is true.

The rendered brief includes the **full judge rationales verbatim** (per-AC severity assessments, missing artifacts, scope and audience analysis — nuanced fix instructions, not flat action codes), the coverage block with per-item fix instructions (only when `coverage-check.json` exists), each classified gap with its action instruction, a "Prior attempts" section for iteration > 1 that tells the writer to try a different approach, and the priority ordering.

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
- If `evidence_warning` is not null: "WARNING: <evidence_warning>"
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

### judge-results.md

Human-readable summary with rationales from both judges and the gap list.

### coverage-prompts/ and coverage-results/

Per-acceptance-criteria prompt files (`coverage-prompts/<id>.md`), manifest (`coverage-prompts/manifest.json`), and agent results (`coverage-results/<id>.json`). Written by the coverage verification step (step 3).

### `feedback-brief-<iteration>.md` (when `passed = false`)

Structured feedback document containing full judge rationales and classified gaps with fix instructions. Iteration-numbered (e.g., `feedback-brief-1.md`, `feedback-brief-2.md`) so prior briefs are preserved for debugging. Iteration 2+ briefs include a "Prior attempts" section instructing the writer to try a different approach. Consumed by the orchestrator's quality gate iteration loop via `docs-workflow-writing --fix-from`.

## Thresholds

- `intent_alignment >= 4` → `passed = true`
- `doc_quality` is reported but does **not** trigger a fix pass. If `doc_quality < 4`, the orchestrator logs a warning ("manual review recommended") but proceeds. Only intent_alignment gaps — specific missed acceptance criteria items — are actionable via targeted rewrites
- When `passed = false`, this skill produces `feedback-brief-<iteration>.md` alongside the sidecar. The orchestrator dispatches the writer in fix mode with this file, or accepts with warning after max iterations

## Model

Judge agents use Opus. The model is specified via the Agent tool's `model` parameter — no separate API key or credentials required.

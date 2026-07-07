---
name: docs-workflow-quality-gate
description: Score documentation quality and intent alignment using LLM judge agents (Opus). Dispatches two judge agents in parallel (doc_quality, intent_alignment), extracts specific gaps from AC coverage analysis, and cross-references against scope-req-audit evidence. Produces pass/fail gate with actionable gap list. Iteration logic is owned by the orchestrator, not this skill.
argument-hint: <ticket> --base-path <path>
allowed-tools: Read, Write, Bash, Glob, Grep, Agent
---

# Quality Gate

Score the pipeline's documentation output before creating a merge request. This skill dispatches two judge agents in parallel — one for doc_quality, one for intent_alignment — using the same model as the eval harness (Opus). Each agent returns a JSON object in a fenced code block, which the `extract-json` script pulls out and validates against the step's schema.

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

This reads the writing output and ticket context, then writes two prompt files:
- `${BASE_PATH}/quality-gate/dq-prompt.md` — doc_quality judge prompt with doc content interpolated
- `${BASE_PATH}/quality-gate/ia-prompt.md` — intent_alignment judge prompt with doc content and ticket context interpolated

### 3. AC coverage verification

A quote-based coverage check before the judge agents. **One agent** reads the documentation once and answers a coverage question for every AC item — do not dispatch one agent per AC item. Embedding the full documentation in 39 separate per-AC prompts was the dominant context and artifact-bloat problem; a single combined prompt reads the docs once.

#### 3a. Prepare the combined coverage prompt

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py verify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --prepare
```

This reads `discovery.json` and the documentation content, then writes a **single combined prompt** — the documentation embedded once, every AC item listed with its id — to `${BASE_PATH}/quality-gate/coverage-prompt.md`, plus a manifest to `${BASE_PATH}/quality-gate/coverage-manifest.json`. It prints a one-line summary.

If the summary reports `0 AC items`, skip steps 3b and 3c.

#### 3b. Dispatch a single coverage agent

Dispatch **one** agent (a single Agent-tool call). Because there is one prompt and one result, there is no per-item mapping problem and nothing to fan out — the script maps results back to AC items by id.

- **Model**: opus — match the judges. The cheap model produced literal-minded false negatives (e.g. reading "subsection" or "automatically detect" too narrowly), and with a single combined prompt the docs are read once, so the cost argument for a cheaper model no longer applies
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/coverage-prompt.md` and follow the instructions. The prompt requires the agent to output a JSON object matching `schema/coverage.json` inside a single ` ```json ` fenced code block.

The Agent tool has no schema-enforced output, so the agent returns prose wrapping the JSON. Write the agent's reply **verbatim** to `${BASE_PATH}/quality-gate/coverage-raw.md`, then extract and validate the `items` array with the script:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py extract-json \
  --raw "${BASE_PATH}/quality-gate/coverage-raw.md" \
  --schema "${CLAUDE_SKILL_DIR}/schema/coverage.json" \
  --out "${BASE_PATH}/quality-gate/coverage-results.json" \
  --key items
```

If the script exits non-zero (no JSON found, or schema mismatch), **re-dispatch the coverage agent once** with a reminder to output only a valid JSON object in a ` ```json ` fence, then re-run the script. The classify step (3c) reports any AC ids missing from the array; you do not need to count files by hand.

#### 3c. Classify coverage results

Determine whether code evidence was expected: check if `${BASE_PATH}/scope-req-audit/` or `${BASE_PATH}/validate/` exists as a directory. If either exists, add `--evidence-expected` to the command.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py verify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --classify \
  [--evidence-expected]
```

Reads `coverage-results.json`, validates quotes against the documentation (whitespace-normalized substring match), joins to scope-req-audit evidence status, and writes `${BASE_PATH}/quality-gate/coverage-check.json`. It prints only a `total=… covered=… uncovered=…` summary and warns (on stderr) if any AC item had no agent result.

Classifications:
- `covered` — AC is addressed with a verified quote. No action needed.
- `real_defect` — AC is not in the documentation but code evidence exists (grounded or partial). Fix it.
- `correctly_absent` — AC is not in the documentation and code evidence is absent. Document as unsupported.
- `unverified` — Agent claimed coverage but the quote was not found in the document. Investigate.
- `investigate` — AC is not covered and evidence status is unknown.

### 4. Dispatch judge agents

Dispatch **both agents in a single message** so they run in parallel. These are independent reads of the same docs — there is no dependency between them. **Do NOT dispatch them in separate messages** — sequential dispatch adds unnecessary latency and has caused ~65s delays in observed runs.

Each judge prompt requires the agent to output a JSON object matching its schema inside a single ` ```json ` fenced code block. The Agent tool has no schema-enforced output, so extract and validate each reply with the `extract-json` script (step 5) rather than trusting the raw text.

#### doc_quality agent

- **Model**: opus
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/dq-prompt.md` and follow the instructions exactly.
- **Output schema**: `${CLAUDE_SKILL_DIR}/schema/doc-quality.json`

#### intent_alignment agent

- **Model**: opus
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/ia-prompt.md` and follow the instructions exactly.
- **Output schema**: `${CLAUDE_SKILL_DIR}/schema/intent-alignment.json`

### 5. Extract and validate judge results

Write each agent's reply **verbatim** to a raw file, then extract + validate it against its schema:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py extract-json \
  --raw "${BASE_PATH}/quality-gate/dq-raw.md" \
  --schema "${CLAUDE_SKILL_DIR}/schema/doc-quality.json" \
  --out "${BASE_PATH}/quality-gate/dq-result.json"

python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py extract-json \
  --raw "${BASE_PATH}/quality-gate/ia-raw.md" \
  --schema "${CLAUDE_SKILL_DIR}/schema/intent-alignment.json" \
  --out "${BASE_PATH}/quality-gate/ia-result.json"
```

If either script call exits non-zero (no JSON found, or schema mismatch), **re-dispatch that judge agent once** with a reminder to output only a valid JSON object in a ` ```json ` fence, then re-run the script. If an agent produces no usable result after the retry, mark the quality gate as `failed` — do not substitute default scores.

### 6. Classify gaps and write step-result.json

Determine the iteration number: if `--iteration N` was provided in the step arguments, use N. Otherwise, this is iteration 1.

Determine whether code evidence was expected: check if `${BASE_PATH}/scope-req-audit/` or `${BASE_PATH}/validate/` exists as a directory. If either exists, add `--evidence-expected` to the command.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py classify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --doc-quality "${BASE_PATH}/quality-gate/dq-result.json" \
  --intent-alignment "${BASE_PATH}/quality-gate/ia-result.json" \
  --iteration <N> \
  [--evidence-expected]
```

The script:
1. Reads the two judge result files (or a combined `--judge-results` file)
2. Reads `coverage-check.json` if it exists (from step 3c) and merges coverage defects into the gaps array, deduplicating by AC text (coverage check classification takes precedence)
3. Cross-references `missed_items` against evidence status to classify each gap:
   - `absent` → `document_as_unsupported` (add "not supported in this release" note)
   - `partial` → `expand_with_evidence` (expand with available code evidence)
   - `grounded` → `add_missing_section` (writing step missed it — re-include from plan)
   - `unknown` → `investigate` (evidence status unavailable)
3. Writes `quality-gate/step-result.json` and `quality-gate/judge-results.md`
4. Prints a one-line summary (`doc_quality=… intent_alignment=… passed=… gaps=…`); the full sidecar is on disk

### 7. Build feedback brief (when `passed = false`)

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
    "intent_alignment": "Full judge rationale text with per-AC coverage assessments..."
  }
}
```

### judge-results.md

Human-readable summary with rationales from both judges and the gap list.

### coverage-prompt.md, coverage-manifest.json, coverage-results.json

The single combined coverage prompt (docs embedded once + all AC items), the manifest mapping AC ids to their text, and the coverage agent's JSON array output. Written by the coverage verification step (step 3).

### `feedback-brief-<iteration>.md` (when `passed = false`)

Structured feedback document containing full judge rationales and classified gaps with fix instructions. Iteration-numbered (e.g., `feedback-brief-1.md`, `feedback-brief-2.md`) so prior briefs are preserved for debugging. Iteration 2+ briefs include a "Prior attempts" section instructing the writer to try a different approach. Consumed by the orchestrator's quality gate iteration loop via `docs-workflow-writing --fix-from`.

## Thresholds

- `intent_alignment >= 4` → `passed = true`
- `doc_quality` is reported but does **not** trigger a fix pass. If `doc_quality < 4`, the orchestrator logs a warning ("manual review recommended") but proceeds. Only intent_alignment gaps — specific missed AC items — are actionable via targeted rewrites
- When `passed = false`, this skill produces `feedback-brief-<iteration>.md` alongside the sidecar. The orchestrator dispatches the writer in fix mode with this file, or accepts with warning after max iterations

## Model

Judge agents use Opus to match the eval harness judge configuration. The coverage agent (step 3b) also uses Opus — running coverage on a cheaper model than the judges produced false negatives when the two disagreed. The model is specified via the Agent tool's `model` parameter — no separate API key or credentials required.

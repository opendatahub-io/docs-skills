---
name: docs-workflow-quality-gate
description: Score documentation intent alignment against the JIRA ticket and verify per-acceptance-criteria coverage with quote-grounded subagents. Dispatches one intent_alignment judge plus one coverage subagent per acceptance criterion, cross-references gaps against scope-req-audit evidence, and gates on coverage (every acceptance criterion must be covered or correctly documented as unsupported). Produces a pass/fail gate with an actionable gap list. Iteration logic is owned by the orchestrator, not this skill.
argument-hint: <ticket> --base-path <path>
allowed-tools: Read, Write, Bash, Glob, Grep, Agent
---

# Quality Gate

Score the pipeline's documentation output before creating a merge request. The gate has two parts: a per-acceptance-criteria coverage check (one quote-grounded subagent per criterion) that is the **authoritative pass/fail signal**, and a single `intent_alignment` judge that supplies a holistic score plus a narrative rationale (scope match, audience fit, focus) for the feedback brief.

The gate passes only when every acceptance criterion is either **covered** (a verified supporting quote exists in the docs) or **correctly absent** (no code evidence exists, so it is documented as unsupported). When it fails, the skill writes a structured list of gaps with recommended actions and a feedback brief (`feedback-brief-<iteration>.md`) ready for the orchestrator to dispatch the writer in fix mode.

> **Note:** The `doc_quality` judge was removed. Structural and technical correctness — fabricated commands, modular-doc structure, style — are already covered by the `technical-review` and `style-review` steps. The quality gate now focuses solely on requirements coverage and intent, the dimension those steps do not assess.

## Arguments

- `$1` — Ticket ID (required, e.g., `RHAIENG-2620`)
- `--base-path <path>` — Base output path (required, e.g., `.agent_workspace/rhaieng-2620`)

## Inputs

Reads from upstream steps by convention:

| Source | Path | Required |
|--------|------|----------|
| Writing output | `<base-path>/writing/step-result.json` | Yes — files array lists AsciiDoc paths |
| Requirements context | `<base-path>/requirements/discovery.json` | Yes — ticket summary and acceptance criteria items |
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

This reads the writing output and ticket context, then writes the intent_alignment prompt file and reports where the judge must write its result. The prompt file already instructs the judge to write its result JSON to the path below and to print only a confirmation — so the (large) rationale never enters the orchestrator's context. The script's JSON output includes:
- `ia_prompt` — judge prompt file path
- `ia_result` (`${BASE_PATH}/quality-gate/ia-result.json`) — where the judge writes its structured result

### 3. Per-acceptance-criteria coverage verification

This is the gate's authoritative signal and is **mandatory** whenever the ticket has acceptance criteria. Each acceptance criteria item gets its own subagent with only that one item and the full documentation — no other acceptance criteria, no judge context. The classify step (step 6) **fails loudly** if acceptance criteria exist but `coverage-check.json` is missing, so steps 3a–3c must not be skipped. Only skip this step when there are no acceptance criteria at all (3a reports an empty `items` array).

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

Read the manifest JSON output from 3a. For each item in the `items` array, dispatch one agent. Launch **all agents in a single message** (parallel execution).

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

Write each agent's JSON output to the item's `result_file` path from the manifest.

#### 3c. Classify coverage results

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py verify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --classify
```

Validates quotes against the documentation (whitespace-normalized substring match), joins to scope-req-audit evidence status, and writes `${BASE_PATH}/quality-gate/coverage-check.json`.

Classifications:
- `covered` — acceptance criteria item is addressed with a verified quote. No action needed.
- `real_defect` — acceptance criteria item is not in the documentation but code evidence exists (grounded or partial). Fix it.
- `correctly_absent` — acceptance criteria item is not in the documentation and code evidence is absent. Document as unsupported.
- `unverified` — Agent claimed coverage but the quote was not found in the document. Investigate.
- `investigate` — acceptance criteria item is not covered and evidence status is unknown.

### 4. Dispatch the intent_alignment judge

Dispatch **one agent**. It writes its result file to disk and returns only a two-line confirmation (`Written <path>` + `score=<N>`) — do **not** request schema output, and do **not** read the result file back here.

#### intent_alignment agent

- **Model**: opus
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/ia-prompt.md` and use it as the agent prompt. The prompt directs the agent to write `{score, rationale, missed_items}` to `ia_result` and print only the confirmation.

### 5. Verify the judge result file

Confirm the `ia_result` file exists on disk before classifying. If it is missing, the judge failed — report the error and stop. Do not read its contents into context; the classify script reads and validates it.

### 6. Classify gaps and write outputs

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py classify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}"
```

The script reads `ia-result.json` from `${BASE_PATH}/quality-gate/` by default (override with `--ia-result`). It:
1. Reads and validates the intent_alignment judge result (fails loudly on a missing or malformed result)
2. Reads `coverage-check.json` (from step 3c). If acceptance criteria exist but the file is missing, **fails loudly** — coverage is mandatory. Merges coverage defects into the gaps array, deduplicating by acceptance criteria text (coverage check classification takes precedence)
3. Cross-references the judge's `missed_items` against evidence status, recovering the requirement id from the `REQ-NNN:` prefix, to classify each remaining gap:
   - `absent` → `document_as_unsupported` (add "not supported in this release" note)
   - `partial` → `expand_with_evidence` (expand with available code evidence)
   - `grounded` → `add_missing_section` (writing step missed it — re-include from plan)
   - `unknown` → `investigate` (evidence status unavailable)
4. Computes the verdict: when coverage ran, `passed` is true only if **every** acceptance criterion is `covered` or `correctly_absent`; with no acceptance criteria, falls back to `intent_alignment >= 4`
5. Writes `quality-gate/judge-results.json` (assembled artifact), `quality-gate/step-result.json`, and `quality-gate/judge-results.md`
6. When `passed` is false, also writes `quality-gate/feedback-brief-<iteration>.md` (see step 7)
7. Outputs the step-result JSON to stdout

The iteration number is determined automatically from the briefs already on disk (first run → `1`, after one fix pass → `2`), so the brief and sidecar match the orchestrator's `feedback-brief-<iteration>.md` reference without an extra argument. Override with `--iteration <N>` only if you need to force a value.

### 7. Feedback brief (when `passed = false`)

When `passed` is false, the `classify` script (step 6) writes `${BASE_PATH}/quality-gate/feedback-brief-<iteration>.md` so the orchestrator can dispatch the writer in fix mode. The brief is assembled deterministically by the script — it embeds the **full judge rationale text** (per-acceptance-criteria severity assessments, named missing artifacts, scope imbalance, audience gaps), the classified gaps with action-code instructions, a "Prior attempts" section when iteration > 1, and a priority ordering. None of that text enters the orchestrator's context.

Verify the brief exists when `passed` is false; do not read it back into context. The orchestrator passes it to the writer via `docs-workflow-writing --fix-from`.

### 8. Verify output (always runs)

Read `${BASE_PATH}/quality-gate/step-result.json` and verify it contains:
- `intent_alignment` (integer 1-5)
- `passed` (boolean)
- `gaps` (array)

If the file is missing or malformed, report the error.

### 9. Report results

Report the score and pass/fail status:
- "Quality gate: intent_alignment=N/5, passed=true/false, gaps=N"
- If coverage check ran: "Coverage: N/M acceptance criteria items addressed with verified quotes"
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
    "intent_alignment": "Full judge rationale text with per-acceptance-criteria coverage assessments..."
  }
}
```

### judge-results.md

Human-readable summary with the intent_alignment judge rationale and the gap list.

### coverage-prompts/ and coverage-results/

Per-acceptance-criteria prompt files (`coverage-prompts/<id>.md`), manifest (`coverage-prompts/manifest.json`), and agent results (`coverage-results/<id>.json`). Written by the coverage verification step (step 3).

### `feedback-brief-<iteration>.md` (when `passed = false`)

Structured feedback document containing full judge rationales and classified gaps with fix instructions. Iteration-numbered (e.g., `feedback-brief-1.md`, `feedback-brief-2.md`) so prior briefs are preserved for debugging. Iteration 2+ briefs include a "Prior attempts" section instructing the writer to try a different approach. Consumed by the orchestrator's quality gate iteration loop via `docs-workflow-writing --fix-from`.

## Thresholds

- **Coverage gate (authoritative)**: `passed = true` only when every acceptance criterion is `covered` (a verified quote exists) or `correctly_absent` (no code evidence — documented as unsupported). Any `real_defect`, `unverified`, or `investigate` item fails the gate.
- **Fallback**: when the ticket has no acceptance criteria, there is nothing to verify, so the gate falls back to `intent_alignment >= 4`.
- `intent_alignment` is always reported and its rationale drives the feedback brief, but its score is not the gate when coverage ran.
- When `passed = false`, this skill produces `feedback-brief-<iteration>.md` alongside the sidecar. The orchestrator dispatches the writer in fix mode with this file, or accepts with warning after max iterations.

## Model

The intent_alignment judge uses Opus. The per-acceptance-criteria coverage subagents use the default model (simple yes/no + quote tasks). The model is specified via the Agent tool's `model` parameter — no separate API key or credentials required.

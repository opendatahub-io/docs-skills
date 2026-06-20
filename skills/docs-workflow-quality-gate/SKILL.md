---
name: docs-workflow-quality-gate
description: Score documentation quality and intent alignment using LLM judge agents (Opus). Dispatches two judge agents in parallel (doc_quality, intent_alignment), extracts specific gaps from AC coverage analysis, and cross-references against scope-req-audit evidence. Produces pass/fail gate with actionable gap list. Iteration logic is owned by the orchestrator, not this skill.
argument-hint: <ticket> --base-path <path>
allowed-tools: Read, Write, Bash, Glob, Grep, Agent
---

# Quality Gate

Score the pipeline's documentation output before creating a merge request. This skill dispatches two judge agents in parallel — one for doc_quality, one for intent_alignment — using the same model as the eval harness (Opus). The agents return structured JSON via schema validation.

The quality gate produces a pass/fail verdict and, when intent alignment is below threshold, a structured list of gaps with recommended actions. The orchestrator uses these gaps to build a feedback brief and dispatch the writer in fix mode inline.

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

### 3. Dispatch judge agents

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

### 4. Write judge results

After both agents return, write their structured outputs to `${BASE_PATH}/quality-gate/judge-results.json`:

```json
{
  "doc_quality": { "score": <N>, "rationale": "<text>" },
  "intent_alignment": { "score": <N>, "rationale": "<text>", "missed_items": [...] }
}
```

### 5. Classify gaps and write step-result.json

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py classify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --judge-results "${BASE_PATH}/quality-gate/judge-results.json"
```

The script:
1. Reads the judge results from the JSON file
2. Cross-references `missed_items` against evidence status to classify each gap:
   - `absent` → `document_as_unsupported` (add "not supported in this release" note)
   - `partial` → `expand_with_evidence` (expand with available code evidence)
   - `grounded` → `add_missing_section` (writing step missed it — re-include from plan)
   - `unknown` → `investigate` (evidence status unavailable)
3. Writes `quality-gate/step-result.json` and `quality-gate/judge-results.md`
4. Outputs the step-result JSON to stdout

### 6. Verify output

Read `${BASE_PATH}/quality-gate/step-result.json` and verify it contains:
- `doc_quality` (integer 1-5)
- `intent_alignment` (integer 1-5)
- `passed` (boolean)
- `gaps` (array)

If the file is missing or malformed, report the error.

### 7. Report results

Report the scores and pass/fail status:
- "Quality gate: doc_quality=N/5, intent_alignment=N/5, passed=true/false, gaps=N"
- If gaps exist, list each gap's `ac_item` and `action`

## Output

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

## Thresholds

- `intent_alignment >= 4` → `passed = true`
- `doc_quality` is reported but does **not** trigger a fix pass. If `doc_quality < 4`, the orchestrator logs a warning ("manual review recommended") but proceeds. Only intent_alignment gaps — specific missed AC items — are actionable via targeted rewrites
- The orchestrator decides what to do when `passed = false` (build a feedback brief and dispatch the writer in fix mode, or accept with warning after max iterations)

## Model

Judge agents use Opus to match the eval harness judge configuration. The model is specified via the Agent tool's `model` parameter — no separate API key or credentials required.

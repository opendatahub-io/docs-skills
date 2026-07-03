---
name: docs-workflow-quality-gate
description: Score documentation intent alignment using an LLM judge agent (Opus) and classify coverage gaps with inline code-evidence checking. Dispatches one coverage agent and one intent_alignment judge. When scope-req-audit did not run, classifies gaps via module registry lookup + grep. Produces pass/fail gate with actionable gap list. Iteration logic is owned by the orchestrator, not this skill.
argument-hint: <ticket> --base-path <path>
allowed-tools: Read, Write, Bash, Glob, Grep, Agent
---

# Quality Gate

Score the pipeline's documentation output before creating a merge request. This skill dispatches one coverage agent (per-AC quote verification) and one intent_alignment judge agent. When `--repo` is provided and no `evidence-status.json` exists from a prior scope-req-audit run, the classify step performs an inline code-evidence check using the learn-code module registry and grep fallback — no separate scope-req-audit step required.

The quality gate produces a pass/fail verdict and, when intent alignment is below threshold, a structured list of gaps with recommended actions and a feedback brief (`feedback-brief.md`) ready for the orchestrator to dispatch the writer in fix mode.

## Arguments

- `$1` — Ticket ID (required, e.g., `RHAIENG-2620`)
- `--base-path <path>` — Base output path (required, e.g., `.agent_workspace/rhaieng-2620`)
- `--repo <path>` — Source code repository path (optional). When provided and no `evidence-status.json` exists, enables inline code-evidence checking via learn-code module registry + grep fallback. Passed through to the `verify --classify` and `classify` subcommands

## Inputs

Reads from upstream steps by convention:

| Source | Path | Required |
|--------|------|----------|
| Writing output | `<base-path>/writing/step-result.json` | Yes — files array lists AsciiDoc paths |
| Requirements context | `<base-path>/requirements/discovery.json` | Yes — ticket summary and AC items |
| Code analysis | `<base-path>/code-analysis/step-result.json` | No — provides `repo_analysis_path` for inline evidence check |
| Evidence status | `<base-path>/scope-req-audit/evidence-status.json` or `<base-path>/validate/evidence-status.json` | No — used when scope-req-audit ran (opt-in). When absent and `--repo` is provided, inline evidence check runs instead |

## Execution

### 1. Parse arguments

Extract `TICKET` from `$1` and `BASE_PATH` from `--base-path`.

### 2. Prepare judge prompt

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py prepare \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}"
```

This reads the writing output and ticket context, then writes:
- `${BASE_PATH}/quality-gate/ia-prompt.md` — intent_alignment judge prompt with doc content and ticket context interpolated

It also writes `dq-prompt.md` (doc_quality) but this prompt is not used in the default flow. The doc_quality judge is skipped unless explicitly requested.

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
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/coverage-prompt.md` and follow the instructions
- **Returns**: a JSON **array**, one object per AC item, each shaped:
  ```json
  {"id": "REQ-001_AC00", "covered": true, "quote": "verbatim sentence"}
  ```
  with `covered` false and `quote` null when the item is not addressed.

Write the agent's array output verbatim to `${BASE_PATH}/quality-gate/coverage-results.json`:

```bash
cat > "${BASE_PATH}/quality-gate/coverage-results.json" <<'EOF'
<the agent's JSON array>
EOF
```

The classify step (3c) reports any AC ids missing from the array; you do not need to count files by hand.

#### 3c. Classify coverage results

Determine whether code evidence was expected: check if `${BASE_PATH}/scope-req-audit/` or `${BASE_PATH}/validate/` exists as a directory. If either exists, add `--evidence-expected` to the command.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py verify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --classify \
  [--repo "${REPO_PATH}"] \
  [--evidence-expected]
```

When `--repo` is provided and no `evidence-status.json` exists from a prior scope-req-audit run, the script performs an inline code-evidence check using the learn-code module registry (from `<base-path>/code-analysis/step-result.json → repo_analysis_path`) and grep fallback. This replaces the separate scope-req-audit step for gap classification.

Reads `coverage-results.json`, validates quotes against the documentation (whitespace-normalized substring match), joins to evidence status, and writes `${BASE_PATH}/quality-gate/coverage-check.json`. It prints only a `total=… covered=… uncovered=…` summary and warns (on stderr) if any AC item had no agent result.

Classifications:
- `covered` — AC is addressed with a verified quote. No action needed.
- `real_defect` — AC is not in the documentation but code evidence exists (grounded or partial). Fix it.
- `correctly_absent` — AC is not in the documentation and code evidence is absent. Document as unsupported.
- `unverified` — Agent claimed coverage but the quote was not found in the document. Investigate.
- `investigate` — AC is not covered and evidence status is unknown.

### 4. Dispatch intent alignment agent

Dispatch **one agent** (doc_quality judge is skipped in the default flow).

Pass the `schema` JSON object as the Agent tool's `schema` parameter. This forces the agent to return structured output via the StructuredOutput tool with automatic retry on schema mismatch. **Do NOT omit the schema parameter** — without it, the agent returns free-text that requires manual parsing and loses the retry-on-mismatch safety net.

#### intent_alignment agent

- **Model**: opus
- **Prompt**: Read the contents of `${BASE_PATH}/quality-gate/ia-prompt.md` and follow the instructions exactly.
- **Schema** (pass as the `schema` parameter to the Agent tool):
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

After the agent returns, write its structured output to `${BASE_PATH}/quality-gate/judge-results.json`:

```json
{
  "intent_alignment": { "score": <N>, "rationale": "<text>", "missed_items": [...] }
}
```

Note: `doc_quality` is omitted from `judge-results.json` when the doc_quality judge is skipped. The classify step handles this gracefully.

If the agent returns `null` (skipped or died), mark the quality gate as `failed` — do not substitute default scores.

### 6. Classify gaps and write step-result.json

Determine the iteration number: count existing `feedback-brief-*.md` files in `${BASE_PATH}/quality-gate/`. If none exist, this is iteration 1. Otherwise, iteration = count + 1.

Determine whether code evidence was expected: check if `${BASE_PATH}/scope-req-audit/` or `${BASE_PATH}/validate/` exists as a directory. If either exists, add `--evidence-expected` to the command.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/quality_gate.py classify \
  --ticket "${TICKET}" \
  --base-path "${BASE_PATH}" \
  --judge-results "${BASE_PATH}/quality-gate/judge-results.json" \
  --iteration <N> \
  [--repo "${REPO_PATH}"] \
  [--evidence-expected]
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
- `doc_quality` (integer 1-5, or null when the doc_quality judge is skipped)
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
  "doc_quality": null,
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
    "doc_quality": null,
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
- `doc_quality` is skipped by default. When present (opt-in), it is reported but does **not** trigger a fix pass — the orchestrator logs a warning if `< 4` but proceeds. Only intent_alignment gaps are actionable
- When `passed = false`, this skill produces `feedback-brief-<iteration>.md` alongside the sidecar. The orchestrator dispatches the writer in fix mode with this file, or accepts with warning after max iterations

## Model

The intent alignment agent and coverage agent (step 3b) both use Opus to match the eval harness judge configuration. The model is specified via the Agent tool's `model` parameter — no separate API key or credentials required.

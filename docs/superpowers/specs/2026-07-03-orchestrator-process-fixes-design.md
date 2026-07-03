# Orchestrator Process Fixes

**Date:** 2026-07-03
**Status:** Draft
**Source:** RHAISTRAT-1280 post-run analysis (`docs-orchestrator-process-fixes.md`)
**Approach:** Targeted surgical fixes (Approach A) — prompt/script/SKILL.md changes only, no architectural refactors

## Context

The RHAISTRAT-1280 workflow run (2026-07-02, 51.5 min) surfaced 5 process issues across 3 priority levels. The dominant failure pattern was subagent premature return, hitting 3 of 12 steps and causing 6 re-dispatches. Secondary issues: artifact bloat inflating context pressure, workaround logging gaps masking intervention count, context pressure reaching CRITICAL, and the iteration ceiling being too low for large changes.

This spec covers short-term fixes. The Workflow-tool migration for fan-out steps (replacing nested Agent-in-Agent with `pipeline()`/`parallel()`) is deferred as a separate future effort.

## Fix 1: Subagent premature return — output verification contracts (P1)

### Problem

Step skills that fan out agents treat "I've sent all Agent tool calls" as task completion. The dispatching agent returns its final summary without blocking on results. Hit scope-req-audit (2 re-dispatches), technical-review (3 re-dispatches), and style-review (1 re-dispatch).

### Design

Add explicit output verification gates to 3 step skills. Each gate follows the same pattern: after agent dispatch, verify expected output count on disk before proceeding to the next step. The verification is a hard gate — the skill must not proceed until the count matches or missing items are accounted for.

### Changes

**`skills/docs-workflow-scope-req-audit/SKILL.md` — step 6 (Collect results from disk):**

Replace the passive file existence check with an active verification gate. After step 5 dispatches all agents, step 6 becomes:

> After all agents complete, verify that the expected per-requirement JSON files were written to disk.
>
> ```bash
> EXPECTED_COUNT=<number of requirements from step 3>
> ACTUAL_COUNT=$(ls ${OUTPUT_DIR}/evidence-*.json 2>/dev/null | wc -l)
> echo "Evidence files: ${ACTUAL_COUNT}/${EXPECTED_COUNT}"
> ```
>
> **HARD GATE — do NOT proceed to step 7 (merge) until `ACTUAL_COUNT` equals `EXPECTED_COUNT`.** If any agents are still running, wait for them to complete. After all agents have returned, if files are still missing:
>
> 1. Identify which REQ IDs have no corresponding `evidence-<NNN>.json`
> 2. Log: `"Missing evidence files for: REQ-003, REQ-007"` (list actual missing IDs)
> 3. The merge agent (step 7) will create fallback entries for missing files — proceed to step 7 only after confirming the missing IDs

**`skills/docs-workflow-tech-review/SKILL.md` — between steps 2b and 2c:**

Add a verification step after dispatching code-questioner agents:

> **2b-verify. Verify batch verdicts before merging**
>
> The `batch_count` from `prepare_claims.py` tells you how many verdict files to expect.
>
> ```bash
> EXPECTED_BATCHES=<batch_count from prepare_claims.py output>
> ACTUAL_BATCHES=$(ls ${OUTPUT_DIR}/batch-verdict-*.json 2>/dev/null | wc -l)
> echo "Batch verdicts: ${ACTUAL_BATCHES}/${EXPECTED_BATCHES}"
> ```
>
> **HARD GATE — do NOT proceed to step 2c (merge verdicts) until `ACTUAL_BATCHES` equals `EXPECTED_BATCHES`.** If agents are still running, wait. After all agents have returned, if verdict files are missing, log which batch sanitized names are missing — `merge_verdicts.py` assigns `no_evidence_found` fallback verdicts for claims in missing batches, so proceed to 2c after logging.

**`skills/docs-workflow-style-review/SKILL.md` — step 4 (Verify output):**

Strengthen from "verify the review report exists" to:

> After the agent completes, verify the review report exists and is non-empty:
>
> ```bash
> test -f "$OUTPUT_FILE" && test -s "$OUTPUT_FILE" && echo "OK" || echo "MISSING_OR_EMPTY"
> ```
>
> **HARD GATE — if the file is missing or empty, do NOT write the sidecar or report completion.** Treat this as a step failure. The orchestrator will handle the failure per its standard step-failure logic.

## Fix 2: Code-analysis artifact bloat (P1)

### Problem

The code-analysis step copies the full learn-code output (1,000 KB, 99 files) to `<base-path>/code-analysis/`. This is 56% of total pipeline artifacts. No downstream consumer reads from this copy — the orchestrator reads only the sidecar, and downstream agents read from the original cached location at `.agent_workspace/<repo-name>/`.

### Design

Stop copying the full analysis tree. Write only `ONBOARDING.md` (for human browsing) and `step-result.json` to the step output directory. Add `repo_analysis_path` to the sidecar so the cached location is recorded explicitly in the progress file.

### Changes

**`skills/docs-workflow-code-analysis/SKILL.md` — steps 2 and 3 (cached analysis copy block):**

Replace the multi-file copy block:

```bash
cp "${LEARN_CODE_BASE}/synthesis/ONBOARDING.md" "${OUTPUT_DIR}/"
cp "${LEARN_CODE_BASE}/detection/detection.json" "${OUTPUT_DIR}/detection.json" 2>/dev/null
cp "${LEARN_CODE_BASE}/module-registry/registry.json" "${OUTPUT_DIR}/registry.json" 2>/dev/null
mkdir -p "${OUTPUT_DIR}/summaries" "${OUTPUT_DIR}/relationships"
cp "${LEARN_CODE_BASE}/module-analysis/"*.json "${OUTPUT_DIR}/summaries/" 2>/dev/null
cp "${LEARN_CODE_BASE}/relationships/"*.json "${OUTPUT_DIR}/relationships/" 2>/dev/null
```

With:

```bash
cp "${LEARN_CODE_BASE}/synthesis/ONBOARDING.md" "${OUTPUT_DIR}/"
```

This applies to both the cached path (step 2) and the post-agent path (step 3).

**`skills/docs-workflow-code-analysis/SKILL.md` — step 4 (Write step-result.json):**

Add `repo_analysis_path` field. The sidecar example becomes:

```json
{
  "schema_version": 1,
  "step": "code-analysis",
  "ticket": "<TICKET>",
  "completed_at": "<ISO 8601>",
  "module_count": "<length of registry.json array>",
  "relationship_count": "<count of .json files in relationships/>",
  "languages_detected": ["<keys from detection.json language_counts>"],
  "repo_path": "<absolute path to repo>",
  "repo_analysis_path": "<absolute path to LEARN_CODE_BASE>"
}
```

Update the metrics extraction instructions to read from `LEARN_CODE_BASE` directly (since the files are no longer copied to `OUTPUT_DIR`):

- `module_count`: read from `${LEARN_CODE_BASE}/module-registry/registry.json`
- `relationship_count`: count `.json` files in `${LEARN_CODE_BASE}/relationships/`
- `languages_detected`: read from `${LEARN_CODE_BASE}/detection/detection.json`

**`skills/docs-orchestrator/schema/step-result-schema.md` — code-analysis section:**

Add to the field table:

| Field | Type | Description | Consumed by |
|---|---|---|---|
| `repo_analysis_path` | string | Absolute path to the learn-code analysis directory (contains detection/, module-registry/, module-analysis/, relationships/, synthesis/) | Orchestrator — recorded in progress file for downstream steps |

**`skills/docs-orchestrator/references/step-post-processing.md` — code-analysis section:**

Add after "Record `repo_path` from the sidecar for downstream steps":

> Record `repo_analysis_path` from the sidecar. This is the canonical location of learn-code analysis data. Downstream steps that need analysis files (scope-req-audit, tech-review) can use this path directly rather than re-deriving it.

### Impact

Reduces code-analysis step output from ~1,000 KB to ~15 KB (ONBOARDING.md + step-result.json). Total pipeline artifact size drops from ~1,780 KB to ~780 KB. Context pressure score should decrease by 2-3 points.

## Fix 3: Workaround logging gap (P2)

### Problem

The progress file logged 1 workaround, but the orchestrator actually applied 3+ workarounds (re-dispatches for scope-req-audit, technical-review, style-review). Pipeline diagnostics underreported the actual intervention count.

### Design

Extend the "Logging workarounds" instructions to explicitly cover re-dispatches. The `progress.py log-workaround` script already handles the mechanics — only the prose instructions need updating.

### Changes

**`skills/docs-orchestrator/SKILL.md` — "Logging workarounds" section (after line 178):**

Append:

> **Re-dispatches are workarounds.** Any re-dispatch of a step's primary agent — whether due to empty output, incomplete output, or premature return — MUST be logged as a workaround **before** the re-dispatch. The `issue` field should describe what was missing (e.g., `"style-review agent returned empty review.md"`, `"scope-req-audit: 4/7 evidence files written after agent returned"`). The `action` field should describe the re-dispatch strategy (e.g., `"re-dispatched docs-reviewer agent with same prompt"`, `"re-dispatched 3 requirement-classifier agents for missing REQ-004, REQ-006, REQ-007"`). This includes partial re-dispatches where only a subset of fan-out agents are re-run.

## Fix 4: Context pressure mitigations (P2)

### Problem

Each step skill loads 3-8 KB of instructions into the orchestrator's context. Over 10 steps, this adds 30-80 KB. Combined with source resolution round-trips, the session hit CRITICAL context pressure with ~4 compaction events.

### Design

Two mitigations: (a) document the pre-resolution pattern so users can skip the resolve round-trip, and (b) provide a lightweight workflow YAML that drops advisory steps.

### Changes

**`skills/docs-orchestrator/SKILL.md` — new section after "Post-requirements source resolution":**

> ### Pre-resolved sources
>
> To skip the source resolution round-trip (saves context and one script invocation), provide the source repo path upfront via either method:
>
> - **CLI flag:** `--source-code-repo /path/to/cloned/repo`
> - **source.yaml:** Create `<base-path>/../source.yaml` with:
>   ```yaml
>   repo_path: /path/to/cloned/repo
>   ```
>
> Both methods bypass `resolve_source.py` entirely. Use for repos you've already cloned or when the source is known in advance.

**New file: `skills/docs-orchestrator/defaults/docs-workflow-fast.yaml`:**

An 8-step workflow for straightforward documentation updates. Drops scope-req-audit (advisory), security-review (new-content-only), quality-gate (large-change-only), and pipeline-diagnostics (audit-only). Keeps pr-analysis since it's already gated by `when: has_pr` and adds zero overhead when unused.

```yaml
workflow:
  name: docs-workflow-fast
  description: >-
    Lightweight workflow for straightforward documentation updates.
    Drops advisory and audit steps to reduce context pressure by ~40%.
    Use when: few requirements, no security-sensitive content, known source repo.

  steps:
    - name: requirements
      skill: docs-workflow-requirements
      description: Analyze documentation requirements

    - name: code-analysis
      skill: docs-workflow-code-analysis
      description: Analyze source repository
      when: has_source_repo
      inputs: [requirements]

    - name: pr-analysis
      skill: docs-workflow-pr-analysis
      description: Analyze PR/MR changes for documentation context
      when: has_pr
      inputs: [code-analysis]

    - name: planning
      skill: docs-workflow-planning
      description: Create documentation plan
      inputs: [requirements, code-analysis, pr-analysis]

    - name: writing
      skill: docs-workflow-writing
      description: Write documentation
      inputs: [planning, code-analysis]

    - name: technical-review
      skill: docs-workflow-tech-review
      description: Technical accuracy review
      inputs: [writing, code-analysis]

    - name: style-review
      skill: docs-workflow-style-review
      description: Style guide compliance review
      inputs: [writing, technical-review]

    - name: create-merge-request
      skill: docs-workflow-create-merge-request
      description: Commit, push, and create merge request or pull request
      when: create_merge_request
      inputs: [writing, style-review, technical-review]
```

Invoked via `--workflow fast` (the orchestrator resolves `docs-workflow-<name>.yaml` from defaults/).

## Fix 5: Iteration ceiling (P3)

### Problem

After 2 iterations (review + fix + re-review), the technical review still showed MEDIUM confidence with 3 critical and 7 significant findings. The `--max-iter 2` ceiling is too low for large changes where the fix pass can surface new issues.

### Design

Make `--max-iter` dynamic based on the number of files the writing step produced. When the writing sidecar has >5 files, pass `--max-iter 3`. The `iteration_decision.py` script already accepts `--max-iter` as a parameter — only the orchestrator invocation needs to change.

### Changes

**`skills/docs-orchestrator/SKILL.md` — "Technical review iteration" section (line 196):**

Change:

> Loop up to 2 iterations (one review, one fix-and-confirm). The loop decision — the confidence/severity/iteration rules — is owned by `iteration_decision.py`; do NOT evaluate it by hand.

To:

> Loop up to N iterations. The default `--max-iter` is 2. When the writing step produced more than 5 files (check `steps.writing.result.files` array length in the progress file), pass `--max-iter 3` to allow an additional fix-and-confirm pass for larger changes. The loop decision — the confidence/severity/iteration rules — is owned by `iteration_decision.py`; do NOT evaluate it by hand.

Change the invocation in step 2 from:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/iteration_decision.py tech-review \
  --sidecar <base_path>/technical-review/step-result.json
```

To:

```bash
FILE_COUNT=$(python3 -c "import json; d=json.load(open('<progress_file>')); print(len(d.get('steps',{}).get('writing',{}).get('result',{}).get('files',[])))")
MAX_ITER=$( [ "$FILE_COUNT" -gt 5 ] 2>/dev/null && echo 3 || echo 2 )

python3 ${CLAUDE_SKILL_DIR}/scripts/iteration_decision.py tech-review \
  --sidecar <base_path>/technical-review/step-result.json \
  --max-iter $MAX_ITER
```

Apply the same dynamic `--max-iter` pattern to the quality-gate iteration invocation for consistency.

## Change summary

| Fix | Priority | Files modified | Files created | Risk |
|---|---|---|---|---|
| 1. Verification contracts | P1 | 3 SKILL.md | 0 | Low — additive instructions |
| 2. Artifact bloat | P1 | 2 SKILL.md, 1 schema, 1 post-processing ref | 0 | Low — removes copies, adds field |
| 3. Workaround logging | P2 | 1 SKILL.md | 0 | Low — prose addition |
| 4. Context pressure | P2 | 1 SKILL.md | 1 YAML | Low — new workflow + docs |
| 5. Iteration ceiling | P3 | 1 SKILL.md | 0 | Low — conditional flag |

**Total:** 7 files modified, 1 file created. All changes are to SKILL.md instructions, schema docs, or workflow YAML — no Python script changes required.

## Future work (not in scope)

- **Workflow-tool migration:** Replace Agent-in-Agent fan-out in scope-req-audit and tech-review with Workflow scripts using `parallel()`. Eliminates the premature-return failure mode entirely. Larger refactor — separate spec.
- **Skill instruction trimming:** Move agent-facing reference material from step SKILL.md files to agent prompts or referenced files to reduce per-skill context load.
- **Progress file argument caching:** Cache constructed step arguments in the progress file so post-compaction re-invocation can skip argument construction.

# Quality Gate

The quality gate is a documentation quality assurance step in the docs-orchestrator workflow. It scores documentation on two dimensions using independent LLM judge agents (Opus), produces a pass/fail verdict, and triggers automated fix iterations when documentation falls short of intent alignment.

## Purpose

The quality gate answers: **"Did we write what was asked for?"** It evaluates documentation after the writing, technical-review, style-review, and security-review steps, before a merge request is created. It is orthogonal to technical review (which checks accuracy) — the quality gate checks **completeness and intent alignment** against the original JIRA ticket and its acceptance criteria.

## Scoring dimensions

Two parallel Opus judge agents evaluate the documentation independently:

### doc_quality (1-5)

Production readiness: technical accuracy, completeness, modular structure (concept/procedure/reference modules), and absence of fabricated content.

| Score | Meaning |
|-------|---------|
| 1 | Unusable |
| 2 | Major issues |
| 3 | Acceptable with caveats |
| 4 | Good |
| 5 | Excellent |

This score is **informational only** — it does not trigger fix iterations. If `doc_quality < 4`, the orchestrator logs a warning recommending manual review.

### intent_alignment (1-5)

How well the documentation fulfills the JIRA ticket's requirements:

| Score | Meaning |
|-------|---------|
| 1 | Off-target |
| 2 | Partially addresses the ticket |
| 3 | Covers most items with gaps |
| 4 | Strong alignment |
| 5 | Full alignment |

The intent_alignment judge evaluates:
- **Scope match** — does the output match the ticket request?
- **Acceptance criteria coverage** — are all acceptance criteria items addressed?
- **Audience alignment** — does content match the target audience?
- **Focus** — does the documentation stay on topic?

When `intent_alignment < 4`, the judge returns a `missed_items` array identifying each gap with a severity (`missing` or `incomplete`), target file, and section location.

## Per-acceptance-criteria coverage verification

Before the judge agents score the documentation, a deterministic coverage check verifies each acceptance criterion is addressed with a grounded quote. This runs on every quality gate invocation (initial and re-runs), providing a verifiable signal independent of the LLM judges.

### Procedure

1. Each acceptance criteria item from `requirements/discovery.json` gets its own subagent
2. Each subagent receives only its single acceptance criteria item and the full documentation — no other acceptance criteria, no judge context, no conversation history
3. The subagent answers yes/no and, if yes, quotes the supporting sentence verbatim
4. Python code verifies the quote actually exists in the documentation (whitespace-normalized substring match)
5. Each result is joined to scope-req-audit evidence status to classify the gap

### Classifications

| Coverage | Quote verified | Evidence status | Classification | Action |
|----------|---------------|-----------------|---------------|--------|
| Yes | Yes | any | `covered` | None |
| Yes | No | any | `unverified` | `investigate` |
| No | — | `grounded` | `real_defect` | `add_missing_section` |
| No | — | `partial` | `real_defect` | `expand_with_evidence` |
| No | — | `absent` | `correctly_absent` | `document_as_unsupported` |
| No | — | `unknown` | `investigate` | `investigate` |

The key insight: `real_defect` (absent from doc, present in code) means "fix it" — the documentation is genuinely missing content. `correctly_absent` (absent from doc, absent in code) means "leave it" — the feature doesn't exist, so document it as unsupported. This distinction is automatic because it joins two independent signals.

### Relationship to judge agents

The coverage check and judge agents serve different purposes:
- **Coverage check**: deterministic, per-acceptance-criteria, quote-grounded. Answers "is this specific acceptance criteria item addressed, provably?"
- **Judge agents**: holistic quality and intent alignment scoring. Answers "is the documentation good and on-target?"

Coverage check defects are merged into the gaps array alongside judge-derived gaps. When both identify the same gap, the coverage check classification takes precedence because it includes a deterministic quote verification. The `judge` field distinguishes the source (`"coverage_check"` vs `"intent_alignment"`).

## Pass/fail criteria

| Condition | Result |
|-----------|--------|
| `intent_alignment >= 4` | **Pass** — proceed to merge request |
| `intent_alignment < 4` | **Fail** — enter iteration loop |
| After 2 iterations, `intent_alignment >= 3` | **Accept with warning** |
| After 2 iterations, `intent_alignment < 3` | **Ask user** — proceed or stop |

## Conditional execution

The quality gate runs conditionally (`when: has_many_requirements`) to avoid unnecessary overhead on simple tickets. The condition is evaluated in two phases:

### Phase 1 — After requirements step

| Condition | Result |
|-----------|--------|
| `requirement_count < 6` | **Skipped** — too few requirements to warrant a gate |
| `requirement_count >= 6` | **Deferred** — provisionally needed, pending tech review |
| `requirement_count` missing | **Deferred** — backward compatibility default |

### Phase 2 — After technical-review step

| Condition | Result |
|-----------|--------|
| Already skipped in Phase 1 | No change |
| Tech review confidence = `HIGH` | **Skipped** — strong writer comprehension makes intent drift unlikely |
| Tech review confidence = `MEDIUM` or `LOW` | **Pending** — gate runs |
| Technical-review was skipped | **Pending** — no confidence signal, gate runs |

Custom workflow YAMLs can override this logic by always including or excluding the quality-gate step.

## Iteration loop

When the quality gate fails (`passed = false`), the orchestrator enters an iteration loop (max 2 iterations):

1. Quality gate runs, produces `step-result.json`
2. If `passed = false`, build `feedback-brief-<N>.md` containing:
   - Full judge rationales (verbatim from both judges)
   - Classified gap list with recommended actions
   - Priority ordering for fixes
   - Prior-attempt guidance (iteration 2+)
3. Dispatch the writer in fix mode: `docs-workflow-writing --fix-from feedback-brief-<N>.md`
4. Re-run the quality gate on the updated documentation
5. After 2 iterations: accept with warning if `intent_alignment >= 3`, otherwise ask the user

## Gap classification

When the quality gate fails, each missed item is cross-referenced against the scope-req-audit's evidence status to determine the appropriate fix action:

| Evidence status | Action | Description |
|-----------------|--------|-------------|
| `absent` | `document_as_unsupported` | Add a "not supported in this release" note |
| `partial` | `expand_with_evidence` | Expand existing content with available code evidence |
| `grounded` | `add_missing_section` | Content was in the plan but not written — re-include |
| `unknown` | `investigate` | Evidence status unavailable — review manually |

## Pipeline position

```
requirements → code-analysis → scope-req-audit → planning → writing
  → technical-review → style-review → security-review
  → quality-gate → create-merge-request → pipeline-diagnostics
```

**Inputs**: `writing` (the documentation files), `requirements` (ticket summary and acceptance criteria items)

**Optional input**: `scope-req-audit` evidence status (for gap classification)

## Output artifacts

The quality gate writes to `.agent_workspace/<ticket>/quality-gate/`:

| File | Description |
|------|-------------|
| `coverage-prompts/manifest.json` | Manifest of acceptance criteria items with prompt/result file paths |
| `coverage-prompts/<id>.md` | Per-acceptance-criteria prompt file with doc content |
| `coverage-results/<id>.json` | Per-acceptance-criteria agent result (`covered`, `quote`) |
| `coverage-check.json` | Classified results with quote verification and evidence status join |
| `dq-prompt.md` | Doc quality judge prompt with documentation content interpolated |
| `ia-prompt.md` | Intent alignment judge prompt with documentation and ticket context |
| `judge-results.json` | Raw structured outputs from both judge agents |
| `judge-results.md` | Human-readable summary with rationales |
| `step-result.json` | Sidecar metadata: scores, passed flag, gaps, coverage summary, rationales |
| `feedback-brief-<N>.md` | Fix instructions for writer iteration (only when `passed = false`) |

## step-result.json schema

```json
{
  "schema_version": 1,
  "step": "quality-gate",
  "ticket": "PROJ-123",
  "completed_at": "2026-04-23T15:50:00Z",
  "doc_quality": 4,
  "intent_alignment": 3,
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
      "section": "After 'Verifying the deployment'"
    }
  ],
  "rationales": {
    "doc_quality": "Full judge rationale text...",
    "intent_alignment": "Full judge rationale text with per-acceptance-criteria coverage..."
  }
}
```

## Implementation

- **Skill**: `docs-workflow-quality-gate` (`skills/docs-workflow-quality-gate/SKILL.md`)
- **Script**: `skills/docs-workflow-quality-gate/scripts/quality_gate.py` — subcommands: `prepare` (build judge prompts), `verify` (per-acceptance-criteria coverage check), `classify` (cross-reference gaps, write sidecar)
- **Condition logic**: `skills/docs-orchestrator/references/quality-gate-conditions.md`
- **Post-processing**: `skills/docs-orchestrator/references/step-post-processing.md`
- **Workflow definition**: `skills/docs-orchestrator/defaults/docs-workflow.yaml` (step 10 of 12)

# Quality Gate

The quality gate is a documentation quality assurance step in the docs-orchestrator workflow. It verifies that every acceptance criterion in the JIRA ticket is addressed by the documentation, produces a pass/fail verdict from a deterministic per-acceptance-criteria coverage check, and triggers automated fix iterations when criteria are missed.

## Purpose

The quality gate answers: **"Did we write what was asked for?"** It evaluates documentation after the writing, technical-review, style-review, and security-review steps, before a merge request is created. It is orthogonal to technical review (which checks accuracy) — the quality gate checks **completeness and intent alignment** against the original JIRA ticket and its acceptance criteria.

The gate has two components: a **per-acceptance-criteria coverage check** (the authoritative pass/fail signal) and a single **intent_alignment judge** (a holistic score and narrative rationale that feeds the feedback brief).

> **Removed: the `doc_quality` judge.** Earlier versions ran a second Opus judge that scored documentation on production readiness (technical accuracy, modular structure, absence of fabrication). That dimension is already covered by the `technical-review` and `style-review` steps, and in practice the score was non-discriminating (near-constant 4/5) and never gated. It was removed so the quality gate focuses solely on the requirements-coverage dimension those steps do not assess.

## The intent_alignment judge

A single Opus judge scores the documentation against the ticket intent.

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

The deterministic coverage check is the authoritative gate signal. It verifies each acceptance criterion is addressed with a grounded quote, independent of the LLM judge. It is **mandatory** whenever the ticket has acceptance criteria and runs on every quality gate invocation (initial and re-runs); the `classify` step fails loudly if acceptance criteria exist but the coverage results are missing.

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

### Relationship to the intent judge

The coverage check and the intent judge serve different purposes:
- **Coverage check**: deterministic, per-acceptance-criteria, quote-grounded. Answers "is this specific acceptance criteria item addressed, provably?" — and is the gate.
- **Intent judge**: holistic scoring and narrative. Answers "is the documentation on-target for the audience and scope?" — its rationale drives the feedback brief and its `missed_items` supplement the gap list.

Coverage check defects are merged into the gaps array alongside judge-derived gaps. When both identify the same gap, the coverage check classification takes precedence because it includes a deterministic quote verification. The `judge` field distinguishes the source (`"coverage_check"` vs `"intent_alignment"`).

## Pass/fail criteria

The gate is coverage-driven. It passes only when **every** acceptance criterion is `covered` or `correctly_absent`:

| Condition | Result |
|-----------|--------|
| Every acceptance criterion `covered` or `correctly_absent` | **Pass** — proceed to merge request |
| Any `real_defect`, `unverified`, or `investigate` criterion | **Fail** — enter iteration loop |
| No acceptance criteria exist (nothing to verify) | Fall back to `intent_alignment >= 4` |
| After 2 iterations, still failing | **Accept with warning**, listing unresolved gaps |

A `correctly_absent` criterion (missing from the docs and absent from the code) does not block the gate — the feature genuinely does not exist — but is still surfaced as a gap with a `document_as_unsupported` action.

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
   - The full intent_alignment judge rationale (verbatim)
   - Classified gap list with recommended actions
   - Priority ordering for fixes
   - Prior-attempt guidance (iteration 2+)
3. Dispatch the writer in fix mode: `docs-workflow-writing --fix-from feedback-brief-<N>.md`
4. Re-run the quality gate on the updated documentation
5. After 2 iterations still failing: accept with warning, listing the unresolved gaps (the human MR review is the backstop)

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
| `ia-prompt.md` | Intent alignment judge prompt with documentation and ticket context |
| `judge-results.json` | Raw structured output from the intent_alignment judge |
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
    "intent_alignment": "Full judge rationale text with per-acceptance-criteria coverage..."
  }
}
```

## Implementation

- **Skill**: `docs-workflow-quality-gate` (`skills/docs-workflow-quality-gate/SKILL.md`)
- **Script**: `skills/docs-workflow-quality-gate/scripts/quality_gate.py` — subcommands: `prepare` (build the intent judge prompt), `verify` (per-acceptance-criteria coverage check), `classify` (compute the coverage verdict, cross-reference gaps, write sidecar)
- **Condition logic**: `skills/docs-orchestrator/references/quality-gate-conditions.md`
- **Post-processing**: `skills/docs-orchestrator/references/step-post-processing.md`
- **Workflow definition**: `skills/docs-orchestrator/defaults/docs-workflow.yaml` (step 10 of 12)

# `when: has_many_requirements` Condition

The `quality-gate` step uses `when: has_many_requirements`. This condition is evaluated in two phases:

## Phase 1 — After requirements step completes (initial evaluation)

- Read `requirement_count` from `steps.requirements.result` in the progress file
- If `requirement_count < 6` → condition is not met, mark the step as `skipped` with `skip_reason: "few_requirements"`. Log: `"Skipping quality-gate: <requirement_count> requirements (threshold: 6)"`
- If `requirement_count >= 6` → mark as `deferred`. The gate is provisionally needed but the tech-review result may change that (see Phase 2)
- If `requirement_count` is missing from the sidecar (backward compatibility) → treat as `deferred`. Log a warning: `"requirement_count missing from requirements sidecar — defaulting to quality-gate enabled"`

## Phase 2 — After technical-review step completes (re-evaluation)

- If the step was already `skipped` in Phase 1, no change
- Read `confidence` from `steps.technical-review.result`
- If `confidence` is `HIGH` → the tech review validated all claims against source code, indicating strong requirements comprehension by the writer. Intent drift is unlikely. Mark quality-gate as `skipped` with `skip_reason: "high_confidence_review"`. Log: `"Skipping quality-gate: technical review reached HIGH confidence"`
- If `confidence` is `MEDIUM` or `LOW` → condition is met, mark as `pending`. The tech review could not fully validate the writing, so an independent intent-alignment check adds value
- If technical-review was `skipped` → condition is met, mark as `pending` (no confidence signal available)

## Rationale

The quality gate checks intent alignment — "did we write what was asked for?" — which is orthogonal to the tech review's accuracy check. However, both accuracy and completeness tend to follow from the same upstream quality: clear requirements, good code-analysis, and strong writer comprehension. When the tech review reaches HIGH, it signals that the writer had a solid grasp of the material, making coverage gaps less likely. Combining the requirement-count threshold (complexity filter) with the confidence signal (quality filter) skips the gate only when both indicators suggest it is unlikely to find gaps.

The threshold and confidence logic can be overridden by using a custom workflow YAML that either always includes or always excludes quality-gate.

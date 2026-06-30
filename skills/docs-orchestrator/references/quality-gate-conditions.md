# `when: has_review_issues` Condition

The `quality-gate` step uses `when: has_review_issues`. This condition is evaluated after the technical-review step completes. The quality gate runs only when the tech review found critical or significant issues — direct evidence that intent alignment should be checked.

## Evaluation — After technical-review step completes

- Read `severity_counts` and `confidence` from `steps.technical-review.result` in the progress file
- If `severity_counts.critical > 0` OR `severity_counts.significant > 0` → condition is met, mark quality-gate as `pending`. Critical or significant issues indicate potential intent drift regardless of ticket complexity. Log: `"Quality-gate enabled: technical review found <critical> critical + <significant> significant issue(s)"`
- If `severity_counts.critical == 0` AND `severity_counts.significant == 0` AND `confidence` is `LOW` → condition is met, mark quality-gate as `pending`. LOW confidence after review iterations signals broad comprehension problems even without specific high-severity findings. Log: `"Quality-gate enabled: technical review confidence is LOW"`
- If `severity_counts.critical == 0` AND `severity_counts.significant == 0` AND `confidence` is not `LOW` → condition is not met, mark quality-gate as `skipped` with `skip_reason: "no_critical_or_significant_issues"`. Log: `"Skipping quality-gate: no critical or significant issues found"`
- If technical-review was `skipped` → condition is met, mark quality-gate as `pending` (no signal available). Log: `"Quality-gate enabled: technical review was skipped (no signal)"`

## Initial status

Before the technical-review step completes, the quality-gate step is `deferred`. It is only evaluated once: after the technical-review iteration loop finishes.

## Rationale

The quality gate checks intent alignment — "did we write what was asked for?" — which is orthogonal to the tech review's accuracy check. However, when the tech review finds zero critical or significant issues and confidence is not LOW, the writing is likely solid enough that a full intent-alignment sweep adds cost without proportional value. Critical or significant issues in any ticket — even one with only 2–3 requirements — are worth checking for intent drift.

The LOW confidence safety net covers edge cases where the reviewer could not verify claims but did not flag specific high-severity issues. LOW confidence after the tech review iteration loop (which attempts fixes before escalating) is rare and signals deeper comprehension problems that the quality gate can catch.

The threshold and confidence logic can be overridden by using a custom workflow YAML that either always includes or always excludes quality-gate.

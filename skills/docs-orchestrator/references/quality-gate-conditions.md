# Quality Gate Conditions

The quality-gate step runs unconditionally in the default workflow (`docs-workflow.yaml`). It no longer uses the `when: has_many_requirements` conditional.

## Prior design (removed)

Previously, the quality gate was gated by a two-phase condition:
- Phase 1 (after requirements): skip if `requirement_count < 6`
- Phase 2 (after tech-review): skip if `confidence == HIGH`

This was removed because the amalgamated quality gate is lightweight enough (2 agents instead of ~11 combined with scope-req-audit) to run on every pipeline execution. The inline evidence check replaces scope-req-audit's 7-agent fan-out with a deterministic module-registry lookup + grep, eliminating the cost justification for skipping.

## Overriding

To skip the quality gate, use a custom workflow YAML that omits the `quality-gate` step (e.g., `docs-workflow-fast.yaml` already omits it).

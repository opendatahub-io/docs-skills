# Context Pressure Detection Model

How the diagnostics skill estimates when the conversation context window is approaching capacity and compaction is likely.

## Why context pressure matters

The docs-orchestrator runs an entire multi-step pipeline in a single Claude session. Each step adds to the conversation context: tool calls, skill reads, artifact reads, sidecar writes, and orchestrator logging. When the context window fills, automatic compaction compresses earlier turns — potentially losing nuance from requirements analysis, code-analysis details, or intermediate review feedback.

Context pressure does not cause failures directly, but it creates conditions where:
- Step skills lose access to earlier reasoning (requirements nuance, code-analysis findings)
- Sidecar writes may be dropped if the instruction was in a compacted turn
- Quality degrades in later steps (writing references fewer early-stage details)
- Resume after interruption requires more re-reading from disk

## Measurement approach

Token counts are not available inside the pipeline at runtime. The diagnostics script uses proxy signals instead.

### Signal 1: Step count progression

Each completed step adds approximately 3,000–15,000 tokens of conversation context:
- Skill read (~1,500–4,000 tokens per step skill)
- Tool calls for artifact reads (~500–2,000 tokens)
- Agent dispatch and response (~2,000–8,000 tokens for writing, review)
- Orchestrator logging and progress updates (~500–1,000 tokens)

| Steps completed | Estimated context usage | Risk |
|---|---|---|
| 1–4 | 15–40K tokens | Low |
| 5–7 | 40–80K tokens | Moderate |
| 8–10 | 80–120K tokens | High |
| 11+ | 120K+ tokens | Critical |

These estimates assume Claude Code's typical context window. Actual limits depend on the model and configuration.

### Signal 2: Artifact sizes

Steps that produce large artifacts contribute to context when downstream steps read those artifacts. The script measures artifact directory sizes as a proxy:

| Artifact category | Typical size | Context impact |
|---|---|---|
| requirements/ | 10–50 KB | Medium — read by planning, writing, quality-gate |
| code-analysis/ | 50–500 KB | High — read by planning, writing, tech-review; large repos produce large registries |
| writing/ | 20–200 KB | High — read by tech-review, style-review, quality-gate |
| technical-review/ | 10–100 KB | Medium — read by writing (fix mode), quality-gate |
| scope-req-audit/ | 5–50 KB | Low — read only by orchestrator for logging |

The script flags total artifacts above 500 KB (moderate) and 1,000 KB (high).

### Signal 3: Weighted context load

Not all steps consume context equally. The script assigns weights:

| Step | Weight | Rationale |
|---|---|---|
| writing | 2.0 | Full document generation, reads requirements + plan + code-analysis |
| technical-review | 1.8 | Claim extraction + per-claim validation + fix dispatch |
| code-analysis | 1.5 | Learn-code subagent, module registry, relationships |
| resolve-feedback | 1.5 | Re-reads gaps, writing output, applies targeted fixes |
| planning | 1.2 | Reads requirements + code-analysis + scope-audit |
| requirements | 1.0 | JIRA analysis, PR reading, requirements extraction |
| scope-req-audit | 1.0 | Gap classification against code-analysis |
| quality-gate | 1.0 | Judge agent scoring, gap identification |
| pr-analysis | 0.8 | PR diff analysis |
| style-review | 0.8 | Rule-based review, relatively lightweight |

A weighted load above 8.0 indicates significant accumulated context.

### Signal 4: Iteration overhead

Review and quality-gate loops multiply context consumption:
- Each tech-review iteration adds ~10,000–20,000 tokens (re-read artifacts, re-validate claims, re-write review.md)
- Each quality-gate iteration adds ~8,000–15,000 tokens (re-judge, identify gaps, dispatch fix agent)

The script adds the iteration count directly to the risk score.

## Risk score calculation

The risk score is a simple sum of triggered conditions:

| Condition | Points |
|---|---|
| 6+ steps completed | +2 |
| 8+ steps completed | +2 (additional) |
| Artifacts > 500 KB | +1 |
| Artifacts > 1,000 KB | +2 (additional) |
| Weighted load > 8.0 | +2 |
| Each extra iteration | +1 per iteration |
| code-analysis > 200 KB | +1 |

| Risk score | Level | Interpretation |
|---|---|---|
| 0–2 | Low | Context well within limits. No action needed |
| 3–5 | Moderate | Compaction possible in later steps. Monitor output quality |
| 6–8 | High | Compaction likely. Late steps may lose early-step context. Consider workflow splitting |
| 9+ | Critical | Near-certain compaction. Multiple compaction events probable. Strong recommendation to split workflow |

## Mitigation strategies

### For moderate pressure

- Ensure `source.yaml` has tight `scope.include` patterns to limit code-analysis artifact size
- Use `--draft` mode to skip framework detection overhead
- Monitor late-step output for missing details from early steps

### For high pressure

- Split into a two-phase workflow: analysis phase (requirements, code-analysis, scope-audit, planning) and execution phase (writing, reviews, quality-gate)
- Pre-resolve source repos with `source.yaml` before starting the workflow
- Consider using `--max-secondary-repos 1` to limit multi-repo overhead

### For critical pressure

- Create a custom workflow YAML with only the needed steps (e.g., `docs-writing-only.yaml` that skips analysis steps and reads from an existing plan)
- Run code-analysis as a separate learn-code invocation beforehand, then reference the cached results
- Break the ticket into multiple smaller tickets with fewer requirements each

## Calibration notes

These thresholds are based on observed pipeline runs and known Claude context limits as of June 2025. They should be recalibrated when:
- The model's context window size changes
- The orchestrator's step skill sizes change significantly
- New steps are added to the default workflow
- The artifact output sizes change due to script updates

The diagnostics script intentionally errs on the side of caution — it flags "moderate" earlier than strictly necessary, because the cost of a false positive (an unnecessary warning) is much lower than the cost of a false negative (a compaction-induced quality regression that goes unnoticed).

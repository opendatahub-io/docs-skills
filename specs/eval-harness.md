# Pipeline Evaluation Harness

An evaluation suite that scores the `docs-orchestrator` pipeline end-to-end against a fixed set of human-authored baselines, so we can measure documentation quality, intent alignment, and pipeline health across changes to the skills, prompts, and models.

Built on the [agent-eval-harness](https://github.com/opendatahub-io/agent-eval-harness) plugin (v1.20.0+). This repo supplies only the eval **config**, **dataset**, and a few **local judges/scripts** — the harness itself is an installed dependency, not vendored code.

## Background

Two source branches in `ccs-ai-agentic-workflow` motivated this work:

- **`feat/eval-port`** — a full pipeline eval (dataset, setup scripts, LLM + inline judges) targeting the CCS orchestrator, itself ported from `redhat-docs-agent-tools` MR !14. Its `eval.yaml` follows an older harness schema.
- **`feat/eval-diagnostics-checks`** (MR !126) — deterministic diagnostics judges (`diagnostics_judge.py`) layered on top of `pipeline_diagnostics.py`, which was in turn *ported from this repo's* `docs-workflow-pipeline-diagnostics` skill.

This spec is a **fresh build on the current harness**, reusing only the still-valid, valuable pieces of that work rather than a verbatim port.

## Access model

The eval is **Red Hat internal in practice**. It writes into the internal GitLab `openshift-ai-documentation` repo and reads gold standards from merged GitLab MRs, so running it requires:

- `glab` authenticated to `gitlab.cee.redhat.com` (VPN connected)
- `JIRA_API_TOKEN` and `JIRA_EMAIL` for JIRA access
- The `agent-eval-harness` and `docs-skills` plugins installed

docs-skills lives in a public repo but is an upstream Red Hat resource with no external contributors. The internal GitLab URLs are auth-gated, not secret, so they are committed as-is. No sanitization of repo URLs, ticket IDs, or MR references is required. The only rule: **never commit secrets** (tokens stay in environment variables).

## Non-goals

- Making the eval runnable without Red Hat credentials.
- Migrating the internal docs target to a public mirror (the opendatahub.io sync is retired).
- Re-implementing anything the harness already provides (execution, collection, scoring, MLflow, reporting).
- Modifying the `docs-orchestrator` skill itself. This is measurement, not pipeline change.

## Compatibility with current `main`

This spec was validated against `main` after the RHAISTRAT-1280 orchestrator refactor and quality-gate redesign. The plan's structural assumptions are confirmed intact:

- `step-result.json` still carries `schema_version` / `step` / `ticket` / `completed_at`, and the `requirements` / `planning` / `writing` step names are unchanged — the inline `check` judges hold.
- The orchestrator argument-hint still exposes `--source-code-repo` and `--docs-repo-path` — the `execution.arguments` template holds.
- `pipeline_diagnostics.py` on current `main` still lacks the token-estimation fields `diagnostics_judge.py` needs, so the Phase-2 two-way merge is still required. Its baseline is the *current* script, which recently gained a diagnostics-crash fix and a `find_progress_files` change — the merge must preserve those while adding the CCS token estimation.
- Per the strengthened CLAUDE.md rule (*all JSON I/O through scripts*), every judge that reads a sidecar or progress file does so in a Python judge module — no hand-parsing in prose.

## Architecture

The harness runs each case as one `docs-orchestrator` invocation, collects its output, and scores it with a set of judges. This repo defines four things:

```text
eval/eval.yaml                  Eval config (v1.20.0 schema), targeting docs-skills:docs-orchestrator
eval/cases/<case>/              Dataset: input.yaml, annotations.yaml, reference/ (extracted on demand)
eval/scripts/                   Setup + judge helper scripts (reference_judge.py, summary_report.py, setup/extract/collect/pin)
eval/config/pairwise-judge.md   Prompt file for the pairwise baseline-comparison judge
skills/docs-workflow-pipeline-diagnostics/scripts/pipeline_diagnostics.py   (reconciled — shared with the diagnostics skill)
eval/scripts/diagnostics_judge.py                                          Deterministic diagnostics judges (module type)
tests/eval/                     Tests for the diagnostics judges + pipeline_diagnostics deltas
```

### Judge inventory

| Judge | Type | Question it answers | Scale |
|---|---|---|---|
| `files_exist` | inline `check` | Did the pipeline produce ≥1 AsciiDoc file? | pass/fail |
| `step_results_valid` | inline `check` | Did requirements/planning/writing complete with valid `step-result.json`? | pass/fail |
| `pipeline_complete` | inline `check` | Did the workflow reach `status: completed`? | pass/fail |
| `cost_budget` | builtin | Did the run stay under the per-case budget? | pass/fail |
| `doc_quality` | LLM `prompt` | Is the documentation well-written, accurate, well-structured? | 1–5 |
| `intent_alignment` | LLM `prompt` | Does the output address the JIRA ticket's ask + acceptance criteria? | 1–5 |
| `reference_comparison` | `module` (`reference_judge.py`) | How closely does output match the human gold standard? | 1–5 |
| `diagnostics_*` | `module` (`diagnostics_judge.py`) | Pipeline health: failures, bottlenecks, context pressure, evidence grounding | scored + optional LLM reflection |
| `pairwise` | LLM `prompt_file` | Head-to-head vs a baseline run (only with `--baseline`) | A / B / tie |

Reading `doc_quality`, `intent_alignment`, and `reference_comparison` together is the point: high quality + low intent = well-written but off-target; high intent + low reference = addresses the ticket but diverges from the human approach; all three high = near production-ready.

### Relationship to the quality gate

The `doc_quality` and `intent_alignment` judges here are the **same judges the in-pipeline quality gate uses** (`skills/docs-workflow-quality-gate`). That is deliberate: the eval is the instrument for measuring and calibrating the gate offline, not just a parallel scorer. Two known weaknesses of the gate are directly addressable by this harness:

- **Single-judge boundary noise.** The gate's pass/fail pivots on one Opus `intent_alignment` score at the 3/4 cut (`passed = ia_score >= 4`), where LLM scoring variance is highest. Running the eval's 8 baselines repeatedly gives us the score spread around that boundary — turning "the gate might be noisy" into a measured number we can drive down. Judge-variance measurement is an explicit intended use of the harness, not a side effect.
- **No gold-standard anchor.** The gate has no comparison to human output. The eval's `reference_comparison` supplies one, so gate pass/fail can be **calibration-checked** against it: if the gate passes docs that score low against the human MR, the threshold is miscalibrated. The 8 human-anchored cases exist partly to enable exactly this cross-check.

A later opportunity (not in the four phases below): the gate's deterministic, quote-grounded **per-AC coverage check** could be lifted into the eval as a `check`/`module` judge — a more verifiable intent signal than a raw LLM score. Noted here so the design leaves room for it; it is out of scope for the initial build.

### Dataset

Eight human-anchored cases, one JIRA ticket each. Every kept case pins `docs_repo.sha` to the **pre-merge state** of a real tech-writer MR, so the pipeline starts from the same point the human did — a fair head-to-head. Gold-standard AsciiDoc is extracted on demand from the merged MR (not committed).

| Case | Ticket | Gold standard (GitLab MR) | Annotations |
|---|---|---|---|
| 001 | RHOAIENG-45969 | MR 2664 | present |
| 006 | RHAIENG-2388 | MR 2697 | **backfill** |
| 007 | RHAIENG-4485 | MR 2691 | **backfill** |
| 008 | RHAIENG-2620 | MR 2380 | present |
| 009 | RHAIENG-1550 | MR 2104 | **backfill** |
| 010 | RHAIENG-653 | MR 1938 | **backfill** |
| 011 | RHOAIENG-16840 | MR 2680 | present |
| 012 | RHOAIENG-40664 | MR 2574 | present |

**Dropped** (weaker, self-referential baselines): `002`, `004`, `005` — these used `docs_repo.sha: HEAD` with pipeline-generated ground truth (not a human MR), and `005` used the retired multi-repo `source_repo` list shape. `003` was already dropped upstream.

Each case's `input.yaml` carries: `ticket`, `source_repo` (url + sha), `docs_repo` (url + sha + branch, pinned pre-merge), `workflow: docs-workflow`, `options.format: adoc`, and `ground_truth` (tier + source MR). `annotations.yaml` carries the ticket `intent`, `acceptance_criteria`, `audience`, and `scope` used by `intent_alignment`.

### Diagnostics judge reconciliation

`pipeline_diagnostics.py` exists in two diverged copies: this repo's (with iteration-loop detection) and the CCS copy (with context-window/token estimation — `total_estimated_tokens`, `context_window_pct`, per-step and heaviest-step token estimates). `diagnostics_judge.py` **depends on the CCS token fields**. The reconciliation is a **two-way merge**: add the CCS token-estimation output to this repo's script while keeping the iteration-loop detection, so the single shared script serves both the diagnostics skill and the new judges. This is the one non-mechanical step and is TDD-guarded against the existing `tests/test_pipeline_diagnostics.py` plus the ported diagnostics tests.

## Configuration

`eval/eval.yaml` (v1.20.0 schema) key settings:

| Setting | Value | Notes |
|---|---|---|
| `skill` | `docs-skills:docs-orchestrator` | The pipeline under test |
| `execution.mode` | `case` | One ticket per invocation |
| `execution.arguments` | `{ticket} --source-code-repo {source_repo_url} --docs-repo-path {docs_repo_path}` | `docs_repo_path` resolved by setup script to a worktree at the pinned SHA |
| `execution.timeout` | `5400` | 1h30m; complex tickets with review cycles run long |
| `execution.max_budget_usd` | `50` | Per case |
| `execution.parallelism` | `3` | Concurrent cases |
| `models.skill` | `claude-opus-4-6` | Pipeline under test — 4.6 is available to everyone who runs the harness (4.8 is not) |
| `models.judge` | `claude-opus-4-6` | Stable model for consistent scoring across runs |
| `models.hook` | `claude-haiku-4-5` | Answers AskUserQuestion prompts cheaply |
| `permissions.allow` | `Read, Write, Edit, Bash, Glob, Grep, Skill, Agent, AskUserQuestion` | `Skill`/`Agent` required for the nested pipeline |
| `permissions.deny` | `mcp__*` | No MCP in headless runs |

Thresholds: the three inline checks + `cost_budget` require `min_pass_rate: 1.0`; `doc_quality`/`intent_alignment` require `min_mean: 3.0`; `pairwise` is informational (no threshold).

## Implementation phases

Each phase is an independently runnable increment — `/eval-run` works at the end of every phase.

### Phase 1 — Walking skeleton
Rewrite the placeholder `eval/eval.yaml` to the v1.20.0 schema targeting `docs-skills:docs-orchestrator` with current models and permissions. Wire the three inline `check` judges (`files_exist`, `step_results_valid`, `pipeline_complete`) and the `cost_budget` builtin. Add one case (001) with a minimal setup path. **Exit criterion:** `/eval-run` executes case 001 end-to-end and reports structural-check results.

### Phase 2 — Diagnostics module judges
Reconcile `pipeline_diagnostics.py` (two-way merge, TDD). Add `eval/scripts/diagnostics_judge.py` (5 deterministic judges + optional LLM reflection) and `tests/eval/` (reconciled against the existing `tests/test_pipeline_diagnostics.py`). Wire the diagnostics judges as `module` judges in `eval.yaml`. **Exit criterion:** diagnostics tests pass; judges produce scores on a collected run.

### Phase 3 — Quality judges + gold standard
Port `doc_quality`, `intent_alignment`, and `reference_comparison` (+ `eval/scripts/reference_judge.py`). Port the setup/extract/collect/pin scripts as-is (glab + GitLab). Build the full 8-case dataset, backfilling `annotations.yaml` for 006/007/009/010. **Exit criterion:** a full run scores all eight cases on all quality dimensions, with `reference_comparison` populated from extracted gold standards.

### Phase 4 — Baseline + reporting
Add the `pairwise` judge (`eval/config/pairwise-judge.md`) and `eval/scripts/summary_report.py`. Document the baseline creation/comparison workflow and the case schema + template in `eval/README.md`. **Exit criterion:** a branch run can be compared against a committed baseline, and the README lets a new user add a case and run the eval.

## Open questions

None blocking. Confirm during implementation: exact `docs-orchestrator` argument wiring for pinned source-repo SHAs (Phase 1), and whether any Phase-3 judge is better served by a harness builtin (e.g. `output_completeness`) than a ported custom judge.

# Pipeline Evaluation Harness

An evaluation suite that scores the `docs-skills:docs-orchestrator` pipeline end-to-end against a fixed set of human-authored baselines, so we can measure documentation quality, intent alignment, and pipeline health across changes to the skills, prompts, and models.

Built on the [agent-eval-harness](https://github.com/opendatahub-io/agent-eval-harness) plugin (v1.20.0+). This repo supplies only the eval **config**, **dataset**, and a few **local judges/scripts** — the harness itself is an installed dependency, not vendored code.

See [specs/eval-harness.md](../specs/eval-harness.md) for the full design.

## Prerequisites

- `glab` authenticated to `gitlab.cee.redhat.com` (VPN connected) — the dataset reads gold standards from merged internal GitLab MRs and writes worktrees against the internal `openshift-ai-documentation` repo
- `JIRA_API_TOKEN` and `JIRA_EMAIL` environment variables set (JIRA access)
- The `agent-eval-harness` and `docs-skills` plugins installed in Claude Code

This eval is Red Hat internal in practice: the internal GitLab URLs and ticket IDs are auth-gated, not secret, so they are committed as-is. The only rule is **never commit secrets** — tokens stay in environment variables.

## One-time setup

```bash
bash eval/scripts/setup.sh
```

This does two things:

- Clones the docs repo (cached at `eval/.docs-repo-cache/`, multi-GB, cached after first run) and checks out a per-case worktree at each case's pinned `docs_repo.sha`
- Extracts human-written gold-standard AsciiDoc from merged GitLab MRs into each case's `reference/` directory (requires `glab` auth)

Re-run `bash eval/scripts/setup.sh` between eval runs — the worktrees get modified during pipeline execution and need to be reset.

## Running the eval

**Quick run** (a single case, for iterating on a skill/prompt/judge change):

```bash
/eval-run --model claude-opus-4-6 --cases case-001-rhoaieng-45969
```

**Full run** (all 8 gold-standard cases, for milestone validation — pre-merge, release candidates):

```bash
/eval-run --model claude-opus-4-6
```

The report lands at `eval/runs/<run-id>/report.html`. Key files inside a run directory:

- `summary.yaml` — per-case scores and aggregate metrics
- `analysis.md` — automated analysis with recommendations
- `run_result.json` — execution metadata (cost, duration, tokens)
- `cases/<case-id>/` — per-case artifacts and outputs

## What the judges measure

### Structural checks

| Judge | Type | What it checks | Scale |
|---|---|---|---|
| `files_exist` | inline `check` | Pipeline produced at least one AsciiDoc file | pass/fail |
| `step_results_valid` | inline `check` | requirements/planning/writing completed with valid `step-result.json` | pass/fail |
| `pipeline_complete` | inline `check` | Workflow reached `status: completed` | pass/fail |
| `budget_check` | builtin (`cost_budget`) | Run stayed under the per-case budget | pass/fail |

### Diagnostics (pipeline health)

| Judge | Type | Question it answers | Scale |
|---|---|---|---|
| `pipeline_health` | `module` | Any step failures or crashes? | scored |
| `evidence_quality` | `module` | Is documentation grounded in code evidence? | scored |
| `review_quality` | `module` | Did technical/style review cycles converge? | scored |
| `validation_quality` | `module` | Did validation steps run and pass? | scored |
| `planning_fidelity` | `module` | Did writing follow the plan? | scored |
| `diagnostics_reflection` | `module` + LLM | Reflection over the deterministic diagnostics scores | scored |

Diagnostics judges live in `eval/scripts/diagnostics_judge.py`, built on `pipeline_diagnostics.py` (shared with the `docs-workflow-pipeline-diagnostics` skill).

### Quality dimensions

| Judge | Type | Question it answers | Scale |
|---|---|---|---|
| `doc_quality` | LLM `prompt` | Is the documentation well-written, accurate, well-structured? | 1-5 |
| `intent_alignment` | LLM `prompt` | Does the output address the JIRA ticket's ask + acceptance criteria? | 1-5 |
| `reference_comparison` | `module` (`reference_judge.py`) | How closely does the output match the human gold standard? | 1-5 |

Reading these three together tells you more than any single number:

- High `doc_quality` + low `intent_alignment` — well-written but off-target
- High `intent_alignment` + low `reference_comparison` — addresses the ticket but diverges from the human approach
- All three high — near production-ready

`reference_comparison` only scores cases with an extracted `reference/` directory. `intent_alignment` requires `annotations.yaml` per case.

### Run comparison

| Judge | Type | What it checks | Scale |
|---|---|---|---|
| `pairwise` | LLM `prompt_file` | Head-to-head comparison against a baseline run (only with `--baseline`) | A wins / B wins / tie |

## Managing baselines

Create a baseline after merging a significant change (new pipeline step, architectural change, model upgrade) — not for small prompt/threshold tweaks, which should compare against the existing baseline instead.

**Creating a baseline** (run on `main` after the change has merged):

```bash
git checkout main
git pull
bash eval/scripts/setup.sh
/eval-run --model claude-opus-4-6 --run-id baseline-v1
```

**Comparing a branch against the baseline:**

```bash
git checkout your-feature-branch
bash eval/scripts/setup.sh
/eval-run --model claude-opus-4-6 --baseline baseline-v1
```

Increment the baseline name (`baseline-v2`, `baseline-v3`, ...) each time you cut a new one; keep old baselines around for historical comparison.

## Dataset

Eight human-anchored cases under `eval/cases/`, one JIRA ticket each. Every case pins `docs_repo.sha` to the pre-merge state of a real tech-writer MR, so the pipeline starts from the same point the human did — a fair head-to-head.

| Case | Ticket | Gold standard (GitLab MR) |
|---|---|---|
| case-001-rhoaieng-45969 | RHOAIENG-45969 | MR 2664 |
| case-006-rhai-eng-2388 | RHAIENG-2388 | MR 2697 |
| case-007-rhai-eng-4485 | RHAIENG-4485 | MR 2691 |
| case-008-rhai-eng-2620 | RHAIENG-2620 | MR 2380 |
| case-009-rhai-eng-1550 | RHAIENG-1550 | MR 2104 |
| case-010-rhaieng-653 | RHAIENG-653 | MR 1938 |
| case-011-rhoaieng-16840 | RHOAIENG-16840 | MR 2680 |
| case-012-rhoaieng-40664 | RHOAIENG-40664 | MR 2574 |

Each case directory has:

- `input.yaml` — `ticket`, `source_repo` (url + sha), `docs_repo` (url + sha + branch, pinned pre-merge), `workflow`, `options.format`, `ground_truth` (tier + source MR); `source_repo_url` and `docs_repo_path` are added by the setup scripts
- `annotations.yaml` — the ticket `intent`, `acceptance_criteria`, `audience`, and `scope`, used by `intent_alignment`
- `reference/` — extracted gold-standard AsciiDoc (not committed, generated by `eval/scripts/extract-gold-standard.sh`)

## Adding a case

1. Copy `eval/cases/TEMPLATE/` to `eval/cases/case-NNN-<ticket-lower>/` and fill in `input.yaml`
2. Run `bash eval/scripts/pin-docs-repo.sh <case-dir>` to pin `docs_repo.sha` to the pre-merge state of the gold-standard MR
3. Run `bash eval/scripts/setup-eval-worktrees.sh` to check out the worktree and populate `docs_repo_path`
4. If the case has a gold-standard MR, add it to `eval/scripts/extract-gold-standard.sh` so `reference_comparison` has something to compare against
5. Add an `annotations.yaml` (ticket `intent`, `acceptance_criteria`, `audience`, `scope`) if you want `intent_alignment` scored

## Relationship to the quality gate

`doc_quality` and `intent_alignment` here are the **same judges the in-pipeline quality gate uses** (`skills/docs-workflow-quality-gate`). The eval is the instrument for measuring and calibrating that gate offline, not just a parallel scorer:

- **Judge variance.** The gate's pass/fail pivots on a single Opus `intent_alignment` score at the 3/4 cut (`passed = ia_score >= 4`), where LLM scoring variance is highest. Running the eval's 8 baselines repeatedly gives us the score spread around that boundary — turning "the gate might be noisy" into a measured number to drive down.
- **Calibration against a gold-standard anchor.** The gate has no comparison to human output; the eval's `reference_comparison` supplies one. Gate pass/fail can be calibration-checked against it: if the gate passes docs that score low against the human MR, the threshold is miscalibrated. The 8 human-anchored cases exist partly to enable exactly this cross-check.

## Troubleshooting

**Cases timing out** — increase `execution.timeout` in `eval.yaml`. Complex tickets with many requirements and review cycles can exceed 1 hour.

**LLM judge returns low or missing scores** — check that `eval/scripts/collect-docs-repo-output.sh` ran between execution and collection. Without it, the judge doesn't see the AsciiDoc output written to the external docs repo.

**`reference_comparison` returns null** — run `bash eval/scripts/extract-gold-standard.sh` to (re-)populate `reference/`. Cases without a `reference/` directory are skipped.

**Worktree conflicts on re-run** — re-run `bash eval/scripts/setup.sh` to reset worktrees; they get modified during pipeline execution.

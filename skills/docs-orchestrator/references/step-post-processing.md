# Step-Specific Post-Processing

After each step completes, apply the rules below. When rules reference sidecar fields, read from `steps.<step-name>.result` in the progress file (already recorded in the after-step logic). If the sidecar was missing, fall back to parsing the step's primary output file where noted.

## requirements

- Log the `title` field: `"Requirements extracted: <title>"`
- Record `requirement_count` from the sidecar. Log: `"Requirements: <requirement_count> requirements discovered"`
- Evaluate `when: has_many_requirements` for any deferred steps (see [`when: has_many_requirements` condition](../SKILL.md#when-has_many_requirements-condition))
- If `options.source` is `null` → run [Post-requirements source resolution](../SKILL.md#post-requirements-source-resolution). This may change `deferred` steps to `pending` or `skipped`

## code-analysis

- Log: `"Code analysis completed: N modules, N relationships, languages: <languages_detected>"`
- Record `repo_path` from the sidecar for downstream steps
- **Multi-repo code analysis**: If `options.additional_sources` is non-empty, run code-analysis for each additional repo sequentially. For each additional source entry (indexed starting at 1):
  1. Derive the repo name: `basename(additional_source.repo_path)`
  2. Invoke the code-analysis step skill with a custom output dir that includes the index to avoid name collisions:
     ```
     Skill: docs-workflow-code-analysis, args: "--repo <additional_source.repo_path> --ticket <ticket> --output-dir <base_path>/code-analysis-<index>-<repo-name>"
     ```
  3. Log: `"Additional code analysis completed for <repo-name>"`
  These additional analyses are sub-tasks of the primary code-analysis step — do not create separate progress file entries. If an additional repo analysis fails, log a warning and continue (do not fail the entire code-analysis step)

## pr-analysis

- Log: `"PR analysis completed: PR #<pr_number> — N modules affected"`

## planning

- Log: `"Planning completed: N modules"`
- If `module_count` is 0, **warn**: `"Planning produced 0 modules — the plan may be empty. Review plan.md before continuing."` Ask the user whether to proceed or stop. If the user chooses to stop: mark the planning step as `failed` in the progress file, set the workflow status to `"failed"`, delete the active workflow marker (`.agent_workspace/.active-workflow`), log `"Planning stopped by user after 0 modules — workflow cancelled."`, and halt without running subsequent steps

## writing

- If `result.files` is empty or missing, **warn**: `"Writing step produced no files."` Mark the `create-merge-request` step as `skipped` with `skip_reason: "no_files"` and record `result.commit_sha: null`, `result.branch: null`, `result.pushed: false`, `result.url: null`, `result.action: "skipped"`, `result.platform: "unknown"`, `result.skipped: true`. Log: `"Skipping create-merge-request: no files to commit."`

## technical-review

- After the [Technical review iteration](../SKILL.md#technical-review-iteration) loop completes, re-evaluate `when: has_many_requirements` Phase 2 for the quality-gate step (see [`when: has_many_requirements` condition](../SKILL.md#when-has_many_requirements-condition))

## create-merge-request

- Record `result.url`, `result.pushed`, and `result.branch`. If `result.pushed` is false and `result.skipped` is false, log warning: `"create-merge-request: branch was not pushed."` If `result.url` is present, record it for the Completion summary

## create-jira

- Record `result.jira_url` and `result.jira_key` for the Completion summary

## quality-gate

- Log: `"Quality gate: intent_alignment=<N>/5, passed=<true|false>, coverage=<covered>/<total>, gaps=<N>"`
- If `passed` is false → enter [Quality gate iteration](../SKILL.md#quality-gate-iteration) loop

## pipeline-diagnostics

- Log: `"Pipeline diagnostics: context_pressure=<level> (score <N>), failures=<N>, bottlenecks=<N>"`
- If `high_severity_failure_count > 0`, **warn**: `"Pipeline had <N> high-severity failure(s). Review the diagnostic report at <base-path>/pipeline-diagnostics/report.md"`
- If `context_pressure_level` is `"high"` or `"critical"`, **warn**: `"Context pressure is <level>. Consider workflow splitting for future runs."`

## Construct arguments

Build the args string for the step skill. The orchestrator maps its user-facing flags to the internal flags that step skills expect: `--source-code-repo` → `--repo`, `--docs-repo-path` → `--repo-path`.

1. **Always**: `<ticket> --base-path <base_path>` — the ticket ID and the **absolute** base output path
2. **If source repo is resolved**: `--repo <repo_path>` — passed to steps that can use it
3. **From orchestrator context**: Step-specific args from parsed CLI flags:
   - `requirements`: `[--pr <url>]... [--repo <repo_path>]`
   - `code-analysis`: `--repo <repo_path>`
   - `pr-analysis`: `--repo <repo_path> [--pr <url>...]`
   - `writing`: `--format <adoc|mkdocs> [--draft] [--repo <repo_path>]... [--repo-path <path>]` — pass `--repo` for the primary source repo AND for each entry in `options.additional_sources` (in order)
   - `technical-review`: `[--repo <repo_path>]...` — pass `--repo` for the primary source repo AND for each entry in `options.additional_sources` (in order)
   - `style-review`: `--format <adoc|mkdocs>`
   - `create-merge-request`: `[--draft] [--repo-path <path>]`
   - `action-comments`: `[--pr <url>] [--include-resolved]` — pass `--pr` from `options.pr_urls[0]` or from `steps.create-merge-request.result.url` if available
   - `pipeline-diagnostics`: `[--ci-log <path>]` — pass `--ci-log` if `options.ci_log` is set

Step skills derive their own output folder and input folders from `--base-path` and step name conventions. No per-input flag wiring needed.

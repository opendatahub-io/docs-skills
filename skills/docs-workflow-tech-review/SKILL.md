---
name: docs-workflow-tech-review
description: Technical accuracy review with optional code-learner claim validation. Iteration logic owned by the orchestrator.
argument-hint: "<ticket> --base-path <path> [--repo <path>]... [--iteration <N>]"
allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Skill, Agent, WebSearch, WebFetch
---

# Technical Review Step

Codex: read [runtime compatibility](../../reference/runtime-compatibility.md).

Step skill for the docs-orchestrator pipeline. Performs a single review pass; the iteration loop is driven by the orchestrator.

## Execution

### 1. Prepare

```bash
python3 <skill-dir>/scripts/prepare_review.py <args>
```

Pass args **unquoted**. The script emits JSON on stdout. Key fields used below: `ticket`, `output_dir`, `output_file`, `claims_file`, `code_analysis_dir`, `repo_path`, `additional_repo_paths`, `additional_code_analysis_dirs`, `has_repo`, `has_code_analysis`, `source_files_block`, `prior_findings_file`. Stop on non-zero exit.

### 2. Claim validation (conditional)

**Skip this section entirely if `has_code_analysis` is false.** Proceed to step 3.

#### 2a. Extract claims

Decide which draft files the extractor needs to read. Files unchanged since the
last iteration keep their prior claims verbatim, so the reviewer sees a stable
set of claims across the run and their verdicts carry forward.

```bash
python3 <skill-dir>/scripts/plan_extraction.py \
  --base-path <base_path> --output-dir <output_dir> \
  --iteration <iteration> \
  [--repo <repo_path>]...
```

Emits `{extract_all, files_to_extract, unchanged_files, carried_claim_count,
changed_file_count, unchanged_file_count, carried_byte_share,
invalidation_reason}`. Cache state never fails the step — on iteration 1, a
missing manifest, or a source-repo change it returns every draft file and
behaves exactly as an ungated run. It does exit non-zero on an unusable
`--base-path` or `--output-dir`; stop on non-zero exit. Add `--report-only` to
keep the measurement while forcing full extraction (kill switch).

**Interpolate `files_to_extract` into `<file_list>` below.** Do not substitute
`<source_files_block>` here — the extractor must be given only the files in the
plan.

```
Agent:
  description: "Extract technical claims from docs for <ticket>"
  prompt: |
    Extract verifiable technical claims from documentation draft files.

    Extract claims from exactly these files:
    <file_list>

    Skip files whose names match release-notes patterns: `new-features-and-enhancements*`,
    `release-notes*`, `known-issues*`, `fixed-issues*`, `deprecated-removed*`. These contain
    announcement-level statements not verifiable against source code.
    For each remaining file, extract factual claims verifiable against code: function names, signatures, parameters, behavior descriptions, config options, defaults, API endpoints, CRD kinds, class names, return types, CLI flags, subcommands.

    Write the claims list to: <output_dir>/extracted-changed.json

    Format: JSON array of objects with fields: id, text, file, line.
    Assign each claim a unique `id`; any format is acceptable, ids are
    reassigned downstream.

    After writing, print ONLY: Written <output_dir>/extracted-changed.json
```

Merge the fresh claims with the carried ones. This assigns final claim ids and
refreshes the manifest:

```bash
python3 <skill-dir>/scripts/merge_extraction.py \
  --base-path <base_path> --output-dir <output_dir> \
  [--repo <repo_path>]...
```

Emits `{total_claims, carried, fresh, files_manifested}` and writes
`claims-list.json`. **Exits non-zero if the extractor produced no readable
output** — treat that as a step failure rather than continuing, because a
claims list built from carried claims alone would silently drop every changed
file's claims.

After the merge, prepare claims for validation:

```bash
python3 <skill-dir>/scripts/prepare_claims.py \
  --claims-list <output_dir>/claims-list.json \
  --output-dir <output_dir> \
  --prior-validation <claims_file>
```

Emits batch-summary JSON: `{total_claims, batch_count, batches: [{sanitized, file, count, claims_file}]}`. If `batch_count` is 0, skip 2b.

#### 2b. Dispatch code-questioner agents

For each batch, dispatch a code-questioner agent. Launch ALL in a **single message** (parallel).

```
Agent:
  subagent_type: docs-skills:code-questioner
  description: "Verify <count> claims from <file>"
  prompt: |
    Verify documentation claims from <file> against the source code.

    Read the claims to verify from: <claims_file>
    It is a JSON array of objects with fields: id, text, file, line.

    Read the learn-code analysis data from: <code_analysis_dir>/
    Files available: detection.json, registry.json, ONBOARDING.md, summaries/, relationships/

    REPO_PATH: <repo_path>

    OUTPUT_FILE: <output_dir>/batch-verdict-<sanitized>.json

    Write a JSON array of verdicts — one entry for EVERY claim (keyed by its `id`):
    [{"claim_id": "<id>", "claim_text": "<text>", "verdict": "supported|partially_supported|unsupported|no_evidence_found", "evidence": "<1-2 sentences with file:line refs>"}]

    IMPORTANT: You must produce a verdict for ALL claims. Do not skip any.
    After writing, print ONLY: Written <OUTPUT_FILE>
```

#### 2b-verify. Verify batch verdicts before merging

The `batch_count` from `prepare_claims.py` tells you how many verdict files to expect.

```bash
EXPECTED_BATCHES=<batch_count from prepare_claims.py output>
ACTUAL_BATCHES=$(ls ${OUTPUT_DIR}/batch-verdict-*.json 2>/dev/null | wc -l)
echo "Batch verdicts: ${ACTUAL_BATCHES}/${EXPECTED_BATCHES}"
```

**HARD GATE — do NOT proceed to step 2c (merge verdicts) until `ACTUAL_BATCHES` equals `EXPECTED_BATCHES`.** If agents are still running, wait. After all agents have returned, if verdict files are missing, log which batch sanitized names are missing — `merge_verdicts.py` assigns `no_evidence_found` fallback verdicts for claims in missing batches, so proceed to 2c after logging.

#### 2c. Merge verdicts — set `HAS_CLAIMS=true` after this completes

```bash
python3 <skill-dir>/scripts/merge_verdicts.py \
  --claims-list <output_dir>/claims-list.json --output-dir <output_dir> \
  --claims-file <claims_file> --summary-file <output_dir>/validation-summary.md \
  --code-analysis-dir <code_analysis_dir>
```

### 3. Dispatch reviewer

Use the Agent tool with `subagent_type: docs-skills:technical-reviewer` and **`run_in_background: false`** (the orchestrator must wait for the reviewer to finish before verifying output).

**Before dispatching:** If a prior `review.md` exists at `<output_file>`, **delete it**. This prevents the reviewer from reading stale findings from a prior iteration:

```bash
rm -f <output_file>
```

**Prompt:**

> Perform a technical review of the documentation drafts for ticket `<ticket>`.
> <source_files_block>
> Review all .adoc and .md files. Follow your standard review methodology.
> Save your review report to: `<output_file>`
>
> The report must include an `Overall technical confidence: HIGH|MEDIUM|LOW` line and a `Severity counts: critical=N significant=N minor=N sme=N` line.
>
> After writing the report file, do NOT print the review contents. Print ONLY these three lines:
>
> Written <output_file>
> Overall technical confidence: HIGH|MEDIUM|LOW
> Severity counts: critical=N significant=N minor=N sme=N

**[if iteration >= 2]** Prepend this paragraph to the prompt, before "Perform a technical review":

> **This is a re-review (iteration 2+).** A prior review found issues and fixes have been applied to the source files. Base your assessment on the current file content. If a `review.md` already exists at the output path below, do NOT read it — it will be overwritten.

**[if iteration >= 2 AND `prior_findings_file` is not null]** Also prepend, immediately after the re-review paragraph:

> **Prior findings:** Read `<prior_findings_file>` for a summary of what the previous iteration found, grouped by severity. For each prior finding, determine whether it is now **FIXED** or still **PERSISTS**, and state that status in your report. You may also report NEW findings, but prioritize verifying the prior findings over hunting for new minor issues.

**[if `has_prior_validation` is true]** Also prepend, after the re-review paragraph (or as the first prepended paragraph if iteration == 1):

> A prior claim-validation pass produced verdicts in `<claims_file>`. Use those verdicts to calibrate your review — claims marked `unsupported` deserve extra scrutiny, while `supported` claims are lower risk.

**[if `has_repo`]** Append: `Source code repository is available at <repo_path>.`

**[if `additional_repo_paths` non-empty]** Append: `Additional source code repositories: <list paths>` and `Additional code-learner analyses: <list additional_code_analysis_dirs>`

**[if HAS_CLAIMS]** Append:

> ## Claim Validation Evidence
> Read the validation summary from: `<output_dir>/validation-summary.md`
> Full results: `<claims_file>`
> Verdicts: `unsupported` = likely inaccurate (critical/significant), `no_evidence_found` = may need SME, `partially_supported` = identify wrong part, `supported` = lower risk.

### 4. Verify and write sidecar

Verify `<output_file>` exists and contains an `Overall technical confidence:` line. If missing, treat as step failure.

```bash
python3 <skill-dir>/scripts/write_step_result.py \
  --ticket "<ticket>" \
  --review-file "<output_file>" \
  --sidecar "<output_dir>/step-result.json" \
  --code-grounded <true if HAS_CLAIMS, else false> \
  --missing-batches "<comma-separated missing batch names from 2b-verify, or empty string if none>" \
  --iteration <iteration number from prepare_review.py output> \
  --extraction-plan "<output_dir>/extraction-plan.json"
```

---
name: docs-workflow-tech-review
description: Technical accuracy review of documentation drafts with optional code-learner validation. When code analysis is available, validates documentation claims against learn-code analysis data before dispatching the technical-reviewer agent. Iteration logic is owned by the orchestrator, not this skill.
argument-hint: "<ticket> --base-path <path> [--repo <path>]..."
allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Skill, Agent, WebSearch, WebFetch
---

# Technical Review Step

Step skill for the docs-orchestrator pipeline. Follows the step skill contract: **parse args → [run claim validation] → dispatch agent → write output**.

When code-learner analysis is available (from the `code-analysis` step), this step validates documentation claims against the analysis data by dispatching `code-questioner` agents. These validation results are passed to the `technical-reviewer` agent as pre-computed evidence, giving the reviewer concrete verdicts alongside its engineering judgment.

This skill performs a single review pass. The iteration loop (re-running with fixes between passes) is driven by the orchestrator skill, not this step skill.

## Arguments

- `$1` — JIRA ticket ID (required)
- `--base-path <path>` — Base output path (e.g., `.agent_workspace/proj-123`)
- `--repo <path>...` — Path to the source code repository (optional, repeatable, provided by orchestrator when available). The first `--repo` is the primary source repo. Additional `--repo` values are secondary repos with code-learner analysis at `<base-path>/code-analysis-<repo-name>/`

## Input

```
<base-path>/writing/
<repo-path>/ (optional — source code repo for code-grounded validation)
```

## Output

```
<base-path>/technical-review/review.md
<base-path>/technical-review/step-result.json
<base-path>/technical-review/claim-validation.json (when code-analysis available)
```

## Execution

### 1. Parse arguments

Extract the ticket ID, `--base-path`, and optional `--repo` value(s) from the args string.

Collect all `--repo` values. The first becomes the primary `REPO_PATH`. Additional values are stored in an `ADDITIONAL_REPO_PATHS` list.

Set the paths:

```bash
OUTPUT_DIR="${BASE_PATH}/technical-review"
OUTPUT_FILE="${OUTPUT_DIR}/review.md"
CLAIMS_FILE="${OUTPUT_DIR}/claim-validation.json"
CODE_ANALYSIS_DIR="${BASE_PATH}/code-analysis"
mkdir -p "$OUTPUT_DIR"
```

Set `HAS_REPO=true` if at least one valid `--repo` path was provided and exists as a directory. Otherwise `HAS_REPO=false`.

### 2. Determine source files

Read the writing step's sidecar at `${BASE_PATH}/writing/step-result.json` to determine the writing mode and file list.

**If the sidecar exists and `mode` is `"update-in-place"` with a non-empty `files` array:**

Build a `<SOURCE_FILES_BLOCK>` listing the files explicitly:

```
Source files — review each of these:
- `/absolute/path/to/file1.adoc`
- `/absolute/path/to/file2.adoc`
```

**Otherwise** (draft mode, missing sidecar, or empty files array):

Set `DRAFTS_DIR="${BASE_PATH}/writing"` and build the block as:

```
Source drafts location: `<DRAFTS_DIR>/`
```

### 3. Claim validation pre-scan (conditional)

**Skip this step entirely if no code-analysis data exists** (check `${CODE_ANALYSIS_DIR}/ONBOARDING.md`). Proceed directly to step 4.

When code-learner analysis is available from the code-analysis step, validate documentation claims against the analysis data before dispatching the reviewer agent.

#### Incremental validation (iterations 2+)

A verdict is a function of the claim text and the source code. Across iterations the source code never changes — only the documentation does — so claims the fix did not touch keep their prior verdicts, and only new or changed claims need re-validation. Step 3a always extracts fresh claims; step 3b then carries forward unchanged verdicts and validates only what changed. This gives the reviewer **fresh** evidence for exactly the claims the fix edited (a blunt all-or-nothing reuse would feed the reviewer stale verdicts for the very claims it needs to re-judge), while keeping re-validation proportional to the change.

#### 3a. Extract claims from draft documentation

Delegate claim extraction to a subagent so that full draft file content (~50-100KB) stays out of the orchestrator's context.

```
Agent:
  description: "Extract technical claims from docs for <TICKET>"
  prompt: |
    Extract verifiable technical claims from documentation draft files.

    <SOURCE_FILES_BLOCK>

    Read all .adoc and .md files from the source location above.
    For each file, extract factual claims that can be verified against code:
    - Function names, method signatures, parameter lists
    - Behavior descriptions ("X happens when Y")
    - Configuration options, environment variables, default values
    - API endpoints, resource types, CRD kinds
    - Class names, return types, data structures
    - Command-line flags, subcommands, option values

    Focus on claims that can be verified against source code.

    Write the claims list to: <OUTPUT_DIR>/claims-list.json

    Format:
    [
      {"id": "claim-1", "text": "The CreateCluster function accepts a ClusterConfig parameter", "file": "proc-creating-cluster.adoc", "line": 42},
      {"id": "claim-2", "text": "Authentication uses JWT tokens stored in the session cookie", "file": "con-auth-overview.adoc", "line": 15}
    ]

    After writing, print ONLY: Written <OUTPUT_DIR>/claims-list.json
```

After the agent completes, determine which claims need code validation and split them into per-doc-file batch files on disk. Both paths below print **only** counts and sanitized batch identifiers — never claim text — so claim details stay out of the orchestrator's context.

**Iteration 1** — no prior `claim-validation.json` exists in `$OUTPUT_DIR`. Batch all claims:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/split_claims.py \
  --claims-list <OUTPUT_DIR>/claims-list.json \
  --output-dir <OUTPUT_DIR>
```

**Iterations 2+** — a prior `claim-validation.json` exists. Carry forward unchanged verdicts and batch only the claims the fix changed:

```bash
# Drop stale batch files from the prior iteration (their claim ids no longer match).
rm -f <OUTPUT_DIR>/batch-claims-*.json <OUTPUT_DIR>/batch-verdict-*.json

# Diff fresh claims against the prior validation: write carried-forward verdicts
# (batch-verdict-carryover.json) and the changed/new claims (claims-to-validate.json).
python3 ${CLAUDE_SKILL_DIR}/scripts/incremental_claims.py \
  --claims-list <OUTPUT_DIR>/claims-list.json \
  --prior-validation <OUTPUT_DIR>/claim-validation.json \
  --output-dir <OUTPUT_DIR>
# prints: {"total_claims": N, "reused_count": N, "revalidate_count": N}

# Batch only the claims that need re-validation.
python3 ${CLAUDE_SKILL_DIR}/scripts/split_claims.py \
  --claims-list <OUTPUT_DIR>/claims-to-validate.json \
  --output-dir <OUTPUT_DIR>
```

In both cases `split_claims.py` emits a JSON object:

```json
{
  "total_claims": 12,
  "batch_count": 3,
  "batches": [
    {"sanitized": "proc-creating-cluster", "file": "proc-creating-cluster.adoc",
     "count": 2, "claims_file": "<OUTPUT_DIR>/batch-claims-proc-creating-cluster.json"}
  ]
}
```

This gives the orchestrator the batch list (sanitized name, doc filename, count, claims file path) — enough to dispatch one code-questioner agent per batch without loading any claim text into context. On iterations 2+ the batch list covers only the changed claims; if `revalidate_count` is `0`, `batches` is empty and step 3b dispatches no agents — the carried-forward verdicts alone feed the merge in step 3d.

#### 3b. Dispatch code-questioner agents for validation (batched by doc file)

For each doc-file batch (from the step 3a `batches` list), dispatch a single `code-questioner` agent that verifies ALL claims from that file. Launch ALL batch agents in a **single message** (parallel execution).

Each agent reads its claims AND the analysis data from disk, then writes its verdicts to a per-batch file. The agent prompt carries no claim text — only file paths — so the orchestrator's context stays lean (agent prompts are tiny and agent results are one-line confirmations).

For each batch (use its `sanitized`, `file`, `count`, and `claims_file` fields), use:

```
Agent:
  subagent_type: docs-skills:code-questioner
  description: "Verify <count> claims from <file>"
  prompt: |
    Verify documentation claims from <file> against the source code.

    Read the claims to verify from: <claims_file>
    It is a JSON array of objects with fields: id, text, file, line.

    Read the learn-code analysis data from: <CODE_ANALYSIS_DIR>/
    Files available:
    - detection.json
    - registry.json
    - ONBOARDING.md
    - summaries/ (per-module analysis)
    - relationships/ (cross-module coupling)

    REPO_PATH: <repo_path>

    OUTPUT_FILE: <OUTPUT_DIR>/batch-verdict-<sanitized>.json

    Write a JSON array of verdicts — one entry for EVERY claim in the claims file (keyed by its `id`):
    [
      {"claim_id": "<id>", "claim_text": "<text>", "verdict": "supported|partially_supported|unsupported|no_evidence_found", "evidence": "<1-2 sentences with file:line refs>"},
      ...
    ]

    IMPORTANT: You must produce a verdict for ALL claims. Do not skip any.
    After writing, print ONLY: Written <OUTPUT_FILE>
```

Use the batch's `sanitized` field (already computed by `split_claims.py`) for the `batch-verdict-<sanitized>.json` filename so it pairs with the batch claims file.

**Important:** All Agent calls MUST be in a single message so they run in parallel.

#### 3c. Collect verdicts from disk

After all code-questioner agents complete, verify which batch verdict files were written:

```bash
ls <OUTPUT_DIR>/batch-verdict-*.json 2>/dev/null | wc -l
```

Log: `"<found_count>/<batch_count> batch verdict files written to disk"`

For any missing batch verdict files (agent failed or was skipped), the merge script in step 3d creates fallback entries with verdict `no_evidence_found` for all claims in that batch.

#### 3d. Assemble claim-validation.json and validation summary via merge script

Assembling the validation output is deterministic JSON work — no judgment — so it runs as a script, not a subagent. The script reads `claims-list.json`, every `batch-verdict-*.json`, and the analysis `registry.json`, then writes both output files and prints only confirmation lines. The full validation data never enters the orchestrator's context. On iterations 2+ the `batch-verdict-*.json` set includes `batch-verdict-carryover.json` (the unchanged claims' carried-forward verdicts), so the merged output covers every claim — carried-forward and freshly re-validated alike.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/merge_verdicts.py \
  --claims-list <OUTPUT_DIR>/claims-list.json \
  --output-dir <OUTPUT_DIR> \
  --claims-file <OUTPUT_DIR>/claim-validation.json \
  --summary-file <OUTPUT_DIR>/validation-summary.md \
  --code-analysis-dir <CODE_ANALYSIS_DIR>
```

Any claim with no matching verdict (missing batch file or skipped claim) is filled in with verdict `no_evidence_found`, so every claim is always covered. The script prints:

```
Written <OUTPUT_DIR>/claim-validation.json
Written <OUTPUT_DIR>/validation-summary.md
```

Set `HAS_CLAIMS=true`.

### 4. Dispatch agent

**You MUST use the Agent tool** to invoke the `technical-reviewer` subagent. Do NOT read the agent's markdown file or attempt to perform the agent's work yourself — the agent has a specialized system prompt and must run as an isolated subagent.

**Agent tool parameters:**
- `subagent_type`: `docs-skills:technical-reviewer`
- `description`: `Technical review of documentation for <TICKET>`

**Prompt** (pass this as the `prompt` parameter to the Agent tool):

> Perform a technical review of the documentation drafts for ticket `<TICKET>`.
> <SOURCE_FILES_BLOCK>
> Review all .adoc and .md files. Follow your standard review methodology.
> Save your review report to: `<OUTPUT_FILE>`
>
> The report must include an `Overall technical confidence: HIGH|MEDIUM|LOW` line and a `Severity counts: critical=N significant=N minor=N sme=N` line.
>
> After writing the report file, do NOT print the review contents. Print ONLY these three lines:
>
> ```
> Written <OUTPUT_FILE>
> Overall technical confidence: HIGH|MEDIUM|LOW
> Severity counts: critical=N significant=N minor=N sme=N
> ```

**[Include only if HAS_REPO=true]** Append:

> Source code repository is available at `<REPO_PATH>`. You may read specific source files to verify technical claims in the documentation.

**[Include only if ADDITIONAL_REPO_PATHS is non-empty]** Append:

> Additional source code repositories are available for cross-verification:
> <for each path in ADDITIONAL_REPO_PATHS, output: "- `<path>`">
>
> Additional code-learner analyses (if available):
> <for each additional repo, if `<BASE_PATH>/code-analysis-<repo-name>/ONBOARDING.md` exists, output: "- `<BASE_PATH>/code-analysis-<repo-name>/`">
>
> Use these to verify claims that reference features outside the primary repository.

**[Include only if HAS_CLAIMS=true]** Append:

> ## Claim Validation Evidence
>
> Documentation claims have been validated against code-learner analysis of the source repository.
>
> Read the validation summary from: `<OUTPUT_DIR>/validation-summary.md`
> Full claim-by-claim results are at: `<CLAIMS_FILE>`
>
> **How to use this evidence:**
> - Claims with verdict `unsupported` are likely inaccurate — verify the evidence and flag as critical or significant issues
> - Claims with verdict `no_evidence_found` may reference features outside the analyzed modules — flag as SME verification needed
> - Claims with verdict `partially_supported` need targeted review — identify what part is wrong
> - Claims with verdict `supported` have analysis backing — still apply your engineering judgment but these are lower risk

### 5. Verify output

After the agent completes, verify the review report exists at `<OUTPUT_FILE>`.

The review report **must** include an `Overall technical confidence: HIGH|MEDIUM|LOW` line. If this line is missing from the output, the orchestrator will treat it as a step failure.

The report should also include a `Severity counts: critical=N significant=N minor=N sme=N` line. This enables the orchestrator to skip unnecessary iteration when only SME-verification items remain.

### 6. Write step-result.json

Write the sidecar with the script. It greps only the confidence and severity-count lines from `<OUTPUT_FILE>` (the full report never enters context), auto-detects the iteration from any prior sidecar, and stamps a real wall-clock timestamp:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/write_step_result.py \
  --ticket "<TICKET>" \
  --review-file "<OUTPUT_FILE>" \
  --sidecar "${BASE_PATH}/technical-review/step-result.json" \
  --code-grounded <true|false>
```

Pass `--code-grounded true` when the reviewer received claim-validation evidence (`HAS_CLAIMS`), otherwise `--code-grounded false`. The script writes:

```json
{
  "schema_version": 1,
  "step": "technical-review",
  "ticket": "<TICKET>",
  "completed_at": "<ISO 8601 timestamp>",
  "confidence": "<HIGH|MEDIUM|LOW>",
  "severity_counts": {"critical": 0, "significant": 0, "minor": 3, "sme": 2},
  "iteration": 1,
  "code_grounded": true
}
```

Behavior:
- `iteration` auto-detects from the existing sidecar (prior iteration + 1, or `1` on the first pass), so it stays correct across the orchestrator's review/fix loop without an extra argument.
- `severity_counts` are integers; each defaults to `0` when the severity line is absent.
- If the `Overall technical confidence:` line is missing, the script exits non-zero — the orchestrator treats a missing confidence as a step failure (see step 5).
- `code_grounded` records whether the reviewer received claim-validation evidence (freshly computed or carried forward).

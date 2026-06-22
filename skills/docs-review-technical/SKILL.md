---
name: docs-review-technical
description: Technical accuracy review and code-aware validation with confidence scoring. Supports local branch review, PR/MR review with optional inline comment posting, and code-aware technical validation against source code repos. MUST BE USED when the user asks to validate documentation against code, check technical accuracy, verify commands/APIs/configs in docs match source code, or run a technical review. Also use when the user provides a --code URL or mentions code-aware review.
argument-hint: "[--local | --pr <url> [--post-comments]] [--code <url>] [--fix] [--threshold <0-100>]"
allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Skill, Agent, WebSearch, WebFetch, AskUserQuestion
---

# Technical Accuracy and Code-Aware Review

Multi-agent technical accuracy review with confidence-based scoring and optional code-aware validation against source repositories.

For style guide compliance and modular docs review, use `docs-review-style`.

## Modes

| Arguments | Mode | Description |
|-----------|------|-------------|
| `--local` | Local review | Review doc changes in current branch vs base branch |
| `--pr <url>` | PR/MR review | Review doc changes in a GitHub PR or GitLab MR |
| `--pr <url> --post-comments` | PR/MR + post | Review and post inline comments to PR/MR |
| *(no arguments)* | Interactive | AskUserQuestion gathers mode and options |

For actioning unresolved review comments on a PR/MR, use the `action-comments` skill.

## Global Options

| Option | Description |
|--------|-------------|
| `--threshold <0-100>` | Confidence threshold for reporting issues (default: 80) |
| `--code <url>` | Code repository URL for technical validation (repeatable). Enables Agent 2. |
| `--fix` | Auto-fix high-confidence issues (>=65%), then interactively walk through remaining |
| `--jira <TICKET-123>` | Auto-discover code repos from JIRA ticket (uses `jira-reader`). Enables Agent 2. |
| `--ref <branch>` | Git ref to check out in `--code` repos (default: default branch). Applies to preceding `--code`. |

## Interactive mode — no arguments provided

**STOP. You MUST follow steps 1-3 IN ORDER. Call AskUserQuestion at each step — do not skip or infer answers. Do not start the review pipeline until all inputs are gathered.**

### Step 1: Mode selection (AskUserQuestion)

Ask: "What type of technical review?" Options: **Review local branch changes** (→ `--local`, skip to Step 3) | **Review a PR/MR** (→ Step 2A).

### Step 2A: PR/MR details (AskUserQuestion)

Ask (textInput): "Enter the PR/MR URL:" → set `--pr <url>`. Ask: "Post inline comments?" (No/Yes) → if Yes, append `--post-comments`. Ask (textInput): "Source code repo URL for code-aware validation? (blank to skip)" → append `--code <url>`. Ask (textInput): "JIRA ticket for auto-discovering repos? (blank to skip)" → append `--jira <ticket>`.

### Step 3: Fix mode (AskUserQuestion)

Ask: "Apply automatic fixes?" (No/Yes) → if Yes, append `--fix`. Proceed to review pipeline.

## Agent Assumptions

These apply to ALL agents and subagents:

- All tools are functional. Do not test tools or make exploratory calls.
- Only call a tool if required. Every tool call should have a clear purpose.
- The confidence threshold is 80 by default (adjustable with `--threshold`).

---

# Multi-Agent Review Pipeline

The `--local` and `--pr` modes share the same pipeline. The difference is how files are discovered and how results are delivered.

## Step 1: Pre-flight Checks

### For --pr mode

Launch a haiku agent to run pre-flight checks using `git-pr-reader`. Stop if any condition is true (still review Claude-generated PRs):

- **PR/MR is closed or draft**: Check the PR/MR state from the platform API.
- **No documentation files changed**: Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py files "${PR_URL}" --json` and check if any changed files end with `.adoc` or `.md`.
- **Claude already commented**: Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py comments "${PR_URL}" --include-resolved --json` and check if any comment `author` matches Claude's username.

### For --local mode

```bash
CURRENT_BRANCH=$(git branch --show-current)
# Detect base branch from remote default, fall back to local refs
BASE_BRANCH=$(git rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's|^origin/||')
if [ -z "$BASE_BRANCH" ]; then
    if git show-ref --verify --quiet refs/heads/main; then
        BASE_BRANCH="main"
    elif git show-ref --verify --quiet refs/heads/master; then
        BASE_BRANCH="master"
    else
        echo "ERROR: Cannot determine base branch"; exit 1
    fi
fi
if [ "$CURRENT_BRANCH" = "$BASE_BRANCH" ]; then
    echo "ERROR: Currently on $BASE_BRANCH. Switch to a feature branch first."; exit 1
fi
```

## Step 2: Discover Documentation Files

### For --local mode

```bash
git diff --name-only "$BASE_BRANCH"...HEAD | sort -u | grep -E '\.(adoc|md)$' > /tmp/docs-review-doc-files.txt || true
DOC_FILES=$(wc -l < /tmp/docs-review-doc-files.txt)
```

### For --pr mode

Use `git-pr-reader` to get changed files:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py files "${PR_URL}" --json | \
    python3 -c "import json,sys; files=[f['path'] for f in json.load(sys.stdin) if f['path'].endswith(('.adoc','.md'))]; print('\n'.join(files))" > /tmp/docs-review-doc-files.txt
```

### For both modes

If no documentation files found, report and exit.

## Step 2a: Extract Changed Line Ranges

Extract the exact changed line ranges so review agents only flag issues in changed content.

### For --local mode

```bash
git diff "$BASE_BRANCH"...HEAD -- $(cat /tmp/docs-review-doc-files.txt | tr '\n' ' ') | \
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/extract_changed_ranges.py \
    --context 3 -o /tmp/docs-review-changed-ranges.json
```

### For --pr mode

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py diff "${PR_URL}" | \
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/extract_changed_ranges.py \
    --context 3 -o /tmp/docs-review-changed-ranges.json
```

The output is a JSON file mapping each file to either `"new"` (entire file is in scope) or a list of `[start, end]` line ranges (inclusive, 1-based). Read and store this as `CHANGED_RANGES` for use in Steps 4 and 8.

## Step 3: Summarize Changes

Launch a sonnet agent to view changes and return a summary noting:
- Which files are new vs modified
- Whether files appear to be concepts, procedures, references, or assemblies
- Any structural patterns (modular docs, release notes)

For `--pr` mode: `python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py diff "${PR_URL}"`
For `--local` mode: `git diff "$BASE_BRANCH"...HEAD -- $(cat /tmp/docs-review-doc-files.txt)`

## Step 4: Agent 1 — Technical Accuracy and Consistency

- `subagent_type`: `technical-reviewer`
- `model`: `opus`

Follow the full technical review process: doc type detection, reviewer persona (developer/architect lens), 6 review dimensions, confidence scoring, and output format. Use `jira-reader`, `git-pr-reader`, and `article-extractor` skills to cross-check technical claims. Do not duplicate style or formatting checks.

Returns issues with: `file`, `line`, `description`, `reason`, `confidence` (0-100), `severity` (error/warning/suggestion).

For `--pr` mode, use `python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py extract` for deterministic line numbers.

**Important**: The agent file describes a JIRA-based drafts workflow for standalone use. In this context, ignore JIRA/drafts sections — review changed files from the diff and return issues in the format above.

**CRITICAL — Scope constraint**: Include the contents of `/tmp/docs-review-changed-ranges.json` in the agent's prompt. Instruct the agent:

> **You MUST only flag issues on lines that fall within the changed ranges below. For files marked `"new"`, all lines are in scope. For files with line ranges, ONLY lines within those ranges are in scope. Do NOT flag issues on lines outside these ranges — they are pre-existing content that is not part of this review.**
>
> Changed ranges: `{CHANGED_RANGES}`

## Step 5: Agent 2 — Code-Aware Technical Scan (conditional)

**Only runs when**: `--code <url>` is provided, or code repos can be auto-discovered from the PR URL, JIRA ticket context, or `:code-repo-url:` AsciiDoc attributes in the changed files.

**Dispatched as**: a general-purpose agent.

Workflow:

1. **Clone repos** to `/tmp/tech-review/<repo-name>/` using full history (needed for `git log` search):

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py clone <repo-url> \
     --output-dir /tmp/tech-review/<repo-name>/ --depth 0 [--ref <ref>]
   ```

   **Repository discovery priority**: `--code` (explicit) > PR URL linked repos > `--jira` ticket linked repos > `:code-repo-url:` AsciiDoc attributes.

   If `--jira` is provided, fetch the ticket using `jira-reader` and extract linked PR/MR URLs and repository references. Parse repo URLs from PR links and JIRA ticket fields.

2. **Extract references** from doc files:
   ```bash
   mapfile -t DOC_FILES < /tmp/docs-review-doc-files.txt
   python3 ${CLAUDE_SKILL_DIR}/scripts/extract_refs.py "${DOC_FILES[@]}" --output /tmp/tech-review-refs.json
   ```

3. **Validate claims against code** — For each cloned repo, check if learn-code analysis exists:
   ```bash
   ls /tmp/tech-review/repo-name/.code-learner/ONBOARDING.md 2>/dev/null
   ```

   **If learn-code analysis exists**, read the module summaries from `.code-learner/summaries/` to get `public_api`, `dependencies`, and `data_flow` for each module. Cross-reference documentation claims against these structured summaries.

   **If learn-code analysis does NOT exist**, use direct source file reading: read the extracted references from `/tmp/tech-review-refs.json` and use Grep/Read to verify each reference against the actual source files. This is slower but works without prior analysis.

   For each claim in the documentation (function names, parameter types, configuration options, API endpoints, class names), verify against the source using the best available method (analysis data or direct reading). Record findings as:
   - **verified**: claim matches source code
   - **inaccurate**: claim contradicts source code (include what the source actually says)
   - **stale**: referenced symbol exists but has changed (renamed, deprecated, different signature)
   - **unverifiable**: cannot determine from available sources

4. **Extract API surface** — For each cloned repo: if learn-code analysis exists (`.code-learner/summaries/`), read `public_api` from module summaries. Otherwise, use Grep to find exported symbols (Go: `^func [A-Z]`, `^type [A-Z]`; Python: `^def [a-z]`/`^class [A-Z]` excluding `_` prefixed). Build an API reference list.

5. **Triage results** — Review the claim validation findings and API reference list against the extracted references (`/tmp/tech-review-refs.json`). Apply the structured triage pipeline from Step 6 (below). Use Read and Grep on source files to verify ambiguous results.

6. Return issues in the standard format: `file`, `line`, `description`, `reason`, `confidence`, `severity`. Include the code evidence in `reason`.

## Step 6: Structured Triage (Evidence-Based Classification)

Process ALL findings through a 5-pass classification pipeline (scope filtering → claim validation → API surface comparison → source file verification → cross-reference and dedup). See [triage pipeline](references/triage-pipeline.md) for the full pass-by-pass process and signal quality filter.

**Assigning severity**: `High` = users will hit errors. `Medium` = misleading but not blocking. `Low` = cosmetic or informational.

## Step 7: Validate All Issues

For each issue from Steps 4-6, launch parallel subagents to validate:
- Wrong command/flag -> verify the correct command exists in the code
- Stale API reference -> confirm the API was renamed or removed
- Broken code example -> verify the example doesn't compile/run as documented
- Incorrect config value -> confirm the actual default in source

Use opus subagents for structural/technical issues.

## Step 8: Filter Issues

Remove issues that:
- Were not validated in Step 7
- Score below the confidence threshold (default: 80)
- **Fall outside the changed line ranges from Step 2a** — For each issue, check that its `line` number falls within the `CHANGED_RANGES` for its file. For files marked `"new"`, all lines pass. For files with `[[start, end], ...]` ranges, the issue's line must fall within at least one range. Drop any issue that fails this check, regardless of confidence or severity.

## Step 9: Whole-Repo Anti-Pattern Scan (conditional)

**Only runs when Agent 2 ran.** Catches issues grounded review may miss.

**Scan scope**: `.adoc` and `.md` files in the parent directories of the files listed in `/tmp/docs-review-doc-files.txt`.

**9a: Anti-pattern scan** — For each confirmed issue from Agent 2, use Grep to search the broader doc tree for additional occurrences of the same error pattern (e.g., same wrong flag name, same stale config key, same renamed path).

**9b: Blast radius scan** — For each issue from Step 6, search the doc tree for additional occurrences. Record every file and line.

## Step 10: Generate Report and Present Results

Write full report to `/tmp/docs-review-technical-report.md` (see [report template](references/report-template.md) for format). Output a terminal summary: source, files reviewed, issues count (above/below threshold), numbered issue list with `file:line [confidence] — description (source)`, and the report path.

### For --local mode: Offer to Apply Changes

After the summary, offer to apply fixes for errors. Describe suggestions but let the user decide.

### For --pr mode without --post-comments

Stop here.

### For --pr mode with --post-comments

If NO issues found, write a summary JSON to `/tmp/docs-review-summary.json` with a "no issues found" message and post via `git_pr_reader.py post "${PR_URL}" /tmp/docs-review-summary.json --review-type technical`.

If issues found, continue to Step 11.

## Step 11: Post Inline Comments (--post-comments only)

Get deterministic line numbers:
```bash
LINE=$(python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py extract "${PR_URL}" "path/to/file.adoc" "pattern from the issue")
```

Build comments JSON and post:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py post "${PR_URL}" /tmp/docs-review-comments.json --review-type technical
```

For each comment: brief description with evidence from source code, include corrected values for small fixes, describe larger fixes without inline code. **Only ONE comment per unique issue.**

## Step 11a: Fix Mode (--fix only)

**Phase A — Auto-fix**: For each issue with confidence >=65%, apply the fix using the Edit tool.

**Phase B — Interactive walkthrough**: For each issue with confidence <65%, present to user with issue details (file, line, current/suggested values, evidence). Ask via AskUserQuestion: **Apply** | **Modify** | **Skip** | **Delete section**.

See [report template](references/report-template.md) for the fix-mode report sections, the full report format, and feedback guidelines.

---

# Notes

- Use `python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py` for all Git platform interactions. Use `extract` for deterministic line numbers — never guess
- Use Bash with heredoc/cat for /tmp files (not Write). Include source code evidence in each issue's `reason`
- If learn-code analysis exists (`.code-learner/`), use ONBOARDING.md and module summaries. Otherwise use Read/Grep directly
- Vale linting is NOT part of this review — use `docs-review-style`

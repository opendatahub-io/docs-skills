---
name: docs-ticket-readiness
description: Assess JIRA ticket readiness for the docs-orchestrator workflow. Checks description quality (via LLM), PR/source linkage, metadata completeness, and relationship context (2-level graph traversal). Outputs structured JSON verdict with actionable gaps. Use when you want to check if a JIRA ticket has enough information before starting a docs workflow.
model: claude-haiku-4-5@20251001
argument-hint: "<ticket> [--jql <query>] [--output-dir <path>] [--max-results <n>] [--skip-description-check] [--comment]"
allowed-tools: Read, Bash, Glob, Grep
---

# Ticket Readiness Assessment

Standalone skill that evaluates whether a JIRA ticket has sufficient information for the docs-orchestrator workflow to succeed. Checks four dimensions and produces a structured verdict.

## Parse arguments

- `$1` — JIRA ticket key (e.g., PROJ-123). Mutually exclusive with `--jql`.
- `--jql <query>` — JQL query for batch mode. Mutually exclusive with positional ticket key.
- `--output-dir <path>` — Write per-ticket markdown reports to this directory.
- `--max-results <n>` — Max tickets for JQL mode (default: 10).
- `--skip-description-check` — Skip LLM description quality assessment (mechanical checks only).
- `--comment` — Post readiness verdict as a JIRA comment after assessment.
- `--ready-statuses <list>` — Comma-separated JIRA statuses considered docs-ready (default: Done, Closed, Resolved, In Review, Code Review, Release Pending).

Determine mode:
- If first arg looks like a JIRA key (matches `^[A-Z][A-Z0-9]+-\d+$`): single ticket mode with `--issue <key>`.
- If `--jql` is present: batch mode.
- If neither: ask the user for a ticket key.

## Step 1: Run mechanical checks

Run the readiness script to fetch JIRA data and perform Dimensions 2–4 (PR linkage, metadata, relationships):

```bash
uv run --script ${CLAUDE_SKILL_DIR}/scripts/ticket_readiness.py \
  --issue <TICKET_KEY> \
  --plugin-root ${CLAUDE_PLUGIN_ROOT} \
  [--ready-statuses <list>]
```

For batch mode:

```bash
uv run --script ${CLAUDE_SKILL_DIR}/scripts/ticket_readiness.py \
  --jql "<JQL_QUERY>" \
  --max-results <N> \
  --plugin-root ${CLAUDE_PLUGIN_ROOT} \
  [--ready-statuses <list>]
```

Capture the JSON output. If the output contains an `"error"` key at the top level, report the error to the user and STOP.

## Step 1.5: PR relevance assessment

If PRs were discovered in Step 1 (i.e., `dimensions.pr_source_linkage.checks.git_links_present.status` is `pass` or `warn`), assess whether each PR is actually relevant to the JIRA ticket.

1. Collect all PR URLs from the Step 1 JSON. Look in:
   - `dimensions.pr_source_linkage.checks.git_links_present.detail` (parse PR URLs)
   - `relationship_map.children[].pr` entries
   - `relationship_map.documented_by[].pr` entries

2. For each unique PR URL, dispatch a subagent (using the Agent tool) **in parallel** (all Agent calls in one message). Each subagent should:

   a. Run the git PR reader to fetch PR info:
   ```bash
   uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py info <PR_URL>
   ```

   b. Compare the PR title and description against the JIRA ticket summary and description (from `description_text` in the Step 1 JSON).

   c. Return a single-line JSON verdict:
   ```json
   {"url": "<PR_URL>", "relevant": true, "reason": "PR adds OpenClaw deployment manifests matching the ticket's scope"}
   ```
   or:
   ```json
   {"url": "<PR_URL>", "relevant": false, "reason": "PR is a CI pipeline fix unrelated to the feature"}
   ```

3. Collect all subagent verdicts and merge into the output:
   - Add `dimensions.pr_source_linkage.checks.pr_relevance` with:
     - `status`: `pass` if all PRs relevant, `warn` if any irrelevant, `info` if no PRs to check
     - `detail`: summary (e.g., "2/2 PRs relevant" or "1/3 PRs irrelevant: github.com/org/repo/pull/99")
     - `verdicts`: array of the per-PR verdict objects

4. If a subagent fails (e.g., PR is private or token missing), set that PR's verdict to `{"url": "...", "relevant": null, "reason": "Could not fetch PR info"}` and do not count it toward pass/warn.

## Step 2: Description quality assessment (Dimension 1)

If `--skip-description-check` was passed, set `description_quality` to `{"status": "skipped"}` for all tickets and skip to Step 3.

Otherwise, for each ticket in the output where `dimensions.description_quality` is `null`:

1. Extract `description_text` from the JSON.
2. If `description_text` is empty or very short (under 20 characters), set:
   ```json
   {"status": "fail", "score": 1, "gaps": ["Description is empty or a one-liner"]}
   ```
3. Otherwise, assess the description against this rubric:

**Rubric for description quality assessment:**

| Signal | Weight | Pass | Warn | Fail |
|--------|--------|------|------|------|
| Specificity | High | Describes a concrete change/feature with technical detail | Vague but has some context | One-liner or empty |
| User impact | Medium | Explains what users need to know or do differently | Implied but not stated | No user-facing context |
| Acceptance criteria | Medium | Has explicit ACs or clear definition of done | Some criteria but informal | None present |
| Scope clarity | Low | Clear boundaries of what's in and out of scope | Partially bounded | Unbounded or ambiguous |

Produce a verdict as JSON with this exact structure:
```json
{"status": "pass|warn|fail", "score": 1-5, "gaps": ["gap description 1", "gap description 2"]}
```

Rules:
- Score 4-5 → status "pass"
- Score 3 → status "warn"
- Score 1-2 → status "fail"
- `gaps` should list specific, actionable gaps (e.g., "No acceptance criteria specified", "User impact not described"). Empty array if status is "pass".

4. Merge the verdict into the ticket's JSON under `dimensions.description_quality`.

## Step 3: Compute overall verdict

For each ticket, compute `overall_status` from all four dimensions:
- `ready` — no fails in any dimension
- `ready_with_warnings` — no fails, but at least one warning
- `not_ready` — at least one fail in any dimension

Dimensions with status `null`, `skipped`, or `info` do not count toward the verdict.

## Step 4: Post JIRA comment (if --comment)

If `--comment` was passed:

**For batch mode (multiple tickets):** First confirm with the user:

> "This will post readiness comments to N JIRA tickets. Continue?"

If the user declines, skip comment posting.

**Post comments:** Pipe the final merged JSON (with description_quality filled in) into the script's `--post-comment` mode:

```bash
echo '<MERGED_JSON>' | uv run --script ${CLAUDE_SKILL_DIR}/scripts/ticket_readiness.py --post-comment
```

Report the comment posting results to the user.

## Step 5: Write markdown reports (if --output-dir)

If `--output-dir` was passed, run the script with the output-dir flag. The script writes per-ticket markdown reports to `<output-dir>/<TICKET>-readiness.md`.

Alternatively, if the script was already run with `--output-dir` in Step 1, the reports are already written. Confirm the output path to the user.

## Step 6: Present results

**Single ticket — formatted summary:**

```
## PROJ-123: Add widget API documentation

**Verdict: READY** (or READY WITH WARNINGS / NOT READY)

| Dimension | Status | Details |
|-----------|--------|---------|
| Description quality | PASS (4/5) | — |
| PR/source linkage | PASS | 2 PRs found (2/2 relevant) |
| Metadata | WARN | Release note type not set |
| Relationships | PASS | Parent: PROJ-100 (Epic) |

### Relationship Map
- Parent: PROJ-100 (Epic: Widget Platform)
  - PROJ-123 (Story: Add widget API documentation) ← this ticket
  - PROJ-458 (Story: Widget docs) — sibling
- Children:
  - PROJ-456 (Sub-task: Widget API endpoints) — PR: github.com/org/repo/pull/55
  - PROJ-457 (Sub-task: Widget UI components)
- Documented by:
  - PROJ-789 (Task: Update API reference) — PR: github.com/org/repo/pull/60
```

**Batch — summary table:**

```
## Readiness Assessment: N tickets

| Ticket | Summary | Verdict | Gaps |
|--------|---------|---------|------|
| PROJ-123 | Add widget API | READY | — |
| PROJ-456 | Fix auth bug | NOT READY | No PRs, missing fix version |
| PROJ-789 | Update config | READY (warnings) | Release note type not set |

**Summary:** 1 ready, 1 ready with warnings, 1 not ready
```

Remove `description_text` from the JSON before displaying — it is internal data used for agent assessment, not for the user.

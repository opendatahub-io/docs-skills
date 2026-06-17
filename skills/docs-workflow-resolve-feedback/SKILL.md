---
name: docs-workflow-resolve-feedback
description: Resolve documentation quality gaps and SME review comments via targeted rewrites. Reads quality-gate gaps and MR review comments, builds a structured feedback brief, and dispatches docs-writer in fix mode. Does not rewrite content that was not flagged. Iteration logic is owned by the orchestrator, not this skill.
argument-hint: <ticket> --base-path <path> [--repo <path>]...
allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Skill, Agent
---

# Resolve Feedback

Targeted rewrite step that addresses two sources of feedback:

1. **Quality gate gaps** — AC items missed by the writing step, classified by code evidence status
2. **SME review comments** — inline comments on the MR/PR from human reviewers

Both sources produce the same shape of input: *what's wrong with specific sections of the docs*. This skill builds a combined feedback brief and dispatches the docs-writer agent in fix mode.

## Arguments

- `$1` — Ticket ID (required)
- `--base-path <path>` — Base output path (required)
- `--repo <path>` — Source code repo path (optional, repeatable). Passed through to writing fix mode for code verification

## Execution

### 1. Parse arguments

Extract `TICKET` from `$1`, `BASE_PATH` from `--base-path`, and collect all `--repo` paths.

### 2. Read quality gate gaps

Read `${BASE_PATH}/quality-gate/step-result.json`. Extract:
- `gaps` array — classified gap list with evidence status and actions
- `rationales.doc_quality` — full doc quality judge rationale
- `rationales.intent_alignment` — full intent alignment judge rationale (contains per-AC coverage assessments, specific missing artifacts, scope analysis)

If the file does not exist or `gaps` is empty, set `QUALITY_GAPS = []`.

### 3. Read SME review comments

Check for an MR/PR URL in `${BASE_PATH}/create-merge-request/step-result.json`:
- If `url` exists and `skipped` is false:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py \
  comments "${MR_URL}" --json
```

Parse the JSON output. Filter to:
- Unresolved comments only (`resolved == false`)
- Exclude bot authors (already handled by git-pr-reader)

If no MR exists, set `SME_COMMENTS = []`.

### 4. Check for feedback

If both `QUALITY_GAPS` and `SME_COMMENTS` are empty, there is nothing to resolve. Write a minimal step-result.json and exit:

```json
{
  "schema_version": 1,
  "step": "resolve-feedback",
  "ticket": "<TICKET>",
  "completed_at": "<ISO 8601>",
  "gaps_resolved": 0,
  "gaps_deferred": 0,
  "sme_comments_resolved": 0,
  "sme_comments_deferred": 0,
  "files_modified": [],
  "sources": []
}
```

### 5. Build feedback brief

Create `${BASE_PATH}/resolve-feedback/feedback-brief.md` with the following structure:

```markdown
# Feedback Brief for <TICKET>

## Intent Alignment Judge Assessment

[Insert rationales.intent_alignment from quality-gate/step-result.json verbatim.
This contains per-AC-item coverage assessments with severity levels, specific missing
artifacts, scope balance analysis, and audience alignment — all directly actionable.]

## Doc Quality Judge Assessment

[Insert rationales.doc_quality from quality-gate/step-result.json verbatim.]

## Classified Gaps with Recommended Actions

[For each gap in QUALITY_GAPS:]

### Gap: <ac_item>
- **File**: <file> (if provided by judge)
- **Section**: <section> (if provided by judge)
- **Evidence status**: <evidence_status>
- **Action**: <action description>

[Map action codes to instructions:]
- `document_as_unsupported` → "Add a note stating that this capability is not supported in this release. Place it in the most relevant existing module — do not create a new module."
- `expand_with_evidence` → "Expand the existing content with available code evidence. Check the source repo for relevant API fields, flags, or config options."
- `add_missing_section` → "This content was in the plan but was not included in the writing output. Add the missing section based on the requirements and plan."
- `investigate` → "This gap could not be classified. Review the requirements and determine whether to document it or note it as out of scope."

## SME Review Comments

[For each comment in SME_COMMENTS:]

### Comment from @<author> on `<path>`:<line>
- **Body**: <comment body>
- **Action**: Address this review comment. Apply the fix if clear and unambiguous. If the comment requires broader context or domain knowledge you don't have, note it as deferred.

## Priority

Address gaps in this order:
1. Items the judge flagged as "missing" or "barely covered" — these are the largest scoring deductions
2. Items flagged as "weakly covered" or "partially covered" — expand existing content
3. Scope rebalancing — if the judge flagged over-indexing on one area, tighten that section rather than expanding others
4. SME comments — inline fixes from human reviewers
```

The key design principle: include the **full judge rationale text**, not just the classified gap list. The rationale contains per-AC-item severity assessments ("partially covered", "weakly covered", "barely covered", "mostly missing"), names specific missing artifacts (e.g., "no InferenceService CR manifest"), identifies scope imbalance, and diagnoses audience gaps. This gives the fix agent precise, nuanced instructions instead of flat action codes.

### 6. Dispatch docs-writer in fix mode

Invoke the writing skill with `--fix-from` pointing to the feedback brief:

```
Skill: docs-workflow-writing, args: "<TICKET> --base-path <BASE_PATH> [--repo <REPO_PATH>]... --fix-from <BASE_PATH>/resolve-feedback/feedback-brief.md"
```

Pass `--repo` for the primary source repo and each additional source (same flags as the original writing invocation) so the fix agent can verify against source code.

### 7. Write step-result.json

After the writing fix completes, write `${BASE_PATH}/resolve-feedback/step-result.json`:

```json
{
  "schema_version": 1,
  "step": "resolve-feedback",
  "ticket": "<TICKET>",
  "completed_at": "<ISO 8601>",
  "gaps_resolved": <count of quality gate gaps addressed>,
  "gaps_deferred": <count of gaps with action "investigate" that could not be resolved>,
  "sme_comments_resolved": <count of SME comments addressed>,
  "sme_comments_deferred": <count of SME comments not addressable>,
  "files_modified": [<list of files modified by the fix>],
  "sources": ["quality-gate", "sme-comments"]
}
```

Set `sources` to only include the feedback types that were present (omit `"sme-comments"` if no MR comments, omit `"quality-gate"` if no gaps).

Count resolved vs deferred based on the fix agent's output — if the agent skipped an item (reported it as needing broader context), count it as deferred.

## Output

- `resolve-feedback/feedback-brief.md` — the combined feedback document passed to the writer
- `resolve-feedback/step-result.json` — structured result for orchestrator consumption

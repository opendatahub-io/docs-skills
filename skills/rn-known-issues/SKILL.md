---
name: rn-known-issues
description: Check known issue status for a release version. Shows which known issues are still open (document in Known Issues) and which are resolved (move to Fixed Issues or remove). Use when asked to check known issues, audit release notes known issues, or find resolved known issues for a version.
allowed-tools: Read, Bash, Grep, Glob
---

# Release Notes: Known Issue Audit

Audit known issues for a release version. Produces a categorized report showing which known issues remain open and which have been resolved since the previous release.

## Arguments

- `$1` — Target fix version (required, e.g., `rhoai-3.4.1`)
- `--project` — Jira project key (default: `RHOAIENG`)
- `--previous` — Previous GA version to check for resolved known issues (auto-inferred if not provided)

## Version inference

When `--previous` is not provided, infer the previous GA version from the target:

| Target pattern | Previous GA |
|----------------|-------------|
| `rhoai-X.Y.Z` (z-stream) | `rhoai-X.Y` |
| `rhoai-X.Y` (GA) | `rhoai-X.(Y-1)` |
| `rhoai-X.Y.EAn` | `rhoai-X.Y` |

Examples:
- Target `rhoai-3.4.1` → previous = `rhoai-3.4`
- Target `rhoai-3.5` → previous = `rhoai-3.4`
- Target `rhoai-3.4.2` → previous = `rhoai-3.4`

## Execution

Run these JQL queries via the Atlassian MCP (`searchJiraIssuesUsingJql`) with `cloudId = "redhat.atlassian.net"`.

If the Atlassian MCP is unavailable or unauthenticated, fall back to jira-reader:

```bash
# Claude Code
uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/jira-reader/scripts/jira_reader.py --jql "<JQL>" --fetch-details

# Cursor
uv run --script skills/jira-reader/scripts/jira_reader.py --jql "<JQL>" --fetch-details
```

### Query 1: New known issues in the target version (still open)

```
project = {PROJECT} AND "Release Note Type" = "Known Issue"
  AND fixVersion = "{TARGET_VERSION}"
  AND statusCategory != Done
ORDER BY priority DESC, key ASC
```

These are **active known issues** — document them in the Known Issues section of the release notes.

### Query 2: New known issues in the target version (already resolved)

```
project = {PROJECT} AND "Release Note Type" = "Known Issue"
  AND fixVersion = "{TARGET_VERSION}"
  AND statusCategory = Done
ORDER BY key ASC
```

These were found and fixed within the same release cycle. Decide whether they need a Known Issue entry (with a note that it's fixed) or can be omitted.

### Query 3: Previously documented known issues now resolved

```
project = {PROJECT} AND "Release Note Type" = "Known Issue"
  AND fixVersion = "{PREVIOUS_VERSION}"
  AND statusCategory = Done
ORDER BY key ASC
```

These are **resolved known issues from the prior release** — candidates for:
- Moving to "Fixed Issues" in the target release notes
- Removal from the Known Issues section

### Query 4: Previously documented known issues still open (carry forward)

```
project = {PROJECT} AND "Release Note Type" = "Known Issue"
  AND fixVersion = "{PREVIOUS_VERSION}"
  AND statusCategory != Done
ORDER BY priority DESC, key ASC
```

These **remain open** — they must stay in the Known Issues section.

## Required fields

Request these fields in each query:

```
summary, status, fixVersions, customfield_10785, customfield_10807, customfield_10783, resolution, priority
```

Field reference:
- `customfield_10785` — Release Note Type
- `customfield_10807` — Release Note Status (Done, In Progress, Proposed, Approved)
- `customfield_10783` — Release Note Text (ADF format)

## Output format

Present results as a markdown report:

```markdown
# Known Issue Audit: {TARGET_VERSION}

Project: {PROJECT}
Previous version: {PREVIOUS_VERSION}
Date: {TODAY}

## Still-open known issues in {TARGET_VERSION} (document these)

| Key | Summary | Priority | RN Status |
|-----|---------|----------|-----------|
| ... | ...     | ...      | ...       |

**Count:** N issues

## Resolved known issues in {TARGET_VERSION} (found-and-fixed same cycle)

| Key | Summary | Resolution | RN Status |
|-----|---------|------------|-----------|
| ... | ...     | ...        | ...       |

**Count:** N issues

## Resolved from {PREVIOUS_VERSION} (move to Fixed Issues)

| Key | Summary | Resolution | RN Status | RN Text filled? |
|-----|---------|------------|-----------|-----------------|
| ... | ...     | ...        | ...       | Yes/No          |

**Count:** N issues — these can be removed from Known Issues and optionally added to Fixed Issues.

## Carry-forward from {PREVIOUS_VERSION} (still open)

| Key | Summary | Priority | Status | RN Status |
|-----|---------|----------|--------|-----------|
| ... | ...     | ...      | ...    | ...       |

**Count:** N issues — these remain in the Known Issues section.

## Summary

- New known issues to document: N
- Previously known issues now fixed: N
- Carry-forward (still open): N
- Release note text missing: N (list keys)
```

## Release Note Text check

For each issue, check if `customfield_10783` (Release Note Text) has content beyond the template skeleton (`Cause:\nConsequence:\nWorkaround:\nResult:`). Flag issues where the text is empty or only contains the template headings.

## Usage examples

**Z-stream audit — what's changed since the last GA?**

> "Check known issues for rhoai-3.4.1"

Audits `rhoai-3.4.1` against the inferred previous version `rhoai-3.4`. Shows any new known issues in 3.4.1, which 3.4 known issues are now fixed, and which carry forward.

**GA release — what resolved from the prior GA?**

> "Run rn-known-issues for rhoai-3.5 --project RHOAIENG"

Audits `rhoai-3.5` against `rhoai-3.4`. Useful at GA time to see which long-standing known issues finally got fixed.

**Explicit previous version — check across multiple z-streams**

> "Check known issues for rhoai-3.4.2 --previous rhoai-3.3"

Overrides version inference to compare against an older baseline. Useful when you want to see everything resolved since 3.3 (skipping the intermediate 3.4 GA).

**Different project**

> "Audit known issues for rhoai-3.4.1 --project RHAIENG"

Same workflow against the Red Hat AI Engineering project instead of OpenShift AI.

**Pre-release checklist**

> "Before we ship rhoai-3.4.1, check known issues — are any still open that should block the release?"

The agent will focus on Query 1 (still-open known issues in the target version) and flag Blocker/Critical priorities.

## Notes

- The Jira project for Red Hat OpenShift AI Engineering is `RHOAIENG` (not `RHAIENG`, which is a separate project).
- Fix version naming: `rhoai-X.Y` for GA releases, `rhoai-X.Y.Z` for z-stream patches.
- Known Issue is a value of the "Release Note Type" field (`customfield_10785`), not a separate field or label.

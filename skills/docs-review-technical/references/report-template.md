# Report Format and Templates

## Fix-Mode Report Sections

When `--fix` is used, the report at `/tmp/docs-review-technical-report.md` includes additional sections:

### Issues Auto-Fixed

| ID | File:Line | Issue | Evidence | Before | After |
|----|-----------|-------|----------|--------|-------|
| AF-1 | file.adoc:23 | Flag renamed | cli_validation | `--enable-feature` | `--feature-enable` |

### Issues Interactively Resolved

| ID | File:Line | Issue | Action |
|----|-----------|-------|--------|
| IR-1 | file.adoc:45 | Stale config key | Applied suggested fix |
| IR-2 | file.adoc:67 | Wrong default | Modified by user |

### Issues Skipped

| ID | File:Line | Issue | Confidence |
|----|-----------|-------|------------|
| SK-1 | file.adoc:91 | Config key not found | 55% |

---

## Full Report Format

```markdown
# Technical Review Report

**Source**: [Branch: <branch> vs <base> | PR/MR URL]
**Date**: YYYY-MM-DD

## Grounded Review Summary

| Metric | Count |
|--------|-------|
| Claims extracted | X |
| Supported | A |
| Partially supported | B |
| Unsupported | C |
| No evidence found | D |

## API Surface Summary

| Metric | Count |
|--------|-------|
| Files processed | X |
| Total entities | Y |
| Entities in docs | Z |
| Potentially undocumented | N |

## Code Repositories

| Repo | Ref | Clone Path | Source |
|------|-----|------------|--------|
| repo-name | main | /tmp/tech-review/repo-name | --code |

## Triage Summary

| Pass | Description | Items Processed | Issues Flagged |
|------|-------------|-----------------|----------------|
| Pass 1 | Scope filtering | X | Y |
| Pass 2 | Claim verdict analysis | X | Y |
| Pass 3 | API surface comparison | X | Y |
| Pass 4 | Source file verification | X | Y |
| Pass 5 | Cross-reference and deduplicate | X | Y |

## Summary

| Metric | Count |
|--------|-------|
| Files reviewed | X |
| Errors (must fix) | Y |
| Warnings (should fix) | Z |
| Suggestions (optional) | N |

## Files Reviewed

### 1. path/to/file.adoc

**Type**: CONCEPT | PROCEDURE | REFERENCE | ASSEMBLY

#### Technical Accuracy

| Line | Severity | Issue | Evidence |
|------|----------|-------|----------|

#### Code Validation (if Agent 2 ran)

| Line | Severity | Issue | Evidence | Verdict |
|------|----------|-------|----------|---------|

Show specific value mismatches (e.g., "Docs: pool_size=10, Code: pool_size=5"), unsupported claims, and import path errors. Only report items where grounded review returned `unsupported` or `no_evidence_found` with concrete evidence, or where the API surface shows a missing/renamed entity.

---

## Required Changes

1. **file.adoc:23** — Description (evidence) [verdict: unsupported]

## Suggestions

1. **file.adoc:91** — Description [verdict: no_evidence_found]

## Undocumented API Surface (if Agent 2 ran)

Entities found in API surface but not referenced in reviewed documentation:

| Type | Name | Source File | Signature |
|------|------|-------------|-----------|
| function | list_resources | src/app.py:12 | def list_resources() |
| class | ExampleClient | src/client.py:2 | class ExampleClient |

## Out-of-Scope References

| Tool | Count |
|------|-------|
| sudo | X |
| kubectl | Y |

---

*Generated with [Claude Code](https://claude.com/claude-code)*
```

## Report Rules

**Sections**: Errors = must fix. Warnings = should fix. Suggestions = optional.

**Do NOT include**: positive findings, executive summaries, compliance percentages, references sections.

## Feedback Guidelines

- **In scope**: Content changed in the branch or PR/MR. **Out of scope**: Unchanged content, enhancement requests.
- **Required** (blocks merging): Incorrect commands, wrong API references, broken code examples, stale config values.
- **Optional** (does not block): Minor accuracy improvements, additional context. Mark with **[SUGGESTION]**.
- Include source code evidence for each issue. For recurring issues: "[GLOBAL] This issue occurs elsewhere."

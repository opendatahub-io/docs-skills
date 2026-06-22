# Output Templates

Markdown templates for human-readable output files produced by learn-code steps.

## registry.md (Step 2)

```markdown
# Module Registry — <repo-name>

| Module | Purpose | Complexity | Likely Imports | Analysis Question |
|--------|---------|------------|----------------|-------------------|
| <module> | <purpose> | <complexity> | <imports> | <question truncated to 80 chars> |
```

## summary.md (Step 3)

```markdown
# Module Analysis Summary — <repo-name>

## Overview

- **Language**: <primary_language>
- **Modules analyzed**: <count>
- **Full analysis**: <count>
- **API-guided**: <count>
- **API-only**: <count>
- **Failed**: <count>

## Modules

### <module-name>

**Purpose**: <purpose>
**Priority**: <onboarding_priority>
**Analysis depth**: <full | api-guided | api-only>
**Public API**: <comma-separated list>
**Dependencies**: <comma-separated list>
**Key gotcha**: <first gotcha or "None">

---
```

## relationships.md (Step 4)

```markdown
# Cross-Module Relationships — <repo-name>

## Summary

- **Pairs analyzed (agent)**: <priority_count>
- **Pairs (lightweight)**: <lightweight_count>
- **Tight couplings**: <count>
- **Loose couplings**: <count>

## Tight Couplings

### <module_a> ↔ <module_b>

- **Type**: <coupling_type>
- **Description**: <description>
- **Shared types**: <list>
- **Risk**: <risk>

## Loose Couplings

| Pair | Type | Strength |
|------|------|----------|
| <a> ↔ <b> | <type> | loose |
```

## Completion Summary

```
Learn-Code Analysis Complete
================================
Repository:    <REPO_NAME>
Language:      <primary_language>
Modules:       <module_count>
Relationships: <pairs_analyzed>

Output files:
  Detection:     <BASE_PATH>/detection/
  Registry:      <BASE_PATH>/module-registry/
  Analysis:      <BASE_PATH>/module-analysis/
  Relationships: <BASE_PATH>/relationships/
  Onboarding:    <BASE_PATH>/synthesis/ONBOARDING.md

Workflow:      <BASE_PATH>/workflow/learn-code_<REPO_NAME>.json
```

## Suggested Next Steps

- Read the onboarding guide: `cat <BASE_PATH>/synthesis/ONBOARDING.md`
- View the dependency graph: `cat <BASE_PATH>/relationships/dependency-graph.json`
- Query the codebase: `/docs-skills:query-code "your question" --repo <REPO_PATH>`

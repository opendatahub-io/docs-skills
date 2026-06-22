# Structured Triage Pipeline (Evidence-Based Classification)

Process ALL claim validation findings and API reference data through a classification pipeline. Do NOT skip this step or use ad-hoc exploration.

## Pass 1: Scope filtering (commands only)

For each command in the extracted references (`/tmp/tech-review-refs.json`), classify the binary as external or in-scope. External system commands (sudo, dnf, oc, kubectl, docker, git, curl, etc.) cannot be validated against the code repo — tag as `out-of-scope` and skip further analysis.

## Pass 2: Claim validation analysis

For each validated claim:
- `inaccurate` claims → Flag as likely incorrect. Read source to understand the discrepancy. High confidence (>=80%) when source clearly contradicts the claim.
- `unverifiable` claims → Check if the claim references something that should be in the repo. Could be wrong repo, or reference lives elsewhere. Medium confidence (50-70%).
- `stale` claims → Medium-high confidence. Cross-reference the actual current implementation to determine what changed.
- `verified` claims → No issue. Skip.

## Pass 3: API surface comparison

Compare the extracted references (`/tmp/tech-review-refs.json`) against the API reference list:
- For each API, class, or function referenced in the docs, check if it appears in the API reference. If absent, flag as potentially stale or renamed. Confidence: 60-80%.
- For each entity in the API reference not mentioned in the doc references, note as potentially undocumented. Severity: Low-Medium. Confidence: 60-80%.

## Pass 4: Read source files

For items flagged in passes 2-3 with confidence >=50%, read the actual source file to confirm the issue. Do not report issues based solely on analysis output without verifying against the source.

## Pass 5: Cross-reference and deduplicate

Merge findings from passes 2-4:
- If a claim flagged in Pass 2 also has a missing API in Pass 3, consolidate into a single issue with the stronger evidence.
- If an entity flagged as undocumented in Pass 3 is found via additional Grep searches in the source, downgrade or remove.
- Remove duplicate findings that flag the same underlying problem from different angles.

## Assigning severity

`High` = users will hit errors (broken commands, missing APIs). `Medium` = misleading but not blocking (wrong names, stale options). `Low` = cosmetic or informational (undocumented features, formatting).

## Signal quality filter

**Flag issues where:**
- Documentation will actively mislead users (wrong commands, broken examples, incorrect terminology)
- Code examples contain wrong default values, renamed flags, or missing parameters
- API signatures, return types, or import paths don't match source code
- Configuration keys or values are stale or incorrect

**Do NOT flag:**
- "Not found in code" without concrete evidence of a problem
- Test fixtures, examples, or intentionally different deprecated paths
- External system commands (sudo, grep, git, etc.) that aren't project-specific
- Pre-existing issues in unchanged content
- Minor discrepancies that don't affect functionality

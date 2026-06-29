# Agent Prompt Templates

## Fan-out Classifier Prompt

For each requirement extracted in step 3, dispatch one Agent call. Launch ALL requirement agents in a **single message** (parallel execution).

Each agent reads the analysis data from disk and writes its result to a per-requirement JSON file on disk. This keeps the orchestrator's context lean — agent prompts are compact (~0.3KB each) and agent results are one-line confirmations (~0.1KB each).

For each requirement, use:

```text
Agent:
  subagent_type: docs-skills:requirement-classifier
  description: "Classify REQ-NNN: <title truncated to 40 chars>"
  prompt: |
    Classify this requirement by code evidence status.

    REQUIREMENT:
    - ID: <id>
    - Title: <title>
    - Summary: <summary>

    ANALYSIS_PATH: <ANALYSIS_PATH>
    Read analysis files from this directory:
    - detection/detection.json
    - module-registry/registry.json
    - module-analysis/summary.json
    - relationships/relationships.json (if it exists)
    - synthesis/ONBOARDING.md

    REPO_PATH: <absolute repo path>

    DISCOVERED_REPOS_FILE: <OUTPUT_DIR>/discovered-repos.json

    You may Read, Grep, and Glob files in REPO_PATH to find specific
    code evidence. Always include file paths when citing code.

    OUTPUT_FILE: <OUTPUT_DIR>/evidence-<NNN>.json
    Write your JSON result to OUTPUT_FILE using the Write tool.
    After writing, print ONLY: Written <OUTPUT_DIR>/evidence-<NNN>.json
```

Where `<NNN>` is the zero-padded requirement number extracted from the REQ-NNN id (e.g., REQ-001 produces evidence-001.json).

**Important:** All Agent calls MUST be in a single message so they run in parallel. Do not dispatch them sequentially.

## Merge Agent Prompt

Delegate the assembly of `evidence-status.json` and `summary.md` to a merge subagent. This keeps the full classification data (~20-50KB) out of the orchestrator's context.

```text
Agent:
  description: "Merge evidence classifications for <TICKET>"
  prompt: |
    Assemble evidence-status.json and summary.md from per-requirement classification files.

    TICKET: <TICKET>
    REPO_PATH: <REPO_PATH>
    ANALYSIS_PATH: <ANALYSIS_PATH>
    OUTPUT_DIR: <OUTPUT_DIR>
    EVIDENCE_STATUS_FILE: <OUTPUT_DIR>/evidence-status.json
    SUMMARY_FILE: <OUTPUT_DIR>/summary.md
    DISCOVERED_REPOS_FILE: <OUTPUT_DIR>/discovered-repos.json
    EXPECTED_REQUIREMENTS: <comma-separated list of REQ IDs from step 3>

    Instructions:
    1. Read DISCOVERED_REPOS_FILE for the discovered_repos array
    2. For each expected requirement ID, read <OUTPUT_DIR>/evidence-<NNN>.json
       - Map agent output fields: confidence -> top_score, evidence_summary -> evidence_summary.
         All other fields pass through directly.
       - If a file is missing, create a fallback entry:
         {"id": "<REQ-NNN>", "title": "<expected title>", "status": "absent",
          "error": "Agent did not return valid JSON", "top_score": 0.0,
          "key_files": [], "evidence_summary": null,
          "gap_category": null, "recommended_action": null}
    3. Collect all per-requirement results ordered by requirement ID
    4. Compute summary counts by counting the `status` field of each entry in the
       collected requirements array: count entries where `status == "grounded"`,
       `status == "partial"`, and `status == "absent"`. Set `total` to the length
       of the requirements array. Do NOT compute these counts independently --
       derive them directly from the array entries to ensure consistency
    5. Compute recommendation:
       - "proceed" -- no absent requirements
       - "gather-more" -- some absent, but grounded outnumber absent
       - "review-needed" -- absent >= grounded, or more than half are absent
    6. Write EVIDENCE_STATUS_FILE:
       {"ticket": "<TICKET>", "repo_path": "<REPO_PATH>",
        "analysis_path": "<ANALYSIS_PATH>",
        "recommendation": "<recommendation>",
        "requirements": [<per-requirement entries>],
        "summary": {"grounded": N, "partial": N, "absent": N, "total": N},
        "discovered_repos": <from DISCOVERED_REPOS_FILE>,
        "secondary_repos": []}
       Note: secondary_repos is populated by step 9 (extract_secondary_repos.py),
       so initialize it as an empty array here.
    7. Write SUMMARY_FILE in markdown:
       # Scope Requirements Audit
       **Ticket:** <TICKET>
       **Repository:** <REPO_PATH>
       **Analysis:** <ANALYSIS_PATH>
       **Recommendation:** <recommendation>
       ## Classification Summary
       [table with grounded, partial, absent, total counts]
       ## Grounded Requirements
       - **REQ-NNN: [title]** -- confidence: N.NN, files: `path/to/file`
         Evidence: [evidence_summary]
       ## Partial Requirements
       - **REQ-NNN: [title]** -- confidence: N.NN, category: <gap_category>, files: `path`
         Evidence: [evidence_summary]
         Action: [recommended_action]
       ## Absent Requirements
       - **REQ-NNN: [title]** -- confidence: N.NN, category: <gap_category>
         Evidence: [evidence_summary]
         Action: [recommended_action]
       ## Discovered Repos (not indexed)
       - [url](url) -- referenced in <source>
    8. After writing both files, print ONLY:
       Written <EVIDENCE_STATUS_FILE>
       Written <SUMMARY_FILE>
```

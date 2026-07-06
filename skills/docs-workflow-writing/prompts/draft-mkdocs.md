Write complete Material for MkDocs Markdown documentation based on the documentation plan for ticket `<TICKET>`.

Read the plan from: `<INPUT_FILE>`

**[Include only if HAS_CODE_ANALYSIS=true]** Code-learner analysis is available at `<CODE_ANALYSIS_DIR>`. Read `ONBOARDING.md` for architecture overview and module relationships. Read relevant module summaries from `summaries/` for accurate function signatures (`public_api`), dependencies, and data flow patterns. Prefer analysis over assumptions — if the analysis contradicts the plan, follow the analysis.

Use the module registry (`registry.json`) to understand module priority:
- **read-first** modules: write with full technical detail using the module's summary data
- **read-second** modules: write concise coverage, focusing on key APIs and purpose
- **skip** modules: do not write standalone content — mention only if relevant to a documented module

**[Include only if HAS_PR_ANALYSIS=true]** PR analysis is available at `<PR_ANALYSIS_DIR>`. Read `PR-*-ANALYSIS.md` for change-specific context — what code was modified, why, and what impact it has. Use this to ensure documentation accurately reflects the current state of the code after the PR changes.

**[Include only if SOURCE_REPO is not null]** Source code repository is available at `<SOURCE_REPO>`. You may read specific source files for additional detail when the analysis data does not contain sufficient information for a section. Use this to verify function signatures, check parameter types, or find code examples — do not browse the entire repo.

**[Include only if ADDITIONAL_REPO_PATHS is non-empty]** Additional source code repositories are available at: <list each path from ADDITIONAL_REPO_PATHS>. For each additional repo with a code-learner analysis directory in `<ADDITIONAL_CODE_ANALYSIS_DIRS>`, read its `ONBOARDING.md` for architecture overview. Use these for cross-repo context when features span multiple repositories.

**IMPORTANT**: Write COMPLETE .md files with YAML frontmatter (title, description). Use Material for MkDocs conventions: admonitions, content tabs, code blocks with titles, heading hierarchy starting at `# h1`.

**Placement mode: DRAFT (staging area)**

Save files to the staging area. Do not modify any existing repository files.

Output folder structure:
```
<OUTPUT_DIR>/
├── _index.md                     # Index of all pages
├── mkdocs-nav.yml                # Suggested nav tree fragment
└── docs/                         # All page files
    ├── <concept-name>.md
    ├── <procedure-name>.md
    └── <reference-name>.md
```

Save pages to: `<OUTPUT_DIR>/docs/`
Create nav fragment at: `<OUTPUT_DIR>/mkdocs-nav.yml`
Create index at: `<OUTPUT_FILE>`

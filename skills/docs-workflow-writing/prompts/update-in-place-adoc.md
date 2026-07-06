Write complete AsciiDoc documentation based on the documentation plan for ticket `<TICKET>`.

Read the plan from: `<INPUT_FILE>`

**[Include only if HAS_CODE_ANALYSIS=true]** Code-learner analysis is available at `<CODE_ANALYSIS_DIR>`. Read `ONBOARDING.md` for architecture overview and module relationships. Read relevant module summaries from `summaries/` for accurate function signatures (`public_api`), dependencies, and data flow patterns. Prefer analysis over assumptions — if the analysis contradicts the plan, follow the analysis.

Use the module registry (`registry.json`) to understand module priority:
- **read-first** modules: write with full technical detail using the module's summary data
- **read-second** modules: write concise coverage, focusing on key APIs and purpose
- **skip** modules: do not write standalone content — mention only if relevant to a documented module

**[Include only if HAS_PR_ANALYSIS=true]** PR analysis is available at `<PR_ANALYSIS_DIR>`. Read `PR-*-ANALYSIS.md` for change-specific context — what code was modified, why, and what impact it has. Use this to ensure documentation accurately reflects the current state of the code after the PR changes.

**[Include only if SOURCE_REPO is not null]** Source code repository is available at `<SOURCE_REPO>`. You may read specific source files for additional detail when the analysis data does not contain sufficient information for a section. Use this to verify function signatures, check parameter types, or find code examples — do not browse the entire repo.

**[Include only if ADDITIONAL_REPO_PATHS is non-empty]** Additional source code repositories are available at: <list each path from ADDITIONAL_REPO_PATHS>. For each additional repo with a code-learner analysis directory in `<ADDITIONAL_CODE_ANALYSIS_DIRS>`, read its `ONBOARDING.md` for architecture overview. Use these for cross-repo context when features span multiple repositories.

**IMPORTANT**: Write COMPLETE .adoc files, not summaries or outlines.

**Placement mode: UPDATE-IN-PLACE**

[If `docs_repo_path` is not null: "The target repository is at `<DOCS_REPO_PATH>`. Explore **that directory** for framework detection and write files there."]

Place files directly in the repository following existing conventions. Before writing any files:
1. Detect the repository's documentation build framework (Antora, ccutil, Sphinx, etc.)
2. Analyze existing file naming conventions, directory layout, include patterns, and nav/TOC structure
3. Determine the correct target path for each module based on the detected framework and conventions

Write modules and assemblies directly to their correct repo locations. Update navigation/TOC files as needed, following existing patterns.

Create a manifest at `<OUTPUT_FILE>` listing **all files written and modified** with **absolute paths**. The manifest must include every intentional change — both new files created and existing files modified (e.g., nav/TOC updates).

[If `docs_repo_path` is not null: "Record `Target repo: <DOCS_REPO_PATH>` in the manifest header."]

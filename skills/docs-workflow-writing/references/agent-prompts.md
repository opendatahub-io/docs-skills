# Agent Prompt Templates

## Mode: `update-in-place`, format: `adoc`

**Description:** `Write adoc documentation for <TICKET>`

**Prompt:**

> Write complete AsciiDoc documentation based on the documentation plan for ticket `<TICKET>`.
>
> Read the plan from: `<INPUT_FILE>`
>
> **[Include only if HAS_CODE_ANALYSIS=true]** Code-learner analysis is available at `<CODE_ANALYSIS_DIR>`. Read `ONBOARDING.md` for architecture overview and module relationships. Read relevant module summaries from `summaries/` for accurate function signatures (`public_api`), dependencies, and data flow patterns. Prefer analysis over assumptions — if the analysis contradicts the plan, follow the analysis.
>
> Use the module registry (`registry.json`) to understand module priority:
> - **read-first** modules: write with full technical detail using the module's summary data
> - **read-second** modules: write concise coverage, focusing on key APIs and purpose
> - **skip** modules: do not write standalone content — mention only if relevant to a documented module
>
> **[Include only if HAS_PR_ANALYSIS=true]** PR analysis is available at `<PR_ANALYSIS_DIR>`. Read `PR-*-ANALYSIS.md` for change-specific context — what code was modified, why, and what impact it has. Use this to ensure documentation accurately reflects the current state of the code after the PR changes.
>
> **[Include only if SOURCE_REPO is not null]** Source code repository is available at `<SOURCE_REPO>`. You may read specific source files for additional detail when the analysis data does not contain sufficient information for a section. Use this to verify function signatures, check parameter types, or find code examples — do not browse the entire repo.
>
> **[Include only if ADDITIONAL_REPO_PATHS is non-empty]** Additional source code repositories are available at: <list each path from ADDITIONAL_REPO_PATHS>. For each additional repo with a code-learner analysis directory in `<ADDITIONAL_CODE_ANALYSIS_DIRS>`, read its `ONBOARDING.md` for architecture overview. Use these for cross-repo context when features span multiple repositories.
>
> **IMPORTANT**: Write COMPLETE .adoc files, not summaries or outlines.
>
> **Placement mode: UPDATE-IN-PLACE**
>
> [If `docs_repo_path` is not null: "The target repository is at `<DOCS_REPO_PATH>`. Explore **that directory** for framework detection and write files there."]
>
> Place files directly in the repository following existing conventions. Before writing any files:
> 1. Detect the repository's documentation build framework (Antora, ccutil, Sphinx, etc.)
> 2. Analyze existing file naming conventions, directory layout, include patterns, and nav/TOC structure
> 3. Determine the correct target path for each module based on the detected framework and conventions
>
> Write modules and assemblies directly to their correct repo locations. Update navigation/TOC files as needed, following existing patterns.
>
> Create a manifest at `<OUTPUT_FILE>` listing **all files written and modified** with **absolute paths**. The manifest must include every intentional change — both new files created and existing files modified (e.g., nav/TOC updates).
>
> [If `docs_repo_path` is not null: "Record `Target repo: <DOCS_REPO_PATH>` in the manifest header."]

---

## Mode: `update-in-place`, format: `mkdocs`

**Description:** `Write mkdocs documentation for <TICKET>`

**Prompt:**

> Write complete Material for MkDocs Markdown documentation based on the documentation plan for ticket `<TICKET>`.
>
> Read the plan from: `<INPUT_FILE>`
>
> **[Include only if HAS_CODE_ANALYSIS=true]** Code-learner analysis is available at `<CODE_ANALYSIS_DIR>`. Read `ONBOARDING.md` for architecture overview and module relationships. Read relevant module summaries from `summaries/` for accurate function signatures (`public_api`), dependencies, and data flow patterns. Prefer analysis over assumptions — if the analysis contradicts the plan, follow the analysis.
>
> Use the module registry (`registry.json`) to understand module priority:
> - **read-first** modules: write with full technical detail using the module's summary data
> - **read-second** modules: write concise coverage, focusing on key APIs and purpose
> - **skip** modules: do not write standalone content — mention only if relevant to a documented module
>
> **[Include only if HAS_PR_ANALYSIS=true]** PR analysis is available at `<PR_ANALYSIS_DIR>`. Read `PR-*-ANALYSIS.md` for change-specific context — what code was modified, why, and what impact it has. Use this to ensure documentation accurately reflects the current state of the code after the PR changes.
>
> **[Include only if SOURCE_REPO is not null]** Source code repository is available at `<SOURCE_REPO>`. You may read specific source files for additional detail when the analysis data does not contain sufficient information for a section. Use this to verify function signatures, check parameter types, or find code examples — do not browse the entire repo.
>
> **[Include only if ADDITIONAL_REPO_PATHS is non-empty]** Additional source code repositories are available at: <list each path from ADDITIONAL_REPO_PATHS>. For each additional repo with a code-learner analysis directory in `<ADDITIONAL_CODE_ANALYSIS_DIRS>`, read its `ONBOARDING.md` for architecture overview. Use these for cross-repo context when features span multiple repositories.
>
> **IMPORTANT**: Write COMPLETE .md files with YAML frontmatter (title, description). Use Material for MkDocs conventions: admonitions, content tabs, code blocks with titles, heading hierarchy starting at `# h1`.
>
> **Placement mode: UPDATE-IN-PLACE**
>
> [If `docs_repo_path` is not null: "The target repository is at `<DOCS_REPO_PATH>`. Explore **that directory** for framework detection and write files there."]
>
> Place files directly in the repository following existing conventions. Before writing any files:
> 1. Detect the repository's documentation build framework (MkDocs, Docusaurus, Hugo, etc.)
> 2. Analyze existing file naming conventions, directory layout, and nav structure
> 3. Determine the correct target path for each page based on the detected framework and conventions
>
> Write pages directly to their correct repo locations. Update `mkdocs.yml` nav section or equivalent as needed, following existing patterns.
>
> Create a manifest at `<OUTPUT_FILE>` listing **all files written and modified** with **absolute paths**. The manifest must include every intentional change — both new files created and existing files modified (e.g., `mkdocs.yml` nav updates).
>
> [If `docs_repo_path` is not null: "Record `Target repo: <DOCS_REPO_PATH>` in the manifest header."]

---

## Mode: `draft`, format: `adoc`

**Description:** `Write adoc documentation for <TICKET>`

**Prompt:**

> Write complete AsciiDoc documentation based on the documentation plan for ticket `<TICKET>`.
>
> Read the plan from: `<INPUT_FILE>`
>
> **[Include only if HAS_CODE_ANALYSIS=true]** Code-learner analysis is available at `<CODE_ANALYSIS_DIR>`. Read `ONBOARDING.md` for architecture overview and module relationships. Read relevant module summaries from `summaries/` for accurate function signatures (`public_api`), dependencies, and data flow patterns. Prefer analysis over assumptions — if the analysis contradicts the plan, follow the analysis.
>
> Use the module registry (`registry.json`) to understand module priority:
> - **read-first** modules: write with full technical detail using the module's summary data
> - **read-second** modules: write concise coverage, focusing on key APIs and purpose
> - **skip** modules: do not write standalone content — mention only if relevant to a documented module
>
> **[Include only if HAS_PR_ANALYSIS=true]** PR analysis is available at `<PR_ANALYSIS_DIR>`. Read `PR-*-ANALYSIS.md` for change-specific context — what code was modified, why, and what impact it has. Use this to ensure documentation accurately reflects the current state of the code after the PR changes.
>
> **[Include only if SOURCE_REPO is not null]** Source code repository is available at `<SOURCE_REPO>`. You may read specific source files for additional detail when the analysis data does not contain sufficient information for a section. Use this to verify function signatures, check parameter types, or find code examples — do not browse the entire repo.
>
> **[Include only if ADDITIONAL_REPO_PATHS is non-empty]** Additional source code repositories are available at: <list each path from ADDITIONAL_REPO_PATHS>. For each additional repo with a code-learner analysis directory in `<ADDITIONAL_CODE_ANALYSIS_DIRS>`, read its `ONBOARDING.md` for architecture overview. Use these for cross-repo context when features span multiple repositories.
>
> **IMPORTANT**: Write COMPLETE .adoc files, not summaries or outlines.
>
> **Placement mode: DRAFT (staging area)**
>
> Save files to the staging area. Do not modify any existing repository files.
>
> Output folder structure:
> ```text
> <OUTPUT_DIR>/
> ├── _index.md                     # Index of all modules
> ├── <name>.adoc                  # Assembly files at root (:_mod-docs-content-type: ASSEMBLY)
> └── modules/                      # All module files
>     ├── <concept-name>.adoc
>     ├── <procedure-name>.adoc
>     └── <reference-name>.adoc
> ```
>
> Save modules to: `<OUTPUT_DIR>/modules/`
> Save assemblies to: `<OUTPUT_DIR>/`
> Create index at: `<OUTPUT_FILE>`

---

## Mode: `draft`, format: `mkdocs`

**Description:** `Write mkdocs documentation for <TICKET>`

**Prompt:**

> Write complete Material for MkDocs Markdown documentation based on the documentation plan for ticket `<TICKET>`.
>
> Read the plan from: `<INPUT_FILE>`
>
> **[Include only if HAS_CODE_ANALYSIS=true]** Code-learner analysis is available at `<CODE_ANALYSIS_DIR>`. Read `ONBOARDING.md` for architecture overview and module relationships. Read relevant module summaries from `summaries/` for accurate function signatures (`public_api`), dependencies, and data flow patterns. Prefer analysis over assumptions — if the analysis contradicts the plan, follow the analysis.
>
> Use the module registry (`registry.json`) to understand module priority:
> - **read-first** modules: write with full technical detail using the module's summary data
> - **read-second** modules: write concise coverage, focusing on key APIs and purpose
> - **skip** modules: do not write standalone content — mention only if relevant to a documented module
>
> **[Include only if HAS_PR_ANALYSIS=true]** PR analysis is available at `<PR_ANALYSIS_DIR>`. Read `PR-*-ANALYSIS.md` for change-specific context — what code was modified, why, and what impact it has. Use this to ensure documentation accurately reflects the current state of the code after the PR changes.
>
> **[Include only if SOURCE_REPO is not null]** Source code repository is available at `<SOURCE_REPO>`. You may read specific source files for additional detail when the analysis data does not contain sufficient information for a section. Use this to verify function signatures, check parameter types, or find code examples — do not browse the entire repo.
>
> **[Include only if ADDITIONAL_REPO_PATHS is non-empty]** Additional source code repositories are available at: <list each path from ADDITIONAL_REPO_PATHS>. For each additional repo with a code-learner analysis directory in `<ADDITIONAL_CODE_ANALYSIS_DIRS>`, read its `ONBOARDING.md` for architecture overview. Use these for cross-repo context when features span multiple repositories.
>
> **IMPORTANT**: Write COMPLETE .md files with YAML frontmatter (title, description). Use Material for MkDocs conventions: admonitions, content tabs, code blocks with titles, heading hierarchy starting at `# h1`.
>
> **Placement mode: DRAFT (staging area)**
>
> Save files to the staging area. Do not modify any existing repository files.
>
> Output folder structure:
> ```text
> <OUTPUT_DIR>/
> ├── _index.md                     # Index of all pages
> ├── mkdocs-nav.yml                # Suggested nav tree fragment
> └── docs/                         # All page files
>     ├── <concept-name>.md
>     ├── <procedure-name>.md
>     └── <reference-name>.md
> ```
>
> Save pages to: `<OUTPUT_DIR>/docs/`
> Create nav fragment at: `<OUTPUT_DIR>/mkdocs-nav.yml`
> Create index at: `<OUTPUT_FILE>`

---

## Mode: `per-module write`

Dispatched once **per module, in parallel**, when `writer_strategy` is
`per_module`. Each writer is scoped to exactly **one** module and never sees
sibling module prose — only the compact module map of the *other* modules.

**Description:** `Write <FORMAT> module <MODULE_TITLE> for <TICKET>`

**Prompt:**

> Write exactly **one** documentation module — `<MODULE_TITLE>` (type
> `<MODULE_TYPE>`) — for ticket `<TICKET>`. Do **not** write any other module.
>
> Read the full plan from `<INPUT_FILE>` and locate the entry for this module
> (anchor `<MODULE_ANCHOR>`). Write only that module's content. Its one-line
> scope is: `<MODULE_SCOPE>`.
>
> Output format: `<FORMAT>` (`adoc` = AsciiDoc, `mkdocs` = Material for MkDocs
> Markdown). Follow the format reference your agent instructions point to.
>
> **[Include only if HAS_CODE_ANALYSIS=true]** Code-learner analysis is available
> at `<CODE_ANALYSIS_DIR>`. Read `ONBOARDING.md` and only the `summaries/` entries
> relevant to **this** module for accurate signatures and data flow. Prefer the
> analysis over assumptions.
>
> **[Include only if HAS_PR_ANALYSIS=true]** PR analysis is available at
> `<PR_ANALYSIS_DIR>`. Use it for change-specific context relevant to this module.
>
> **[Include only if SOURCE_REPO is not null]** Source code is at `<SOURCE_REPO>`.
> Read specific files only when the analysis is insufficient for this module.
>
> **Module map (all *other* modules in this doc set).** Use this to write
> cross-references inline as real `xref:`/links. Do not invent links to modules
> not in this map:
>
> ```json
> <MODULE_MAP_JSON>
> ```
>
> **Placement mode: <PLACEMENT_MODE>**
>
> [If `update-in-place`: "The target repository is at `<DOCS_REPO_PATH>` (when
> set, otherwise detect from `<SOURCE_REPO>`). Detect the build framework and
> existing conventions, then write this one module to its correct repo location.
> Do not modify navigation or other modules' files — the linking pass and
> single-source dedup are handled centrally."]
>
> [If `draft`: "Write this one module to `<MODULE_OUTPUT_FILE>`. Create parent
> directories as needed. Do not modify any existing repository files."]
>
> **IMPORTANT:** Write a COMPLETE module, not a summary or outline. Resolve any
> cross-reference you can from the module map as a real inline link. Reserve
> `xref_suggestions` for *uncertain or external* targets the map could not
> resolve.
>
> **Report back.** End your final message with **only** this JSON object (no
> prose after it):
>
> ```json
> { "file": "<absolute path you wrote>", "status": "ok",
>   "xref_suggestions": [ { "target": "<unresolved target>", "reason": "<why>" } ] }
> ```
>
> If you could not write the module, set `"status": "error"` and put the reason
> in a `"message"` field. Leave `xref_suggestions` as `[]` when every link
> resolved from the map (the common case).

---

## Mode: `fix`

**Description:** `Fix documentation for <TICKET>`

**Prompt:**

> Apply fixes to documentation drafts based on technical review feedback for ticket `<TICKET>`.
>
> Read the review report from: `<FIX_FROM>`
> Drafts location: `<OUTPUT_DIR>/`
>
> For each issue flagged in the review:
> 1. If the fix is clear and unambiguous, apply it directly
> 2. If the issue requires broader context or judgment, skip it
> 3. Do NOT rewrite content that was not flagged
>
> Edit files in place. Do NOT create copies or new files.
>
> **[Include only if SOURCE_REPO is not null]** Source code repository is available at `<SOURCE_REPO>`. You may read specific source files to verify fixes and resolve ambiguous review findings.
>
> **[Include only if ADDITIONAL_REPO_PATHS is non-empty]** Additional source code repositories are available at: <list each path from ADDITIONAL_REPO_PATHS>. Use these for cross-repo verification of review findings.

In fix mode, the skill does not create new modules or restructure content.

---

## Mode: `linking pass`

Dispatched **once, only if** one or more per-module writers reported non-empty
`xref_suggestions`. Skipped entirely when all suggestions were empty.

**Description:** `Resolve cross-reference suggestions for <TICKET>`

**Prompt:**

> One or more documentation modules for ticket `<TICKET>` reported cross-reference
> suggestions that could not be resolved from the module map during writing.
>
> Module map (all written modules, with their files and anchors):
>
> ```json
> <MODULE_MAP_JSON>
> ```
>
> Collected suggestions (each names the source file and an unresolved target):
>
> ```json
> <COLLECTED_SUGGESTIONS_JSON>
> ```
>
> For each suggestion, add the link **only** where it is clearly warranted and the
> target genuinely exists (in the map above or as a real external resource). Edit
> the relevant files in place using the format's link syntax. Do **not** rewrite
> content, restructure modules, or add links that were not suggested. Skip any
> suggestion you cannot resolve with confidence.
>
> End your final message with a one-line summary of which files you edited.

---
name: docs-workflow-writing
description: Write documentation from a documentation plan. Dispatches the docs-writer agent. Supports AsciiDoc (default) and MkDocs formats. Default placement is UPDATE-IN-PLACE; use --draft for staging area. Also supports fix mode for applying technical review corrections.
argument-hint: <ticket> --base-path <path> --format <adoc|mkdocs> [--draft] [--repo <path>]... [--repo-path <path>] [--fix-from <review_path>]
allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Skill, Agent
---

# Documentation Writing Step

Step skill for the docs-orchestrator pipeline. Follows the step skill contract: **run script → dispatch agent → verify output**.

## Execution

### 1. Run the script

Run the build script to parse arguments, validate inputs, determine mode, and create output directories:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/build_writing_args.sh <args>
```

Pass through the full args string. The script emits JSON on stdout:

```json
{
  "mode":                "update-in-place | draft | fix",
  "ticket":              "PROJ-123",
  "format":              "adoc | mkdocs",
  "input_file":          "<base-path>/planning/plan.md",
  "code_analysis_dir":   "<base-path>/code-analysis/ | null",
  "has_code_analysis":   true | false,
  "pr_analysis_dir":     "<base-path>/pr-analysis/ | null",
  "has_pr_analysis":     true | false,
  "output_dir":          "<base-path>/writing",
  "output_file":         "<base-path>/writing/_index.md",
  "docs_repo_path":      "<path> | null",
  "source_repo_path":    "<path> | null",
  "additional_repo_paths": ["<path>", ...],
  "additional_code_analysis_dirs": ["<path>", ...],
  "fix_from":            "<path> | null",
  "verify_output":       true | false
}
```

If the script exits non-zero, stop and report the error from stderr.

### 2. Dispatch the docs-writer agent

**You MUST use the Agent tool** to invoke the `docs-writer` subagent. Do NOT read the agent's markdown file or attempt to perform the agent's work yourself — the agent has a specialized system prompt and must run as an isolated subagent.

Read the prompt template from the `prompt_template` path in the script's JSON output. Substitute the `<TICKET>`, `<INPUT_FILE>`, `<OUTPUT_FILE>`, `<OUTPUT_DIR>`, `<DOCS_REPO_PATH>`, `<FIX_FROM>`, `<CODE_ANALYSIS_DIR>`, `<PR_ANALYSIS_DIR>`, `<SOURCE_REPO>`, `<ADDITIONAL_REPO_PATHS>`, and `<ADDITIONAL_CODE_ANALYSIS_DIRS>` placeholders with the corresponding values from the script's JSON.

Apply the conditional `[Include only if ...]` directives based on the script's JSON flags (`has_code_analysis`, `has_pr_analysis`, `source_repo_path`, `additional_repo_paths`, `docs_repo_path`). Omit conditional paragraphs when the condition is false/null/empty.

**Agent tool parameters:**
- `subagent_type`: `docs-tools:docs-writer`
- `description`:
  - fix mode: `Fix documentation for <TICKET>`
  - otherwise: `Write <format> documentation for <TICKET>`

The prompt templates are in `${CLAUDE_SKILL_DIR}/prompts/`:
- `update-in-place-adoc.md` — AsciiDoc, update-in-place mode
- `update-in-place-mkdocs.md` — MkDocs, update-in-place mode
- `draft-adoc.md` — AsciiDoc, draft mode
- `draft-mkdocs.md` — MkDocs, draft mode
- `fix.md` — Fix mode (format-independent)

In fix mode, the skill does not create new modules or restructure content.

---

### 3. Verify output

If `verify_output` is `true` in the script's JSON output, check that `output_file` exists.

If `verify_output` is `false` (fix mode), no verification is needed — files are edited in place.

### 4. Write step-result.json

Skip this step if `mode` is `"fix"` (fixes edit files in place — no new manifest to parse).

Parse the manifest and write the sidecar via script pipeline:

```bash
MANIFEST_JSON=$(python3 ${CLAUDE_PLUGIN_ROOT}/scripts/parse_manifest.py "<OUTPUT_FILE>" --mode "<MODE>" --format "<FORMAT>")
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/write_step_result.py \
  --step writing --ticket "<TICKET>" \
  --output-dir "<OUTPUT_DIR>" --data "$MANIFEST_JSON"
```

Where `<MODE>` and `<FORMAT>` are the values from the `build_writing_args.sh` JSON output.

---

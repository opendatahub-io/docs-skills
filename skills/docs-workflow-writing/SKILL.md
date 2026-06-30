---
name: docs-workflow-writing
description: Write documentation from a documentation plan. Dispatches the docs-writer agent. Supports AsciiDoc (default) and MkDocs formats. Default placement is UPDATE-IN-PLACE; use --draft for staging area. Also supports fix mode for applying technical review corrections.
argument-hint: "<ticket> --base-path <path> --format <adoc|mkdocs> [--draft] [--repo <path>]... [--repo-path <path>] [--fix-from <review_path>]"
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

### 1b. Determine the writer strategy

For non-fix modes, decide whether to write the doc set with one writer or one
writer **per module**. Run the companion script:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/build_module_map.py \
  --plan "<input_file>" \
  --planning-result "<base-path>/planning/step-result.json" \
  --output-dir "<output_dir>" \
  --format "<format>" \
  --mode "<mode>"
```

Substitute the values from the `build_writing_args.sh` JSON. The script emits:

```json
{
  "writer_strategy": "per_module | single",
  "module_count": 12,
  "threshold": 8,
  "fallback_reason": "null | fix_mode | below_threshold | no_module_ids",
  "modules": [
    { "id": "...", "anchor": "...", "title": "...", "type": "concept|procedure|reference",
      "scope": "...", "output_file": "..." }
  ]
}
```

- If `writer_strategy` is `single` (including all fix-mode and below-threshold
  runs), follow **step 2 (single writer)** below — today's exact behavior.
- If `writer_strategy` is `per_module`, follow **step 2b (per-module writers)**
  instead, then skip step 2.

### 2. Dispatch the docs-writer agent (single-writer strategy)

**You MUST use the Agent tool** to invoke the `docs-writer` subagent. Do NOT read the agent's markdown file or attempt to perform the agent's work yourself — the agent has a specialized system prompt and must run as an isolated subagent.

Select the prompt based on `mode` and `format` from the JSON output. See [agent prompts](references/agent-prompts.md) for the full prompt text for each combination.

| `mode` | `format` | Description |
|--------|----------|-------------|
| `update-in-place` | `adoc` | `Write adoc documentation for <TICKET>` |
| `update-in-place` | `mkdocs` | `Write mkdocs documentation for <TICKET>` |
| `draft` | `adoc` | `Write adoc documentation for <TICKET>` |
| `draft` | `mkdocs` | `Write mkdocs documentation for <TICKET>` |
| `fix` | *(any)* | `Fix documentation for <TICKET>` |

**Agent tool parameters for all modes:**
- `subagent_type`: `docs-skills:docs-writer`
- `description`: use the value from the Description column

In every prompt, substitute the `<TICKET>`, `<INPUT_FILE>`, `<OUTPUT_FILE>`, `<OUTPUT_DIR>`, `<DOCS_REPO_PATH>`, `<FIX_FROM>`, `<CODE_ANALYSIS_DIR>`, `<PR_ANALYSIS_DIR>`, `<SOURCE_REPO>`, `<ADDITIONAL_REPO_PATHS>`, `<ADDITIONAL_CODE_ANALYSIS_DIRS>`, `HAS_CODE_ANALYSIS`, and `HAS_PR_ANALYSIS` placeholders with the corresponding values from the script's JSON.

---

### 2b. Dispatch per-module writers (per-module strategy)

Use this path **only** when `writer_strategy` is `per_module`. Subagents cannot
spawn subagents, so all dispatch happens here in the writing skill (main session).

1. **Dispatch one `docs-writer` per module, in parallel.** Make all `Agent`
   calls concurrently (one response, multiple tool calls) — modules are discrete
   files, so there is no write contention. For each entry in `modules`, use the
   **`Mode: per-module write`** prompt from
   [references/agent-prompts.md](references/agent-prompts.md), substituting:
   - `<MODULE_TITLE>`, `<MODULE_TYPE>`, `<MODULE_ANCHOR>`, `<MODULE_SCOPE>`,
     `<MODULE_OUTPUT_FILE>` from the module entry,
   - `<MODULE_MAP_JSON>` = the compact list of **all *other*** modules
     (`id`, `anchor`, `title`, `type`, `output_file`) — exclude the current module,
   - `<FORMAT>`, `<PLACEMENT_MODE>`, `<INPUT_FILE>`, `<DOCS_REPO_PATH>`,
     `<SOURCE_REPO>`, `<CODE_ANALYSIS_DIR>`, `<PR_ANALYSIS_DIR>`,
     `HAS_CODE_ANALYSIS`, `HAS_PR_ANALYSIS` from the `build_writing_args.sh` JSON.
   - `subagent_type`: `docs-skills:docs-writer`.

2. **Accumulate only the small reports.** Each writer returns a JSON report
   (`{ "file", "status", "xref_suggestions" }`). Collect these reports **only** —
   never the module bodies — so this skill's context stays flat as module count
   grows.

3. **Fail fast on any writer error.** If any report has `"status": "error"`
   (or a writer returned no parseable report), **STOP** and fail the writing step
   with a message naming every module whose `file`/title failed. Keep the
   successful modules' output on disk, but do not write `step-result.json` and do
   not proceed — this matches today's all-or-nothing writing semantics and the
   orchestrator's "verify output → mark failed → STOP" contract.

4. **Optional linking pass.** If **any** report has a non-empty
   `xref_suggestions`, dispatch **one** `docs-writer` using the
   **`Mode: linking pass`** prompt, substituting `<MODULE_MAP_JSON>` (all written
   modules) and `<COLLECTED_SUGGESTIONS_JSON>` (every suggestion, each tagged with
   its source `file`). If **no** report has suggestions, **skip this pass
   entirely.**

---

### 3. Verify output

If `verify_output` is `true` in the script's JSON output, check that `output_file` exists.

If `verify_output` is `false` (fix mode), no verification is needed — files are edited in place.

For the per-module strategy, instead of checking a single `output_file`, confirm
that every successful module report's `file` exists on disk. (Fix mode still
performs no verification.)

### 4. Write step-result.json

Skip this step if `mode` is `"fix"` (fixes edit files in place — no new manifest to parse).

Assemble the `files` array based on the strategy:

- **single:** Read the manifest at `<OUTPUT_FILE>` (`_index.md`) and extract every
  absolute file path from the table rows.
- **per_module:** Use the `file` from each successful module report (plus any files
  the linking pass edited). Do not parse `_index.md`.

Write the sidecar to `<OUTPUT_DIR>/step-result.json` using the `mode` and `format`
from the `build_writing_args.sh` JSON and the `writer_strategy` from
`build_module_map.py`:

```json
{
  "schema_version": 1,
  "step": "writing",
  "ticket": "<TICKET>",
  "completed_at": "<current ISO 8601 timestamp>",
  "files": [
    "/absolute/path/to/file1.adoc",
    "/absolute/path/to/file2.adoc"
  ],
  "mode": "<mode from build_writing_args.sh JSON>",
  "format": "<format from build_writing_args.sh JSON>",
  "writer_strategy": "<writer_strategy from build_module_map.py: per_module | single>"
}
```

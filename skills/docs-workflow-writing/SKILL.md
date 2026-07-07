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

Pass through the args **unquoted** so each flag and value is a separate shell word. Do NOT wrap the entire args string in quotes — the script uses positional argument parsing and each `--flag value` pair must be a separate argument. The script emits JSON on stdout:

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
- `run_in_background`: `false` (the orchestrator must wait for the writer to finish before verifying output)

In every prompt, substitute the `<TICKET>`, `<INPUT_FILE>`, `<OUTPUT_FILE>`, `<OUTPUT_DIR>`, `<DOCS_REPO_PATH>`, `<FIX_FROM>`, `<CODE_ANALYSIS_DIR>`, `<PR_ANALYSIS_DIR>`, `<SOURCE_REPO>`, `<ADDITIONAL_REPO_PATHS>`, `<ADDITIONAL_CODE_ANALYSIS_DIRS>`, `HAS_CODE_ANALYSIS`, and `HAS_PR_ANALYSIS` placeholders with the corresponding values from the script's JSON.

---

### 3. Verify output

If `verify_output` is `true` in the script's JSON output, check that `output_file` exists.

If `verify_output` is `false` (fix mode), no verification is needed — files are edited in place.

### 4. Write step-result.json

Skip this step if `mode` is `"fix"` (fixes edit files in place — no new manifest to parse).

Do **not** hand-author the sidecar — a hand-written sidecar drifts from the schema and uses an
orchestrator-delayed timestamp instead of a real wall-clock one. Run the script, passing `mode`
and `format` from the build script's JSON output:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/write_step_result.py \
  --ticket "<TICKET>" \
  --manifest "<OUTPUT_FILE>" \
  --mode "<mode from script JSON>" \
  --format "<format from script JSON>" \
  --sidecar "<OUTPUT_DIR>/step-result.json"
```

The script parses absolute file paths from the manifest's table rows and writes the conformant
`step-result.json` with a real wall-clock `completed_at`. If the script exits non-zero, fix the
arguments and re-run; do not substitute a stub.

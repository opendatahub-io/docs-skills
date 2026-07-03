---
name: docs-workflow-code-analysis
description: "Run code-learner analysis on a source repository for the docs orchestrator workflow. Dispatches a subagent to run learn-code, keeping the heavy orchestration out of the main context. Produces ONBOARDING.md, module registry, per-module summaries, and cross-module relationship data."
argument-hint: --repo <path> --ticket <TICKET> --output-dir <path>
allowed-tools: Read, Write, Bash, Agent, Glob, Grep
---

# docs-workflow-code-analysis

Orchestrator step skill that wraps `learn-code` to analyze a source repository and produce structured code understanding for downstream documentation steps.

## Arguments

| Flag | Required | Description |
|---|---|---|
| `--repo` | Yes | Path to the cloned source repository |
| `--ticket` | Yes | JIRA ticket ID |
| `--output-dir` | Yes | Base output directory (`.agent_workspace/<ticket>/code-analysis/`) |

## Execution

### 1. Validate inputs

- Verify `--repo` directory exists and is a git repository
- Verify `--output-dir` parent exists; create output directory if needed

### 2. Check for cached analysis

Check if learn-code output already exists. Learn-code may store results in two locations depending on the subagent's working directory:

1. **Inside the repo**: `${REPO}/.agent_workspace/*/synthesis/ONBOARDING.md`
2. **At the docs repo level**: `${GIT_ROOT}/.agent_workspace/${REPO_NAME}/synthesis/ONBOARDING.md` (where `GIT_ROOT` is the documentation repo root and `REPO_NAME` is `basename "${REPO}"`)

Check both locations:

```bash
REPO_NAME="$(basename "$REPO")"
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Check inside the cloned repo first
LEARN_CODE_ONBOARDING="$(ls "${REPO}/.agent_workspace/"*/synthesis/ONBOARDING.md 2>/dev/null | head -1)"

# Fall back to docs-repo-level .agent_workspace/<repo-name>/
if [[ -z "$LEARN_CODE_ONBOARDING" ]]; then
  LEARN_CODE_ONBOARDING="$(ls "${GIT_ROOT}/.agent_workspace/${REPO_NAME}/synthesis/ONBOARDING.md" 2>/dev/null)"
fi
```

If an `ONBOARDING.md` is found at either location, the analysis was already completed. Locate the corresponding base directory (the parent of `synthesis/`) and copy the onboarding guide to `--output-dir`. All other analysis files stay at the cached location — downstream agents read them from there directly.

```bash
# Find the learn-code base directory containing the cached analysis
LEARN_CODE_BASE="$(dirname "$(dirname "$LEARN_CODE_ONBOARDING")")"

cp "${LEARN_CODE_BASE}/synthesis/ONBOARDING.md" "${OUTPUT_DIR}/"
```

Skip to step 4.

### 3. Dispatch learn-code subagent

**You MUST use the Agent tool** to run learn-code in an isolated subagent. Do NOT invoke `Skill: learn-code` inline — that would load 850+ lines of skill text plus all intermediate orchestration into the main context.

```
Agent:
  description: "Run learn-code analysis on <REPO>"
  prompt: |
    Run the learn-code skill to analyze the source repository.

    Skill: learn-code, args: "<REPO>"

    After learn-code completes, report the location of the output files
    (ONBOARDING.md, registry.json, detection.json, summaries/, relationships/).
```

After the agent completes, locate the learn-code output. Check both possible locations (same as step 2):

```bash
REPO_NAME="$(basename "$REPO")"
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Check inside the cloned repo first
LEARN_CODE_ONBOARDING="$(ls "${REPO}/.agent_workspace/"*/synthesis/ONBOARDING.md 2>/dev/null | head -1)"

# Fall back to docs-repo-level .agent_workspace/<repo-name>/
if [[ -z "$LEARN_CODE_ONBOARDING" ]]; then
  LEARN_CODE_ONBOARDING="$(ls "${GIT_ROOT}/.agent_workspace/${REPO_NAME}/synthesis/ONBOARDING.md" 2>/dev/null)"
fi

# Copy analysis output to the step's output directory
LEARN_CODE_BASE="$(dirname "$(dirname "$LEARN_CODE_ONBOARDING")")"

cp "${LEARN_CODE_BASE}/synthesis/ONBOARDING.md" "${OUTPUT_DIR}/"
```

If `ONBOARDING.md` is not found at either location after the agent completes, mark the step as `failed` and report the error.

### 4. Write step-result.json

Extract metrics from the analysis files at `LEARN_CODE_BASE` (not from `OUTPUT_DIR` — analysis files are not copied):

- **module_count**: `${LEARN_CODE_BASE}/module-registry/registry.json` is a JSON **array** — the count is its length (e.g. `len(json.load(f))` or `jq length`).
- **relationship_count**: count of `.json` files in `${LEARN_CODE_BASE}/relationships/`.
- **languages_detected**: read `${LEARN_CODE_BASE}/detection/detection.json` (a JSON object) — use the keys of `language_counts`, or fall back to `primary_language` as a single-element list.

Write the sidecar:

```json
{
  "schema_version": 1,
  "step": "code-analysis",
  "ticket": "<TICKET>",
  "completed_at": "<ISO 8601>",
  "module_count": "<length of registry.json array>",
  "relationship_count": "<count of .json files in relationships/>",
  "languages_detected": ["<keys from detection.json language_counts>"],
  "repo_path": "<absolute path to repo>",
  "repo_analysis_path": "<absolute path to LEARN_CODE_BASE>"
}
```

### 5. Report completion

Print summary:
```
Code analysis complete:
- Modules: <N>
- Relationships: <N>
- Languages: <list>
- Output: <output-dir>
```

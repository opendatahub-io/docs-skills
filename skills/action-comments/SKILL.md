---
name: action-comments
description: Fetch unresolved review comments from GitHub PRs or GitLab MRs and interactively action them on local files. Works standalone or as a workflow step (with --base-path). MUST BE USED when the user asks to action, address, or process review comments on a PR/MR, or when the docs-review-comments workflow is running.
argument-hint: "[url] [--include-resolved] [--base-path <path>]"
allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Agent, AskUserQuestion
---

# Action Review Comments

Fetch unresolved review comments from a GitHub PR or GitLab MR and interactively action them on local files.

## Arguments

| Argument | Description |
|----------|-------------|
| `$1` (positional) | PR/MR URL (optional — auto-detects from current branch if omitted) |
| `--include-resolved` | Include resolved comments in addition to unresolved |
| `--base-path <path>` | Workflow step mode: write `step-result.json` sidecar to this path |

## Step 0: Load workspace context (if available)

Check whether a `.agent_workspace/` directory exists in the current repository root with artifacts from a prior docs-workflow run. This step is **automatic** — no user input required.

```bash
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
```

If `--base-path` was provided, use that directly as `WORKSPACE`. Otherwise, probe for a workspace:

1. Look for `.agent_workspace/` under `REPO_ROOT`
2. If it exists, list ticket directories inside it. If exactly one exists, use it. If multiple exist, pick the one whose `create-merge-request/step-result.json` contains a `url` matching `PR_URL` (resolved in Step 1). If no match or PR_URL is not yet known, defer selection until after Step 1 and re-check.

Set `WORKSPACE` to the matched ticket directory (e.g., `.agent_workspace/proj-123/`), or `null` if no workspace is found.

When `WORKSPACE` is set, read the following artifacts if they exist — do not fail if any are missing:

| Artifact | Path | Use |
|----------|------|-----|
| Code analysis | `${WORKSPACE}/code-analysis/ONBOARDING.md` | API surfaces, module maps, code structure — verify reviewer claims about APIs, configs, commands |
| Requirements | `${WORKSPACE}/requirements/requirements.md` | Original ticket requirements — check whether a reviewer's suggestion is in scope |
| Technical review | `${WORKSPACE}/technical-review/review.md` | Prior validated claims — avoid re-introducing issues the tech review already flagged |
| Scope audit | `${WORKSPACE}/scope-req-audit/step-result.json` | Evidence classification per requirement — know which features are grounded vs absent in code |
| Source config | `${WORKSPACE}/source.yaml` | Source repo path — if the cloned repo still exists locally, use it for direct code verification |

If `source.yaml` exists and its `repo_path` points to a valid local directory, set `SOURCE_REPO` to that path. This enables direct code lookups when verifying reviewer comments about specific APIs, flags, or config options.

Log what was loaded:

> Workspace context loaded from `{WORKSPACE}`: code-analysis: {yes/no}, requirements: {yes/no}, technical-review: {yes/no}, scope-audit: {yes/no}, source-repo: {yes/no}

If no workspace is found, log nothing and proceed without grounding — the skill works standalone.

## Step 1: Resolve PR/MR URL

If URL provided, use directly. If omitted, auto-detect:
```bash
PR_URL=$(python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py detect 2>/dev/null)
```

If detection fails, stop with:

> Could not detect a PR/MR for the current branch. Please provide a URL and try again.

## Step 2: Get PR info and check out the branch locally

Fetch PR metadata to determine the source branch:

```bash
HEAD_REF=$(python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py info "${PR_URL}" --field head_ref)
BASE_REF=$(python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py info "${PR_URL}" --field base_ref)
TITLE=$(python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py info "${PR_URL}" --field title)
```

Check whether the current branch matches `head_ref`:

```bash
CURRENT_BRANCH=$(git branch --show-current)
```

**If already on the correct branch**: proceed to Step 3.

**If on a different branch**:

1. Check for uncommitted changes:
   ```bash
   git status --porcelain
   ```
   If there are uncommitted changes, stop with:
   > You have uncommitted changes on `{CURRENT_BRANCH}`. Please commit or stash them before switching branches.

2. Fetch and check out the PR branch:
   ```bash
   git fetch origin "${HEAD_REF}"
   git checkout "${HEAD_REF}"
   ```

   If the branch does not exist locally, create a tracking branch:
   ```bash
   git checkout -b "${HEAD_REF}" "origin/${HEAD_REF}"
   ```

Report to the user:

> Checked out branch `{HEAD_REF}` for PR: {title}

## Step 3: Fetch review comments

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py comments "${PR_URL}" --json
```

Add `--include-resolved` if the `--include-resolved` flag was passed.

The script automatically filters bot comments, resolved threads (unless `--include-resolved`), and returns top-level comments with: `id`, `path`, `line`, `body`, `author`, `resolved`.

If no comments are returned, report:

> No unresolved review comments found on this PR/MR.

And stop. If in workflow step mode, write a minimal step-result.json (see Step 6).

## Step 4: Categorize comments

Before presenting comments, categorize each one:

| Category | Criteria | Action |
|----------|----------|--------|
| **Required** | Technical errors, broken examples, incorrect commands, style violations | Must fix |
| **Suggestion** | Improvements, alternative approaches, wording changes, reorganization | User discretion |
| **Question** | Requests for clarification, questions from reviewer | Present but do not auto-suggest a fix |
| **Outdated** | Already addressed by subsequent commits | Skip automatically |

For **Outdated** detection: read the file at the comment's `path` and `line`. If the content no longer matches what the comment references, mark as outdated. Extract the reviewer's quoted text from markdown blockquotes (`>` lines) in the `body` field. If no blockquotes are present, fall back to comparing against the line context.

## Step 5: Process each comment interactively

For each non-outdated comment, present:

```markdown
## Comment {N} of {total} from @{author} on `{path}:{line}` [{category}]

> {comment_body}

### Current content (local file)
{relevant lines from the local file around the comment's line}

### Suggested change
{your analysis and proposed edit, grounded in workspace context if available}
```

### Grounding fixes with workspace context

When `WORKSPACE` is set and the comment references technical content (API fields, commands, config options, prerequisites), use the loaded artifacts to verify and inform your suggested change:

- **Code analysis available**: Check `ONBOARDING.md` for the API surface, module map, or code structure relevant to the comment. If the reviewer says "this flag doesn't exist", verify against the code analysis before agreeing or pushing back.
- **Source repo available** (`SOURCE_REPO` is set): Read the actual source file to verify claims about specific APIs, config keys, default values, or command syntax. Use `grep` or `Read` against the source repo — do not guess.
- **Requirements available**: If the reviewer suggests adding content, check whether it falls within the original ticket scope. If out of scope, note this when presenting the suggested change.
- **Technical review available**: Cross-reference with prior review findings. If the tech review already validated a claim the reviewer is questioning, cite the validation.
- **Scope audit available**: Check evidence status for the requirement the comment relates to. If the feature is classified as `absent` in the code, the reviewer's request to add documentation may need a "not supported" note instead.

If workspace context contradicts the reviewer's comment, present both perspectives and let the user decide. Do not silently override the reviewer.

Call AskUserQuestion with these options:

| Option | Description |
|--------|-------------|
| Apply | Apply the suggested change |
| Edit | Apply with modifications — ask for user's preferred text |
| Skip | Skip this comment |
| View context | Show more surrounding lines, then re-ask |

**When Apply is selected**: Read the target file, apply the edit using Edit tool, confirm the change was applied, move to next comment.

**When Edit is selected**: Call AskUserQuestion with `textInput: true`:

> Enter the text you'd like to use instead:

Apply the user's text using Edit tool, confirm, move to next.

**When View context is selected**: Read 20 lines before and after the comment's line from the local file, display them, then re-present the same options.

**When Skip is selected**: Move to next comment.

## Step 6: Summary

After all comments are processed, present:

```markdown
## Action Comments Summary

**PR/MR**: {PR_URL}
**Branch**: {HEAD_REF}
**Workspace grounding**: {WORKSPACE path | "none"}

| Metric | Count |
|--------|-------|
| Total comments | X |
| Applied | Y |
| Edited | Z |
| Skipped | S |
| Outdated (auto-skipped) | O |
| Bot comments (filtered) | B |

### Changes applied

1. `{path}:{line}` — {brief description of change}
2. ...

### Comments skipped

1. `{path}:{line}` — @{author}: "{truncated comment}" — Reason: {user skipped / outdated}
```

If any changes were applied, remind the user:

> Changes have been applied to your local files on branch `{HEAD_REF}`. Review them with `git diff` and commit when ready.

### Workflow step mode (`--base-path`)

When `--base-path` is provided, write `${BASE_PATH}/action-comments/step-result.json` after the summary:

```json
{
  "schema_version": 1,
  "step": "action-comments",
  "ticket": "<TICKET>",
  "completed_at": "<ISO 8601>",
  "comments_resolved": <count of applied + edited>,
  "comments_deferred": 0,
  "comments_skipped": <count of user-skipped>,
  "comments_outdated": <count of auto-skipped outdated>,
  "files_modified": ["<list of files modified>"]
}
```

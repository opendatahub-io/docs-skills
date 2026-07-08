---
name: action-comments
description: Fetch unresolved review comments from GitHub PRs or GitLab MRs and action them on local files. Works standalone (interactive) or in CI mode (autonomous). Optionally reads .agent_workspace artifacts for grounding. MUST BE USED when the user asks to action, address, or process review comments on a PR/MR.
argument-hint: "[url] [--ci] [--include-resolved] | <ticket> --base-path <path> [--ci] [url]"
allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Agent, AskUserQuestion
---

# Action Review Comments

Action review comments on local files: interactive by default, autonomous in CI (auto-detected, or forced with `--ci`).

## Arguments

### Standalone mode

| Argument | Description |
|----------|-------------|
| `$1` (positional) | PR/MR URL (optional — auto-detects from current branch if omitted) |
| `--ci` | Force autonomous mode (no interactive prompts): auto-applies fixes, commits+pushes, and posts reply comments explaining rationale. When omitted, CI mode is **auto-detected** from the `CI`/`GITHUB_ACTIONS`/`GITLAB_CI` env vars (pass `--no-ci` to force interactive) |
| `--include-resolved` | Include resolved comments in addition to unresolved |

### Workflow step mode

| Argument | Description |
|----------|-------------|
| `$1` (positional) | Ticket ID (required, e.g., `PROJ-123`) |
| `--base-path <path>` | Base output path (required). Used to **read** workspace artifacts from prior workflow steps (code-analysis, requirements, etc.) and to **write** `step-result.json` sidecar to `${BASE_PATH}/action-comments/` |
| `--pr <url>` | PR/MR URL (optional — auto-detects from current branch if omitted) |
| `--ci` | Same as standalone mode |
| `--include-resolved` | Same as standalone mode |

## Step 0: Resolve run mode (CI vs interactive)

Determine whether to run autonomously. Explicit flags win; otherwise CI is auto-detected from the environment (so a CI cron job needs no flag):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/action_comments.py resolve-mode ${CI_FLAG}
```

Pass `--ci` or `--no-ci` in `${CI_FLAG}` only if the user supplied one; otherwise pass nothing. The script prints `{"ci_mode": <bool>, "reason": "..."}`. Use `ci_mode` for all later branching.

In CI mode, **ignore `--include-resolved`** — re-actioning resolved threads is never wanted autonomously.

## Step 1: Resolve PR/MR URL

If a URL was provided (positional `$1` in standalone mode, or `--pr` in workflow step mode), use it directly. If omitted, auto-detect:
```bash
PR_URL=$(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py detect 2>/dev/null)
```

If detection fails, stop with:

> Could not detect a PR/MR for the current branch. Please provide a URL and try again.

**Validate the URL format** — after `PR_URL` is set (whether from direct input or auto-detection), validate it:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/action_comments.py validate-url "${PR_URL}"
```

Exit code `0` means valid; non-zero means invalid. If invalid, stop with:

> Invalid PR/MR URL: `{PR_URL}`. Expected `https://{host}/{owner}/{repo}/pull/{n}` (GitHub) or `https://{host}/{namespace}/{project}/merge_requests/{n}` (GitLab); public and self-hosted both supported.

## Step 2: Load workspace context (if available)

Resolve the workspace directory and discover which grounding artifacts exist. This step is **automatic** — no user input required:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
python3 ${CLAUDE_SKILL_DIR}/scripts/action_comments.py workspace \
  --repo-root "${REPO_ROOT}" ${BASE_PATH_ARG} --pr "${PR_URL}"
```

Pass `--base-path <path>` in `${BASE_PATH_ARG}` only in workflow step mode. The script prints:

```json
{"workspace": "<path|null>", "artifacts": {"code_analysis": true, ...}, "source_repo": "<path|null>"}
```

Set `WORKSPACE` to `workspace`. If `source_repo` is non-null, set `SOURCE_REPO` to it — used for direct code verification.

**Load artifacts** — for each artifact reported `true`, read the file below (uses detailed in Step 6 "Grounding fixes with workspace context"):

| Artifact | Path |
|----------|------|
| Code analysis | `${WORKSPACE}/code-analysis/ONBOARDING.md` |
| Requirements | `${WORKSPACE}/requirements/requirements.md` |
| Technical review | `${WORKSPACE}/technical-review/review.md` |
| Scope audit | `${WORKSPACE}/scope-req-audit/step-result.json` |
| Source config | `${WORKSPACE}/source.yaml` (already resolved into `SOURCE_REPO`) |

Log what was loaded:

> Workspace context loaded from `{WORKSPACE}`: code-analysis/requirements/technical-review/scope-audit/source-repo {yes/no each}

If no workspace is found, proceed without grounding — the skill works standalone.

## Step 3: Get PR info and check out the branch locally

Fetch PR metadata:

```bash
HEAD_REF=$(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py info "${PR_URL}" --field head_ref)
TITLE=$(uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py info "${PR_URL}" --field title)
```

**Validate the ref and decide the checkout action** (guards against unsafe refs, reports whether a checkout is needed):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/action_comments.py checkout-plan \
  --head-ref "${HEAD_REF}" --current-branch "$(git branch --show-current)"
```

Exit code `2` means the ref is unsafe — stop with:

> Unsafe branch ref detected: `{HEAD_REF}`. Branch names may contain only letters, digits, `.`, `-`, `_`, and `/`.

Otherwise the script prints `{"head_ref": "...", "on_target_branch": <bool>}`.

**If `on_target_branch` is `true`**: proceed to Step 4. **If `false`**, switch branches:

1. If `git status --porcelain` shows uncommitted changes, stop: "You have uncommitted changes. Please commit or stash them before switching branches."
2. Fetch and check out (creating a tracking branch if not local):
   ```bash
   git fetch origin "${HEAD_REF}"
   git checkout "${HEAD_REF}" 2>/dev/null || git checkout -b "${HEAD_REF}" "origin/${HEAD_REF}"
   ```

Report: `Checked out {HEAD_REF} for PR: {title}`

## Step 4: Fetch review comments

```bash
uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py comments "${PR_URL}" --json
```

Add `--include-resolved` only in interactive mode if the flag was passed (ignore it in CI mode — see Step 0).

The script filters bot comments and resolved threads (unless `--include-resolved`) and returns top-level comments with: `id`, `path`, `line`, `body`, `author`, `resolved`, `has_bot_reply`, `position_outdated` (GitLab MRs also carry `discussion_id`).

**Idempotency (CI cron):** in CI mode, **skip any comment where `has_bot_reply` is `true`** — it already got a reply on a prior run, which is what makes repeated cron runs safe. Save the raw JSON to a file (e.g. `comments.json`) for the next step.

If no comments are returned, report:

> No unresolved review comments found on this PR/MR.

And stop. If in workflow step mode, write a minimal step-result.json (see Step 7).

## Step 5: Categorize comments

Categorize each comment:

| Category | Criteria | Action |
|----------|----------|--------|
| **Required** | Technical errors, broken examples, incorrect commands, style violations | Must fix |
| **Suggestion** | Improvements, alternative approaches, wording changes, reorganization | User discretion |
| **Question** | Requests for clarification, questions from reviewer | Present but do not auto-suggest a fix |
| **Outdated** | Already addressed by subsequent commits | Skip automatically |

**Outdated detection** — annotate each comment with an `outdated` flag (forge `position_outdated` signal + file-existence check):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/action_comments.py classify-outdated \
  --repo-root "${REPO_ROOT}" --comments-file comments.json
```

The script echoes the comments JSON with `outdated` added per comment; auto-skip those where it is `true`.

## Step 6: Process comments

For each non-outdated comment, read the target file and prepare a suggested change grounded in workspace context (below). Then follow the **interactive** or **CI** path per `ci_mode` (Step 0).

### Grounding fixes with workspace context

**Reviewers are SMEs who know the technology — treat every reasonable comment as authoritative and action it.** Try to ground each change in `.agent_workspace` evidence (or the source repo it points to). When the workspace confirms the comment, apply it. When you **cannot find evidence either way**, still apply the change, but note in the reply/summary that it isn't backed by workspace evidence. Use grounding to inform and strengthen the change, not as a gate that blocks it. When `WORKSPACE` is set and the comment references technical content (API fields, commands, config options, prerequisites), use the loaded artifacts:

- **Code analysis** (`ONBOARDING.md`): check reviewer claims about APIs/flags/structure to inform the change.
- **Source repo** (`SOURCE_REPO` set): `grep`/`Read` the source to verify APIs, config keys, defaults, command syntax — don't guess.
- **Requirements**: for suggested additions, check they're in the original ticket scope; note when they aren't.
- **Technical review**: cite any prior tech-review validation of a claim the reviewer questions.
- **Scope audit**: if a requirement is classified `absent` in code, the request may need a "not supported" note instead.

### Interactive mode (default)

For each non-outdated comment, present:

```markdown
## Comment {N} of {total} from @{author} on `{path}:{line}` [{category}]

> {comment_body}

### Current content (local file)
{relevant lines from the local file around the comment's line}

### Suggested change
{your analysis and proposed edit, grounded in workspace context if available}
```

If the workspace doesn't back the comment, still propose the edit — note the lack of evidence in your suggested change rather than withholding it.

Call AskUserQuestion with these options:

| Option | Description |
|--------|-------------|
| Apply | Apply the suggested change |
| Edit | Apply with modifications — ask for user's preferred text |
| Skip | Skip this comment |
| View context | Show more surrounding lines, then re-ask |

- **Apply**: apply the suggested change with the Edit tool. **Edit**: call AskUserQuestion with `textInput: true` ("Enter the text you'd like to use instead:") and apply the user's text. In both cases, read back the changed lines to verify the expected text is present; if the edit errors or verification fails, report `Failed to apply edit to {path}:{line}.` and call AskUserQuestion with **Retry** (re-read and retry) or **Skip**.
- **View context**: read 20 lines before and after the comment's line, display them, then re-present the same options.
- **Skip**: move to next comment.

### CI mode (`ci_mode` true)

No interactive prompts. First skip comments with `has_bot_reply: true` (Step 4). For each remaining non-outdated comment, autonomously decide and act based on category and workspace context.

**Preconditions** — a CI cron needs a write-scoped `GITHUB_TOKEN` (or `GITLAB_TOKEN`) to push and post replies. If it's missing, stop early with a clear error rather than applying edits that can't be pushed.

#### Decision logic by category

| Category | Action |
|----------|--------|
| **Required** | Apply the fix; if ambiguous or not cleanly appliable, log a warning and skip |
| **Suggestion** | Apply if it aligns with requirements/scope and is straightforward; skip if out-of-scope, subjective, or needs major restructuring |
| **Question** | Don't edit; post a reply answering it from workspace context |
| **Outdated** | Auto-skip (already handled in Step 5) |

**Unverified comments (cross-category):** if you cannot find evidence in `.agent_workspace` or the source repo either way, still apply the change (the reviewer is an SME) and note in the reply that it wasn't backed by workspace evidence. Absence of evidence is never grounds to skip.

For each comment, log the decision:

```text
[{N}/{total}] {path}:{line} [{category}] → {Applied|Applied (unverified)|Skipped|Replied} — {one-line rationale}
```

#### Applying changes in CI mode

Same as interactive mode: read the file, apply the edit, read back changed lines to verify. On failure, log it and move to the next comment (no retry loop).

#### Committing and pushing in CI mode

After **all** comments are processed, if any files were modified, commit and push to the PR branch (otherwise the edits are lost when the job ends). Run once, after the loop:

```bash
git add -A  # stage edits and new files
git -c user.name="action-comments[bot]" \
    -c user.email="action-comments@users.noreply.github.com" \
    commit -m "docs: action review comments [skip ci]"
git push origin HEAD:"${HEAD_REF}"
```

`[skip ci]` avoids retriggering the pipeline. If `git push` fails (protected branch, non-fast-forward, missing token), log the error and continue to reply-posting — don't abort the run.

#### Posting reply comments

After processing each comment (applied, skipped, or answered), post a reply on the thread explaining the action.

**Reply body format** (passed as `REPLY_BODY`):

```text
**{Action}** — {rationale}

{If change was applied: "Applied to `{path}` — {brief description of what changed}"}
{If question was answered: the answer, grounded in workspace context}
{If no workspace evidence was found: "Applied on reviewer authority — not verified against workspace evidence."}
```

**Routing flag** (from the Step 4 JSON): GitHub → `--comment-id "${COMMENT_ID}"` (the comment's `id`); GitLab → `--discussion-id "${DISCUSSION_ID}"`. Keep `--signoff` exactly `Claude Code action-comments (CI)` — that string is how `has_bot_reply` detects prior replies for idempotency.

```bash
uv run --script ${CLAUDE_PLUGIN_ROOT}/skills/git-pr-reader/scripts/git_pr_reader.py \
  reply "${PR_URL}" ${ROUTING_FLAG} \
  --body "${REPLY_BODY}" --signoff "Claude Code action-comments (CI)"
```

If the reply post fails (non-zero exit code), log a warning and continue — do not block on reply failures.

## Step 7: Summary

After all comments are processed, present a summary with: PR/MR URL, branch, workspace grounding (path or "none"); a count table (total, applied, edited, skipped, outdated); a **Changes applied** list (`{path}:{line}` — description, flagging any applied without workspace evidence); and a **Comments skipped** list (`{path}:{line}` — @author: reason).

In **interactive** mode, if any changes were applied, remind the user:

> Changes have been applied to your local files on branch `{HEAD_REF}`. Review them with `git diff` and commit when ready.

In **CI** mode the changes were already committed and pushed (Step 6).

### Workflow step mode (`--base-path`)

When `--base-path` is provided, write the `step-result.json` sidecar via the script (never hand-author the JSON):

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/action_comments.py write-result \
  --base-path "${BASE_PATH}" --ticket "${TICKET}" ${CI_MODE_FLAG} \
  --comments-resolved <applied+edited> \
  --comments-skipped <skipped> \
  --comments-outdated <outdated> \
  --comments-replied <replies posted> \
  --files-modified <path1> <path2> ...
```

Comments applied without workspace evidence still count as resolved (`--comments-resolved`) — the note lives in the reply/summary, not a separate counter.

Pass `--ci-mode` in `${CI_MODE_FLAG}` when `ci_mode` is true (sets `comments_replied` to the count of replies successfully posted). In interactive mode omit it; `comments_replied` is `0`.

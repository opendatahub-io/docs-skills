# Argument Reference

When displaying available options to the user (e.g., on skill load or when asking for flags), reproduce the descriptions below **verbatim** — do not summarize or paraphrase them.

- `$1` — JIRA ticket ID (required). If missing, STOP and ask the user.
- `--workflow <name>` — Use `.agent_workspace/docs-<name>.yaml` instead of `docs-workflow.yaml`. Allows running alternative pipelines (e.g., writing-only, review-only). If the project-level file does not exist, fall back to the matching plugin default at `skills/docs-orchestrator/defaults/docs-<name>.yaml`
- `--pr <url>...` — PR/MR URLs (space-delimited, one or more). Accepts GitHub PRs (`gh` CLI) and GitLab MRs (`glab` CLI). Used both as requirements input (agent reads diffs/descriptions) and for source repo resolution (repo URL and branch derived from the first PR/MR). When multiple PRs from different repos are provided, all repos are resolved and treated equally as source material
- `--mkdocs` — Use Material for MkDocs format instead of AsciiDoc. Propagates to the writing step (generates `.md` with MkDocs front matter) and style-review step (applies Markdown-appropriate rules). Sets `options.format` to `"mkdocs"` in the progress file
- `--draft` — Write documentation to the staging area (`.agent_workspace/<ticket>/writing/`) instead of directly into the repo. Uses DRAFT placement mode: no framework detection, no file placement into the target repo. Without this flag, UPDATE-IN-PLACE is the default
- `--docs-repo-path <path>` — Target documentation repository for UPDATE-IN-PLACE mode. The docs-writer explores this directory for framework detection (Antora, MkDocs, Docusaurus, etc.) and writes files there instead of the current working directory. Propagates to `writing` and `create-merge-request` steps (mapped to their internal `--repo-path` flag). **Precedence**: if both `--docs-repo-path` and `--draft` are passed, `--docs-repo-path` wins — log a warning and ignore `--draft`
- `--source-code-repo <url-or-path>...` — Source code repository/repositories for code analysis and requirements enrichment (space-delimited, one or more). Accepts remote URLs (https://, git@, ssh:// — each shallow-cloned to `.agent_workspace/<ticket>/code-repo/<repo_name>/`) or local paths (used directly). The first repo is treated as primary; additional repos are returned as `additional_repos` in the result. Passed to requirements, code-analysis, writing, and technical-review steps (mapped to their internal `--repo` flag). Without `--pr`, the entire repo is the subject matter; with `--pr`, the PR branch is checked out on the primary repo so code-analysis reflects the PR's state. Takes highest priority in source resolution, overriding `source.yaml` and PR-derived URLs
- `--create-jira <PROJECT>` — Create a linked JIRA ticket in the specified project after the planning step completes. Runs the standalone `docs-workflow-create-jira` workflow (use `--workflow workflow-create-jira`). Requires `JIRA_API_TOKEN` to be set
- `--create-merge-request` — Create a branch, commit, push, and open a merge request or pull request after reviews complete. Activates the `create-merge-request` workflow step (guarded by `when: create_merge_request`). Off by default
- `--no-source-repo` — Skip source repo resolution and all source-dependent steps (scope-req-audit). The workflow runs without source grounding. Use for tickets with no associated source code repository, or pass on resume after the workflow stops due to no repo being found
- `--auto-discover-repos` — Skip the confirmation prompt when secondary repos are discovered by scope-req-audit. Useful for CI/automation where interactive prompts are not available. Has no effect if no secondary repos are found
- `--max-secondary-repos <N>` — Maximum number of secondary repos to clone after scope-req-audit (default: 3). Repos are ranked by the number of associated requirements

## Examples

```bash
# Minimal — just a ticket
/docs-orchestrator PROJ-123

# PR-driven with MkDocs output
/docs-orchestrator PROJ-123 --pr https://github.com/org/repo/pull/42 --mkdocs

# Multiple PRs from different repos, written to a separate docs repo
/docs-orchestrator PROJ-123 \
  --pr https://github.com/org/backend/pull/10 https://gitlab.example.com/org/frontend/-/merge_requests/5 \
  --docs-repo-path /home/user/docs-repo

# Source repo without PRs, draft mode, with merge request creation
/docs-orchestrator PROJ-123 \
  --source-code-repo https://github.com/org/operator \
  --draft \
  --create-merge-request

# Local source repo + PR (checks out PR branch within repo)
/docs-orchestrator PROJ-123 \
  --source-code-repo /home/user/local-checkout \
  --pr https://github.com/org/repo/pull/99

# Custom workflow YAML
/docs-orchestrator PROJ-123 --workflow quick
```

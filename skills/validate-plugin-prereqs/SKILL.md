---
name: validate-plugin-prereqs
description: Check that all environment variables and CLI tools required by the docs-skills plugin are available. Use when setting up a new environment, troubleshooting missing prerequisites, or before running a workflow for the first time.
---

# Validate plugin prerequisites

Run the prerequisite checker:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/validate_prereqs.sh
```

The script loads `~/.env` and `./.env`, then checks all required and optional environment variables and CLI tools. It prints a human-readable table and exits with code 0 (all required items present) or 1 (something missing).

If any required items are missing, tell the user what's needed and how to fix it:

- **`JIRA_API_TOKEN`** / **`JIRA_EMAIL`**: Add to `~/.env` or `.env`. Required for JIRA-related skills (jira-reader, jira-writer, create-jira, jira-ready).
- **`GITHUB_TOKEN`**: Add to `~/.env` or `.env`. Needed for GitHub-based skills (git-pr-reader, understand-pull-request).
- **`GITLAB_TOKEN`**: Add to `~/.env` or `.env`. Needed only for GitLab-based repositories.
- **`python3`**: Install Python 3.10+.
- **`uv`**: Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- **`git`**: Install via system package manager.
- **`jq`**: Install via system package manager.
- **`gh`**: Install from https://cli.github.com/.
- **`glab`**: Install from https://gitlab.com/gitlab-org/cli. Required for GitLab workflows (create-merge-request, git-pr-reader).
- **`vale`**: Install from https://vale.sh/docs/install/. Optional — only needed for style review skills.
- **`shellcheck`** / **`ruff`**: Optional dev/CI tools.

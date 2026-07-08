#!/bin/bash
# Set up docs repo checkout for an eval case
# Called by the eval harness before each case runs
# Usage: bash eval/scripts/setup-case-docs-repo.sh <case_dir>
# Outputs the docs_repo_path to stdout (for the harness to use in arguments)

set -euo pipefail

CASE_DIR="$1"
INPUT_YAML="${CASE_DIR}/input.yaml"
DOCS_REPO_CACHE="eval/.docs-repo-cache"
CASE_DOCS_WORKTREE="${CASE_DIR}/.docs-repo"

if [ ! -f "$INPUT_YAML" ]; then
  echo "ERROR: No input.yaml found at ${INPUT_YAML}" >&2
  exit 1
fi

# Extract docs_repo SHA from input.yaml
DOCS_SHA=$(python3 -c "
import yaml, sys
data = yaml.safe_load(open('${INPUT_YAML}'))
docs = data.get('docs_repo', {})
print(docs.get('sha', ''))
")

if [ -z "$DOCS_SHA" ]; then
  echo "WARNING: No docs_repo.sha in ${INPUT_YAML} — using HEAD" >&2
  DOCS_SHA="HEAD"
fi

# Check if docs repo cache exists
if [ ! -d "${DOCS_REPO_CACHE}/.git" ]; then
  echo "ERROR: Docs repo cache not found at ${DOCS_REPO_CACHE}. Run: bash eval/scripts/pin-docs-repo.sh" >&2
  exit 1
fi

# Create a worktree for this case at the pinned SHA
if [ -d "$CASE_DOCS_WORKTREE" ]; then
  # Clean up existing worktree
  git -C "$DOCS_REPO_CACHE" worktree remove --force "$(cd "$CASE_DOCS_WORKTREE" && pwd)" 2>/dev/null || rm -rf "$CASE_DOCS_WORKTREE"
fi

git -C "$DOCS_REPO_CACHE" worktree add --detach "$(pwd)/${CASE_DOCS_WORKTREE}" "$DOCS_SHA" 2>/dev/null

# Output the absolute path for the harness
(cd "$CASE_DOCS_WORKTREE" && pwd)

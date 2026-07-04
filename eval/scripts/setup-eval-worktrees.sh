#!/bin/bash
# Create docs repo worktrees for each eval case
# Run after pin-docs-repo.sh has populated docs_repo.sha in each input.yaml
# Usage: bash eval/scripts/setup-eval-worktrees.sh
# Requires: eval/.docs-repo-cache to exist (from pin-docs-repo.sh)

set -euo pipefail

EVAL_DIR="eval/cases"
DOCS_REPO_CACHE="eval/.docs-repo-cache"
PROJECT_ROOT="$(pwd)"

if [ ! -d "${DOCS_REPO_CACHE}/.git" ]; then
  echo "ERROR: Docs repo cache not found. Run: bash eval/scripts/pin-docs-repo.sh" >&2
  exit 1
fi

# Clean up any existing worktrees from previous runs
echo "Cleaning up old worktrees..."
git -C "$DOCS_REPO_CACHE" worktree prune 2>/dev/null || true

for case_dir in ${EVAL_DIR}/case-*/; do
  case_name=$(basename "$case_dir")
  input_yaml="${case_dir}/input.yaml"

  if [ ! -f "$input_yaml" ]; then
    echo "SKIP ${case_name}: no input.yaml"
    continue
  fi

  # Extract docs_repo SHA
  docs_sha=$(python3 -c "
import yaml
data = yaml.safe_load(open('${input_yaml}'))
docs = data.get('docs_repo', {})
print(docs.get('sha', ''))
")

  if [ -z "$docs_sha" ]; then
    echo "SKIP ${case_name}: no docs_repo.sha"
    continue
  fi

  worktree_path="${PROJECT_ROOT}/${case_dir}.docs-worktree"

  # Remove existing worktree if present
  if [ -d "$worktree_path" ]; then
    git -C "$DOCS_REPO_CACHE" worktree remove --force "$worktree_path" 2>/dev/null || rm -rf "$worktree_path"
  fi

  echo "=== ${case_name} ==="

  if [ "$docs_sha" = "HEAD" ]; then
    # For HEAD cases, use the default branch
    default_branch=$(git -C "$DOCS_REPO_CACHE" symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||' || echo "main")
    git -C "$DOCS_REPO_CACHE" worktree add --detach "$worktree_path" "origin/${default_branch}" 2>/dev/null
    echo "  Worktree: ${default_branch} HEAD"
  else
    git -C "$DOCS_REPO_CACHE" worktree add --detach "$worktree_path" "$docs_sha" 2>/dev/null
    echo "  Worktree: ${docs_sha:0:12}"
  fi

  # Write docs_repo_path into input.yaml if not already present
  if grep -q "docs_repo_path:" "$input_yaml" 2>/dev/null; then
    # Update existing path
    python3 -c "
import yaml
data = yaml.safe_load(open('${input_yaml}'))
data['docs_repo_path'] = '${worktree_path}'
with open('${input_yaml}', 'w') as f:
    yaml.dump(data, f, default_flow_style=False, sort_keys=False)
"
    echo "  Updated docs_repo_path in input.yaml"
  else
    # Append
    echo "docs_repo_path: ${worktree_path}" >> "$input_yaml"
    echo "  Added docs_repo_path to input.yaml"
  fi
done

echo ""
echo "Done. All worktrees created. Run /eval-run to execute the evaluation."
echo "To clean up worktrees: git -C eval/.docs-repo-cache worktree prune"

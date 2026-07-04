#!/bin/bash
# Pin docs repo SHA per eval case — finds the commit just before each gold standard MR merged
# Run from project root with: bash eval/scripts/pin-docs-repo.sh
# Requires: glab authenticated to gitlab.cee.redhat.com, VPN connected

set -euo pipefail

PROJECT_ID=82936
EVAL_DIR="eval/cases"
DOCS_REPO_CLONE="eval/.docs-repo-cache"
DOCS_REPO_URL="https://gitlab.cee.redhat.com/documentation-red-hat-openshift-data-science-documentation/openshift-ai-documentation.git"

# Gold standard cases: case_dir | MR_IID | target_branch
declare -A CASES=(
  ["case-001-rhoaieng-45969"]="2664"
  ["case-006-rhai-eng-2388"]="2697"
  ["case-007-rhai-eng-4485"]="2691"
  ["case-008-rhai-eng-2620"]="2380"
  ["case-009-rhai-eng-1550"]="2104"
  ["case-010-rhaieng-653"]="1938"
  ["case-011-rhoaieng-16840"]="2680"
  ["case-012-rhoaieng-40664"]="2574"
)

# Step 1: Clone docs repo if not cached (full clone for history)
if [ ! -d "$DOCS_REPO_CLONE/.git" ]; then
  echo "Cloning docs repo (full history)..."
  git clone "$DOCS_REPO_URL" "$DOCS_REPO_CLONE"
else
  echo "Using cached docs repo clone, fetching latest..."
  git -C "$DOCS_REPO_CLONE" fetch origin
fi

# Step 2: For each gold standard case, find the commit just before the MR merged
for case_name in "${!CASES[@]}"; do
  mr_iid="${CASES[$case_name]}"
  echo ""
  echo "=== ${case_name} (MR-${mr_iid}) ==="

  # Get MR merge details from GitLab API
  mr_json=$(glab api --hostname gitlab.cee.redhat.com "projects/${PROJECT_ID}/merge_requests/${mr_iid}" 2>/dev/null)

  merged_at=$(echo "$mr_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['merged_at'])")
  target_branch=$(echo "$mr_json" | python3 -c "import json,sys; print(json.load(sys.stdin)['target_branch'])")
  merge_commit=$(echo "$mr_json" | python3 -c "import json,sys; print(json.load(sys.stdin).get('merge_commit_sha',''))")

  echo "  Merged at: ${merged_at}"
  echo "  Target branch: ${target_branch}"
  echo "  Merge commit: ${merge_commit}"

  # Find the commit on the target branch just before the merge
  # Use the merge commit's parent on the target branch
  if [ -n "$merge_commit" ]; then
    # Get the first parent of the merge commit (the target branch side)
    pre_merge_sha=$(git -C "$DOCS_REPO_CLONE" rev-parse "${merge_commit}^1" 2>/dev/null || echo "")
  fi

  if [ -z "$pre_merge_sha" ]; then
    # Fallback: find latest commit on target branch before merge timestamp
    git -C "$DOCS_REPO_CLONE" checkout -q "origin/${target_branch}" 2>/dev/null || git -C "$DOCS_REPO_CLONE" checkout -q "${target_branch}" 2>/dev/null
    pre_merge_sha=$(git -C "$DOCS_REPO_CLONE" log --before="${merged_at}" --format="%H" -1 2>/dev/null || echo "UNKNOWN")
  fi

  echo "  Pre-merge SHA: ${pre_merge_sha}"

  # Update the case's input.yaml with docs_repo info
  input_file="${EVAL_DIR}/${case_name}/input.yaml"
  if [ -f "$input_file" ]; then
    # Check if docs_repo section already exists
    if grep -q "docs_repo:" "$input_file"; then
      echo "  docs_repo already in input.yaml — skipping"
    else
      # Append docs_repo section
      cat >> "$input_file" << YAML
docs_repo:
  url: ${DOCS_REPO_URL}
  sha: ${pre_merge_sha}
  branch: ${target_branch}
YAML
      echo "  Updated input.yaml with docs_repo"
    fi
  fi
done

echo ""
echo "Done. Each gold standard case now has a docs_repo SHA pinned to the state before its MR merged."
echo "The docs repo cache is at: ${DOCS_REPO_CLONE}"
echo ""
echo "Next: update eval.yaml to use --docs-repo-path instead of --draft,"
echo "and add a setup step that checks out each case's docs repo SHA before running."

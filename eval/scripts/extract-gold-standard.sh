#!/bin/bash
# Extract gold standard AsciiDoc files from GitLab MRs
# Run from project root with: bash eval/scripts/extract-gold-standard.sh
# Requires: glab authenticated to gitlab.cee.redhat.com

set -euo pipefail

PROJECT_ID=82936
EVAL_DIR="eval/cases"

declare -A MR_MAP=(
  ["case-001-rhoaieng-45969"]=2664
  ["case-006-rhai-eng-2388"]=2697
  ["case-007-rhai-eng-4485"]=2691
  ["case-008-rhai-eng-2620"]=2380
  ["case-009-rhai-eng-1550"]=2104
  ["case-010-rhaieng-653"]=1938
  ["case-011-rhoaieng-16840"]=2680
  ["case-012-rhoaieng-40664"]=2574
)

declare -A JIRA_MAP=(
  ["case-001-rhoaieng-45969"]="RHOAIENG-45969"
  ["case-006-rhai-eng-2388"]="RHAIENG-2388"
  ["case-007-rhai-eng-4485"]="RHAIENG-4485"
  ["case-008-rhai-eng-2620"]="RHAIENG-2620"
  ["case-009-rhai-eng-1550"]="RHAIENG-1550"
  ["case-010-rhaieng-653"]="RHAIENG-653"
  ["case-011-rhoaieng-16840"]="RHOAIENG-16840"
  ["case-012-rhoaieng-40664"]="RHOAIENG-40664"
)

declare -A AUTHOR_MAP=(
  ["case-001-rhoaieng-45969"]="mmortari"
  ["case-006-rhai-eng-2388"]="chtyler"
  ["case-007-rhai-eng-4485"]="chtyler"
  ["case-008-rhai-eng-2620"]="chtyler"
  ["case-009-rhai-eng-1550"]="chtyler"
  ["case-010-rhaieng-653"]="chtyler"
  ["case-011-rhoaieng-16840"]="stmccart"
  ["case-012-rhoaieng-40664"]="stmccart"
)

for case_name in "${!MR_MAP[@]}"; do
  mr_iid="${MR_MAP[$case_name]}"
  jira="${JIRA_MAP[$case_name]}"
  author="${AUTHOR_MAP[$case_name]}"
  ref_dir="${EVAL_DIR}/${case_name}/reference"

  echo "=== ${case_name} (MR-${mr_iid}) ==="

  # Get MR changes
  tmp_file="/tmp/mr-${mr_iid}-changes.json"
  glab api --hostname gitlab.cee.redhat.com \
    "projects/${PROJECT_ID}/merge_requests/${mr_iid}/changes" \
    > "${tmp_file}" 2>/dev/null

  # Get target branch and merge commit SHA
  target_branch=$(python3 -c "import json; d=json.load(open('${tmp_file}')); print(d.get('target_branch','main'))")
  merge_sha=$(python3 -c "import json; d=json.load(open('${tmp_file}')); print(d.get('merge_commit_sha',''))")

  # Extract adoc file paths
  adoc_files=$(python3 -c "
import json
data = json.load(open('${tmp_file}'))
for c in data['changes']:
    if c['new_path'].endswith('.adoc'):
        print(c['new_path'])
")

  # Download each file at the merge commit
  for filepath in ${adoc_files}; do
    # Determine local path: preserve assemblies/modules structure
    filename=$(basename "${filepath}")
    mkdir -p "${ref_dir}"
    if echo "${filepath}" | grep -q "modules/"; then
      mkdir -p "${ref_dir}/modules"
      dest="${ref_dir}/modules/${filename}"
    else
      dest="${ref_dir}/${filename}"
    fi

    encoded_path=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${filepath}', safe=''))")
    glab api --hostname gitlab.cee.redhat.com \
      "projects/${PROJECT_ID}/repository/files/${encoded_path}/raw?ref=${merge_sha}" \
      > "${dest}" 2>/dev/null

    echo "  Downloaded: ${filename}"
  done

  # Write input.yaml if it doesn't exist
  input_file="${EVAL_DIR}/${case_name}/input.yaml"
  if [ ! -f "${input_file}" ]; then
    cat > "${input_file}" << YAML
ticket: ${jira}
source_repo:
  url: TBD
  sha: TBD
workflow: docs-workflow
options:
  format: adoc
  draft: true
ground_truth:
  tier: gold-standard
  source: "GitLab MR ${mr_iid}, authored by ${author}"
YAML
    echo "  Created: input.yaml (source_repo needs manual update)"
  fi

  adoc_count=$(find "${ref_dir}" -name "*.adoc" | wc -l | tr -d ' ')
  echo "  Total: ${adoc_count} adoc files"
  echo ""
done

echo "Done. Review the reference/ directories and update source_repo URLs in input.yaml files."

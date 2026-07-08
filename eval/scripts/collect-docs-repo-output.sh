#!/usr/bin/env bash
# Copies AsciiDoc files written to external docs repos into each case's
# .output/writing/ directory so collect.py can find them as a named output.
#
# Run AFTER execute.py, BEFORE collect.py.
#
# Usage: bash eval/scripts/collect-docs-repo-output.sh <workspace>
#
# For each case, reads writing/step-result.json to find the absolute paths
# of written AsciiDoc files, then copies them into .output/writing/ — a
# fixed path that collect.py picks up without {ticket} placeholder issues.

set -euo pipefail

WORKSPACE="${1:?Usage: $0 <workspace-path>}"

for case_dir in "$WORKSPACE"/cases/*/; do
    [ -d "$case_dir" ] || continue
    case_id=$(basename "$case_dir")

    # Find ticket ID from input.yaml
    ticket=$(python3 -c "import yaml,sys; print(yaml.safe_load(open(sys.argv[1])).get('ticket',''))" "$case_dir/input.yaml" 2>/dev/null)
    [ -z "$ticket" ] && continue

    # Find the writing step-result.json
    ticket_lower=$(echo "$ticket" | tr '[:upper:]' '[:lower:]')
    sr="$case_dir/.agent_workspace/$ticket_lower/writing/step-result.json"
    [ -f "$sr" ] || continue

    # Create the output directory that matches eval.yaml outputs path
    output_dir="$case_dir/.output/writing"
    mkdir -p "$output_dir"
    count=0

    while IFS= read -r filepath; do
        [ -f "$filepath" ] || continue
        if cp "$filepath" "$output_dir/$(basename "$filepath")" 2>/dev/null; then
            count=$((count + 1))
        fi
    done < <(python3 -c "
import json, sys
with open('$sr') as f:
    data = json.load(f)
for p in data.get('files', []):
    if p.endswith('.adoc'):
        print(p)
")

    echo "  $case_id: copied $count AsciiDoc files to .output/writing/"
done

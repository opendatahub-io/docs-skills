#!/usr/bin/env bash
#
# Convert MDITA files to DITA XML using the local DITA-OT installation.
#
# Usage:
#   mdita_convert.sh <input> [output_dir]
#
# Arguments:
#   input       Path to an .md, .mdita, or .mditamap file (not a directory)
#   output_dir  Output directory (default: ./dita-output)
#
# Output:
#   JSON on stdout with conversion results.

set -euo pipefail

usage() {
  echo '{"error": "Usage: mdita_convert.sh <input> [output_dir]"}' >&2
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

INPUT="$1"
OUTPUT_DIR="${2:-./dita-output}"

if [ ! -e "$INPUT" ]; then
  echo "{\"error\": \"Input not found: $INPUT\"}"
  exit 1
fi

if [ -d "$INPUT" ]; then
  echo "{\"error\": \"Input must be an .mdita, .md, or .mditamap file, not a directory. Use a .mditamap to convert multiple topics at once.\"}"
  exit 1
fi

if ! command -v java &>/dev/null; then
  echo '{"error": "Java 17+ not found. Install with: sudo dnf install -y java-17-openjdk-devel (Fedora/RHEL) or sudo apt install -y openjdk-17-jdk (Debian/Ubuntu) or brew install openjdk@17 (macOS)"}'
  exit 1
fi

if ! command -v dita &>/dev/null; then
  echo '{"error": "dita command not found. Install DITA-OT and ensure it is on your PATH."}'
  exit 1
fi

if ! dita plugins 2>/dev/null | grep -q "org.lwdita"; then
  echo '{"error": "org.lwdita plugin not found. Install it: dita install org.lwdita"}'
  exit 1
fi

DITA_VERSION=$(dita version 2>/dev/null || echo "unknown")

mkdir -p "$OUTPUT_DIR"

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

if dita -i "$INPUT" -f dita -o "$OUTPUT_DIR" --temp="$TEMP_DIR" 2>"$TEMP_DIR/stderr.log"; then
  FILE_COUNT=$(find "$OUTPUT_DIR" -name "*.dita" -o -name "*.ditamap" | wc -l)
  FILES=$(find "$OUTPUT_DIR" -name "*.dita" -o -name "*.ditamap" | sort | head -50)
  FILES_JSON=$(echo "$FILES" | jq -R -s 'split("\n") | map(select(length > 0))')
  cat <<EOF
{"status": "success", "dita_version": "$DITA_VERSION", "input": "$INPUT", "output_dir": "$OUTPUT_DIR", "file_count": $FILE_COUNT, "files": $FILES_JSON}
EOF
else
  STDERR=$(cat "$TEMP_DIR/stderr.log" 2>/dev/null || echo "")
  STDERR_ESCAPED=$(echo "$STDERR" | jq -R -s '.')
  cat <<EOF
{"status": "error", "dita_version": "$DITA_VERSION", "input": "$INPUT", "output_dir": "$OUTPUT_DIR", "stderr": $STDERR_ESCAPED}
EOF
  exit 1
fi

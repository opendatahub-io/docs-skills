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

emit_error() {
  if command -v jq &>/dev/null; then
    jq -n --arg msg "$1" '{error: $msg}'
  else
    printf '{"error": "jq not found. Install jq, then rerun."}\n'
  fi
}

if [ $# -lt 1 ]; then
  emit_error "Usage: mdita_convert.sh <input> [output_dir]" >&2
  exit 1
fi

INPUT="$1"
OUTPUT_DIR="${2:-./dita-output}"

if ! command -v jq &>/dev/null; then
  emit_error "jq not found. Install with: sudo dnf install -y jq (Fedora/RHEL) or sudo apt install -y jq (Debian/Ubuntu) or brew install jq (macOS)"
  exit 1
fi

if [ ! -e "$INPUT" ]; then
  emit_error "Input not found: $INPUT"
  exit 1
fi

if [ -d "$INPUT" ]; then
  emit_error "Input must be an .mdita, .md, or .mditamap file, not a directory. Use a .mditamap to convert multiple topics at once."
  exit 1
fi

if ! command -v java &>/dev/null; then
  emit_error "Java 17+ not found. Install with: sudo dnf install -y java-17-openjdk-devel (Fedora/RHEL) or sudo apt install -y openjdk-17-jdk (Debian/Ubuntu) or brew install openjdk@17 (macOS)"
  exit 1
fi

# Verify Java is 17+ when the version can be parsed; skip the gate if parsing fails.
JAVA_VERSION_OUT=$(java -version 2>&1 || true)
JAVA_VERSION_RAW=$(printf '%s\n' "$JAVA_VERSION_OUT" | sed -n '1s/.*version "\([0-9._]*\)".*/\1/p')
JAVA_MAJOR=""
case "$JAVA_VERSION_RAW" in
  1.*) JAVA_MAJOR=$(printf '%s' "$JAVA_VERSION_RAW" | cut -d. -f2) ;;
  [0-9]*) JAVA_MAJOR=$(printf '%s' "$JAVA_VERSION_RAW" | cut -d. -f1) ;;
esac
if [ -n "$JAVA_MAJOR" ] && [ "$JAVA_MAJOR" -lt 17 ]; then
  emit_error "Java 17+ required, found version $JAVA_VERSION_RAW. Install a newer JDK (for example java-17-openjdk-devel)."
  exit 1
fi

if ! command -v dita &>/dev/null; then
  emit_error "dita command not found. Install DITA-OT and ensure it is on your PATH."
  exit 1
fi

# Capture first, then match, so a short-circuiting grep never SIGPIPEs the upstream under pipefail.
PLUGINS=$(dita plugins 2>/dev/null || true)
if ! grep -q "org.lwdita" <<<"$PLUGINS"; then
  emit_error "org.lwdita plugin not found. Install it: dita install org.lwdita"
  exit 1
fi

DITA_VERSION=$(dita version 2>/dev/null || echo "unknown")

mkdir -p "$OUTPUT_DIR"

# Clear artifacts of the types this tool produces so reported counts reflect only this run.
find "$OUTPUT_DIR" \( -name "*.dita" -o -name "*.ditamap" \) -type f -delete

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

if dita -i "$INPUT" -f dita -o "$OUTPUT_DIR" --temp="$TEMP_DIR" 2>"$TEMP_DIR/stderr.log"; then
  FILES=$(find "$OUTPUT_DIR" \( -name "*.dita" -o -name "*.ditamap" \) -type f | sort)
  jq -n \
    --arg dita_version "$DITA_VERSION" \
    --arg input "$INPUT" \
    --arg output_dir "$OUTPUT_DIR" \
    --arg files "$FILES" \
    '($files | split("\n") | map(select(length > 0))) as $list
     | {status: "success", dita_version: $dita_version, input: $input, output_dir: $output_dir, file_count: ($list | length), files: ($list[0:50])}'
else
  STDERR=$(cat "$TEMP_DIR/stderr.log" 2>/dev/null || echo "")
  jq -n \
    --arg dita_version "$DITA_VERSION" \
    --arg input "$INPUT" \
    --arg output_dir "$OUTPUT_DIR" \
    --arg stderr "$STDERR" \
    '{status: "error", dita_version: $dita_version, input: $input, output_dir: $output_dir, stderr: $stderr}'
  exit 1
fi

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

LWDITA_VERSION="6.0.0"

emit_error() {
  if command -v jq &>/dev/null; then
    jq -n --arg msg "$1" '{status: "error", error: $msg}'
  else
    local escaped=${1//\\/\\\\}
    escaped=${escaped//\"/\\\"}
    printf '{"status": "error", "error": "%s"}\n' "$escaped"
  fi
}

if [ $# -lt 1 ]; then
  emit_error "Usage: mdita_convert.sh <input> [output_dir]"
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
JAVA_VERSION_RAW=$(printf '%s\n' "$JAVA_VERSION_OUT" | sed -n '1s/.*version "\([0-9][0-9._-]*\)".*/\1/p')
JAVA_MAJOR=""
case "$JAVA_VERSION_RAW" in
  1.*) JAVA_MAJOR=$(printf '%s' "$JAVA_VERSION_RAW" | cut -d. -f2) ;;
  [0-9]*) JAVA_MAJOR=$(printf '%s' "$JAVA_VERSION_RAW" | grep -oE '^[0-9]+') ;;
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
if ! grep -qx "org.lwdita@${LWDITA_VERSION}" <<<"$PLUGINS"; then
  emit_error "org.lwdita ${LWDITA_VERSION} not found. Install it: dita install https://github.com/aireilly/org.lwdita/releases/download/v${LWDITA_VERSION}/org.lwdita-${LWDITA_VERSION}.zip"
  exit 1
fi

DITA_VERSION=$(dita version 2>/dev/null || echo "unknown")

if ! mkdir -p "$OUTPUT_DIR"; then
  emit_error "Could not create output directory: $OUTPUT_DIR"
  exit 1
fi

TEMP_DIR=$(mktemp -d)
trap 'rm -rf "$TEMP_DIR"' EXIT

# Mark the run's start so pre-existing output files not rewritten by this
# conversion can be identified as stale after a successful run, without
# deleting anything before we know the run succeeded.
RUN_MARKER="$TEMP_DIR/run-start"
touch "$RUN_MARKER"

if dita -i "$INPUT" -f dita -o "$OUTPUT_DIR" --temp="$TEMP_DIR/dita-temp" >"$TEMP_DIR/stdout.log" 2>"$TEMP_DIR/stderr.log"; then
  # Prune output files this run did not touch, so file_count/files reflect
  # only this run's output rather than leftovers from a prior conversion.
  find "$OUTPUT_DIR" \( -name "*.dita" -o -name "*.ditamap" \) -type f ! -newer "$RUN_MARKER" -delete

  if ! FILES=$(find "$OUTPUT_DIR" \( -name "*.dita" -o -name "*.ditamap" \) -type f | sort); then
    emit_error "Could not list output files in: $OUTPUT_DIR"
    exit 1
  fi

  if [ -z "$FILES" ]; then
    STDERR=$(cat "$TEMP_DIR/stderr.log" 2>/dev/null || echo "")
    jq -n \
      --arg dita_version "$DITA_VERSION" \
      --arg input "$INPUT" \
      --arg output_dir "$OUTPUT_DIR" \
      --arg stderr "$STDERR" \
      '{status: "error", dita_version: $dita_version, input: $input, output_dir: $output_dir, stderr: ("dita reported success but produced no .dita or .ditamap files.\n" + $stderr)}'
    exit 1
  fi

  # The lwdita transform serializes whatever structure it built without
  # reparsing it against the topic's own DOCTYPE, so a positionally-invalid
  # taskbody (for example two <result> elements) can exit 0 here. Run each
  # output file back through `dita validate`, which does parse against the
  # DTD, so the caller finds out now instead of when AEM's editor opens it.
  DTD_ERRORS=""
  while IFS= read -r out_file; do
    [ -z "$out_file" ] && continue
    if ! VALIDATE_OUT=$(dita validate -i "$out_file" 2>&1); then
      DTD_ERRORS+="${out_file}:"$'\n'"${VALIDATE_OUT}"$'\n\n'
    fi
  done <<<"$FILES"

  if [ -n "$DTD_ERRORS" ]; then
    jq -n \
      --arg dita_version "$DITA_VERSION" \
      --arg input "$INPUT" \
      --arg output_dir "$OUTPUT_DIR" \
      --arg dtd_errors "$DTD_ERRORS" \
      '{status: "error", dita_version: $dita_version, input: $input, output_dir: $output_dir, error: ("Generated DITA is not valid against its DTD. Fix the Markdown source and reconvert:\n\n" + $dtd_errors)}'
    exit 1
  fi

  jq -n \
    --arg dita_version "$DITA_VERSION" \
    --arg input "$INPUT" \
    --arg output_dir "$OUTPUT_DIR" \
    --arg files "$FILES" \
    '($files | split("\n") | map(select(length > 0))) as $list
     | {status: "success", dita_version: $dita_version, input: $input, output_dir: $output_dir, file_count: ($list | length), files: $list}'
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

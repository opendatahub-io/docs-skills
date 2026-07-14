#!/bin/bash
# Checks that all environment variables and CLI tools required by
# docs-skills are available. Loads ~/.env and ./.env first.

set -euo pipefail

# --- Safe .env loader (matches jira-ready-check.sh pattern) ---
_safe_load_env() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    [[ "$line" =~ ^[[:space:]]*([a-zA-Z_][a-zA-Z0-9_]*)[[:space:]]*=(.*) ]] || continue
    local key="${BASH_REMATCH[1]}"
    local value="${BASH_REMATCH[2]}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "$value" =~ ^\"(.*)\"$ ]] || [[ "$value" =~ ^\'(.*)\'$ ]]; then
      value="${BASH_REMATCH[1]}"
    fi
    if [[ -z "${!key+x}" ]]; then
      export "$key=$value"
    fi
  done < "$file"
}

# --- Load .env files ---
env_sources=()
if [[ -f ".env" ]]; then
  _safe_load_env ".env"
  env_sources+=(".env")
fi
if [[ -f "$HOME/.env" ]]; then
  _safe_load_env "$HOME/.env"
  env_sources+=("$HOME/.env")
fi
# Backward-compat alias used by JIRA scripts
: "${JIRA_API_TOKEN:=${JIRA_AUTH_TOKEN:-}}"

# --- Check definitions ---
# Format: "NAME:required|optional"
ENV_CHECKS=(
  "JIRA_API_TOKEN:required"
  "JIRA_EMAIL:required"
  "GITHUB_TOKEN:optional"
  "GITLAB_TOKEN:optional"
)

CLI_CHECKS=(
  "python3:required"
  "uv:required"
  "git:required"
  "jq:required"
  "gh:required"
  "glab:required"
  "vale:optional"
  "shellcheck:optional"
  "ruff:optional"
)

# --- Output helpers ---
COL_WIDTH=22
PASS="OK"
FAIL="MISSING"

_dot_pad() {
  local label="$1"
  local remaining=$(( COL_WIDTH - ${#label} ))
  (( remaining < 2 )) && remaining=2
  printf '%s ' "$label"
  printf '.%.0s' $(seq 1 "$remaining")
  printf ' '
}

# --- Run checks ---
required_missing=()

echo "docs-skills prerequisite check"
echo "================================"
echo ""

# Env vars
if [[ ${#env_sources[@]} -gt 0 ]]; then
  echo "Environment variables (loaded ${env_sources[*]}):"
else
  echo "Environment variables (no .env files found):"
fi

for entry in "${ENV_CHECKS[@]}"; do
  name="${entry%%:*}"
  level="${entry##*:}"
  _dot_pad "  $name"
  if [[ -n "${!name:-}" ]]; then
    echo "$PASS"
  elif [[ "$level" == "optional" ]]; then
    echo "$FAIL (optional)"
  else
    echo "$FAIL"
    required_missing+=("$name")
  fi
done

echo ""
echo "CLI tools:"

for entry in "${CLI_CHECKS[@]}"; do
  name="${entry%%:*}"
  level="${entry##*:}"
  _dot_pad "  $name"
  if command -v "$name" &>/dev/null; then
    echo "$PASS"
  elif [[ "$level" == "optional" ]]; then
    echo "$FAIL (optional)"
  else
    echo "$FAIL"
    required_missing+=("$name")
  fi
done

echo ""

if [[ ${#required_missing[@]} -eq 0 ]]; then
  echo "Result: all required prerequisites satisfied"
  exit 0
else
  echo "Result: ${#required_missing[@]} required item(s) missing (${required_missing[*]})"
  exit 1
fi

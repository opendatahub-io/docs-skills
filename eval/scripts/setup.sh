#!/bin/bash
# One-time setup for eval harness prerequisites
# Run from project root: bash eval/scripts/setup.sh
#
# 1. Clones the docs repo (if not cached) and creates per-case worktrees
# 2. Extracts gold-standard AsciiDoc from merged GitLab MRs
#
# Requires: glab authenticated to gitlab.cee.redhat.com, VPN connected
# Re-run between eval runs to reset worktrees (they get modified during execution)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Step 1/2: Setting up docs repo worktrees ==="
bash "$SCRIPT_DIR/setup-eval-worktrees.sh"

echo ""
echo "=== Step 2/2: Extracting gold-standard reference files ==="
bash "$SCRIPT_DIR/extract-gold-standard.sh"

echo ""
echo "Setup complete. Run: /eval-run --model claude-opus-4-6"

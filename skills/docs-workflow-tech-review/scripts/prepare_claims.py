#!/usr/bin/env python3
"""Prepare claims for code-questioner validation in a single entry point.

Handles both iteration 1 (batch all claims) and iteration 2+ (carry forward
unchanged verdicts, batch only changed claims). Wraps incremental_claims.py
and split_claims.py so the SKILL.md needs only one script call instead of
conditional branching.

If --prior-validation points to a valid claim-validation.json, runs the
incremental path: cleans stale batch files, diffs claims, carries forward
unchanged verdicts, and batches only changed claims. Otherwise batches all.

Emits the same batch-summary JSON as split_claims.py on stdout.

Usage:
  prepare_claims.py --claims-list <path> --output-dir <dir> \
      [--prior-validation <path>]
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (json.JSONDecodeError, OSError):
        return None


def run_script(name, script_args):
    """Run a sibling script and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPTS_DIR, name), *script_args],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-list", required=True, help="Freshly extracted claims-list.json")
    parser.add_argument("--output-dir", required=True, help="Directory for batch files")
    parser.add_argument(
        "--prior-validation", default="",
        help="Prior claim-validation.json (triggers incremental path)",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    prior = args.prior_validation
    claims_to_split = args.claims_list

    # Iteration 2+: prior validation exists and is valid JSON
    if prior and os.path.isfile(prior) and load_json(prior) is not None:
        # Clean stale batch files from prior iteration
        for pattern in ("batch-claims-*.json", "batch-verdict-*.json"):
            for f in glob.glob(os.path.join(output_dir, pattern)):
                os.remove(f)

        # Run incremental diff: writes batch-verdict-carryover.json + claims-to-validate.json
        rc, stdout, stderr = run_script("incremental_claims.py", [
            "--claims-list", args.claims_list,
            "--prior-validation", prior,
            "--output-dir", output_dir,
        ])
        if rc != 0:
            print(stderr, file=sys.stderr, end="")
            print(f"ERROR: incremental_claims failed (exit {rc})", file=sys.stderr)
            return rc
        # Log incremental counts (JSON) to stderr for diagnostics
        if stdout.strip():
            print(stdout.strip(), file=sys.stderr)

        # Split only the changed claims
        claims_to_split = os.path.join(output_dir, "claims-to-validate.json")

        # If no claims to re-validate, emit empty batch summary
        remaining = load_json(claims_to_split)
        if isinstance(remaining, list) and len(remaining) == 0:
            json.dump({"total_claims": 0, "batch_count": 0, "batches": []}, sys.stdout)
            sys.stdout.write("\n")
            return 0

    # Run split_claims (iteration 1: all claims; iteration 2+: changed claims only)
    rc, stdout, stderr = run_script("split_claims.py", [
        "--claims-list", claims_to_split,
        "--output-dir", output_dir,
    ])
    if stderr:
        print(stderr, file=sys.stderr, end="")
    if rc != 0:
        return rc
    # Pass through split_claims stdout (the batch summary JSON)
    sys.stdout.write(stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())

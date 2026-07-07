#!/usr/bin/env python3
"""Prepare the tech-review step: parse args, resolve paths, build config.

Replaces the inline procedural logic that was formerly in SKILL.md steps 1-2.
Emits a JSON config on stdout that the SKILL.md dispatcher uses to drive the
claim-validation sub-pipeline and the reviewer agent dispatch.

Usage:
  prepare_review.py <ticket> --base-path <path> [--repo <path>]...
"""

import argparse
import json
import os
import sys
from pathlib import Path


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (json.JSONDecodeError, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticket", help="JIRA ticket ID")
    parser.add_argument("--base-path", required=True, help="Base output path")
    parser.add_argument("--repo", action="append", default=[], help="Source repo path (repeatable)")
    parser.add_argument(
        "--iteration", type=int, default=1, help="Review iteration number (1-based)"
    )
    args = parser.parse_args()

    base_path = os.path.abspath(args.base_path)
    output_dir = os.path.join(base_path, "technical-review")
    os.makedirs(output_dir, exist_ok=True)

    output_file = os.path.join(output_dir, "review.md")
    claims_file = os.path.join(output_dir, "claim-validation.json")
    code_analysis_dir = os.path.join(base_path, "code-analysis")

    # Resolve repo paths
    repo_paths = [os.path.abspath(r) for r in args.repo if os.path.isdir(r)]
    repo_path = repo_paths[0] if repo_paths else None
    additional_repo_paths = repo_paths[1:]

    # Discover additional code-analysis directories for secondary repos
    additional_code_analysis_dirs = []
    for rp in additional_repo_paths:
        repo_name = os.path.basename(rp)
        ca_dir = os.path.join(base_path, f"code-analysis-{repo_name}")
        if os.path.isfile(os.path.join(ca_dir, "ONBOARDING.md")):
            additional_code_analysis_dirs.append(ca_dir)

    has_code_analysis = os.path.isfile(os.path.join(code_analysis_dir, "ONBOARDING.md"))

    # Read writing sidecar to determine source files
    writing_sidecar = load_json(os.path.join(base_path, "writing", "step-result.json"))
    source_files_block = ""
    if (
        isinstance(writing_sidecar, dict)
        and writing_sidecar.get("mode") == "update-in-place"
        and writing_sidecar.get("files")
    ):
        file_lines = "\n".join(f"- `{f}`" for f in writing_sidecar["files"])
        source_files_block = f"Source files — review each of these:\n{file_lines}"
    else:
        drafts_dir = os.path.join(base_path, "writing")
        source_files_block = f"Source drafts location: `{drafts_dir}/`"

    has_prior_validation = os.path.isfile(claims_file)

    config = {
        "ticket": args.ticket,
        "base_path": base_path,
        "output_dir": output_dir,
        "output_file": output_file,
        "claims_file": claims_file,
        "code_analysis_dir": code_analysis_dir,
        "repo_path": repo_path,
        "additional_repo_paths": additional_repo_paths,
        "additional_code_analysis_dirs": additional_code_analysis_dirs,
        "has_repo": bool(repo_paths),
        "has_code_analysis": has_code_analysis,
        "source_files_block": source_files_block,
        "has_prior_validation": has_prior_validation,
        "iteration": args.iteration,
    }

    json.dump(config, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

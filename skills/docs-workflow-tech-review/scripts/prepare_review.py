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
import re
import sys
from pathlib import Path

# Mirror the canonical confidence/severity patterns in write_step_result.py so
# the prior-findings header stays consistent with the sidecar the orchestrator
# reads. These tolerate the reviewer's `**...:** [HIGH` markdown.
_CONFIDENCE_RE = re.compile(
    r"^\s*(?:\*\*)?Overall technical confidence:(?:\*\*)?\s*\[?\s*(HIGH|MEDIUM|LOW)",
    re.I | re.M,
)
_SEVERITY_RE = re.compile(
    r"^\s*(?:\*\*)?Severity counts:(?:\*\*)?\s*"
    r"critical=(\d+)\s+significant=(\d+)\s+minor=(\d+)\s+sme=(\d+)",
    re.I | re.M,
)

# Issue section headings emitted by the technical-reviewer agent, mapped to the
# short labels used in the prior-findings summary.
_FINDING_SECTIONS = [
    ("Critical issues", "Critical"),
    ("Significant issues", "Significant"),
    ("Minor issues", "Minor"),
    ("SME verification needed", "SME verification"),
]


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _extract_section(content, heading):
    """Return the body under a `### <heading>` up to the next heading (or end)."""
    pattern = re.compile(
        r"^#{2,4}\s*" + re.escape(heading) + r"\b.*?\n(.*?)(?=^#{2,4}\s|\Z)",
        re.S | re.M,
    )
    match = pattern.search(content)
    return match.group(1).strip() if match else ""


def extract_prior_findings(review_path, output_path, iteration):
    """Write a compact prior-findings summary distilled from a review.md.

    Captures the confidence, severity counts, and each per-severity issue
    section (dropping 'None identified.' sections) so the next iteration's
    reviewer can verify prior findings as FIXED or PERSISTS instead of
    re-discovering them from scratch.
    """
    content = Path(review_path).read_text(encoding="utf-8")

    lines = [f"# Prior findings (iteration {iteration})", ""]

    conf = _CONFIDENCE_RE.search(content)
    if conf:
        lines.append(f"Prior confidence: {conf.group(1).upper()}")
    sev = _SEVERITY_RE.search(content)
    if sev:
        c, s, mi, sme = sev.groups()
        lines.append(f"Prior severity: critical={c} significant={s} minor={mi} sme={sme}")
    lines.append("")

    any_findings = False
    for heading, label in _FINDING_SECTIONS:
        body = _extract_section(content, heading)
        if not body or body.lower().startswith("none identified"):
            continue
        any_findings = True
        lines.extend([f"## {label}", "", body, ""])

    if not any_findings:
        lines.append("No outstanding findings were recorded in the prior review.")

    Path(output_path).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


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

    # On re-review iterations, distil the prior review.md into a compact
    # prior-findings file the reviewer verifies against. prepare_review runs
    # before the reviewer deletes review.md, so the prior report is still here.
    prior_findings_file = None
    if args.iteration >= 2:
        prior_review = os.path.join(output_dir, "review.md")
        if os.path.isfile(prior_review):
            prior_findings_path = os.path.join(
                output_dir, f"prior-findings-iter-{args.iteration - 1}.md"
            )
            extract_prior_findings(prior_review, prior_findings_path, args.iteration - 1)
            prior_findings_file = prior_findings_path

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
        "prior_findings_file": prior_findings_file,
    }

    json.dump(config, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

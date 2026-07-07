#!/usr/bin/env python3
"""Write the technical-review step-result.json sidecar.

Greps only the confidence and severity-count lines from the reviewer's report
(the full report never enters the orchestrator's context), auto-detects the
iteration from any prior sidecar, and stamps a real wall-clock timestamp.

The iteration is the prior sidecar's iteration + 1 (or 1 on the first pass), so
the field stays correct across the orchestrator's review/fix loop without an
extra argument. Read the prior value before this run overwrites the sidecar.

Severity counts default to 0 when the line is absent. If the confidence line is
missing the script exits non-zero — the orchestrator treats a missing confidence
as a step failure.

Usage:
  write_step_result.py --ticket <id> --review-file <review.md> \
      --sidecar <step-result.json> --code-grounded <true|false>
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIDENCE_RE = re.compile(
    r"^\s*(?:\*\*)?Overall technical confidence:(?:\*\*)?\s*\[?\s*(HIGH|MEDIUM|LOW)",
    re.I | re.M,
)
SEVERITY_RE = re.compile(
    r"^\s*(?:\*\*)?Severity counts:(?:\*\*)?\s*"
    r"critical=(\d+)\s+significant=(\d+)\s+minor=(\d+)\s+sme=(\d+)",
    re.I | re.M,
)


def detect_iteration(sidecar_path: Path) -> int:
    """Prior sidecar's iteration + 1, or 1 when there is no prior sidecar."""
    if not sidecar_path.exists():
        return 1
    try:
        prior = json.loads(sidecar_path.read_text())
    except (json.JSONDecodeError, OSError):
        return 1
    prior_iter = prior.get("iteration", 0)
    if not isinstance(prior_iter, int) or prior_iter < 0:
        return 1
    return prior_iter + 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--review-file", required=True, help="The reviewer's review.md report")
    parser.add_argument("--sidecar", required=True, help="Path to write step-result.json")
    parser.add_argument(
        "--code-grounded",
        required=True,
        choices=["true", "false"],
        help="Whether the reviewer received claim-validation evidence",
    )
    parser.add_argument(
        "--missing-batches",
        default="",
        help="Comma-separated list of missing batch names (empty if none)",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        default=None,
        help="Iteration number (auto-detected from prior sidecar if not provided)",
    )
    args = parser.parse_args()

    review_path = Path(args.review_file)
    if not review_path.is_file():
        print(f"ERROR: review file not found: {review_path}", file=sys.stderr)
        return 1
    report = review_path.read_text()

    conf_match = CONFIDENCE_RE.search(report)
    if not conf_match:
        print(
            f"ERROR: no 'Overall technical confidence:' line in {review_path}",
            file=sys.stderr,
        )
        return 1
    confidence = conf_match.group(1).upper()

    sev_match = SEVERITY_RE.search(report)
    if sev_match:
        critical, significant, minor, sme = (int(g) for g in sev_match.groups())
    else:
        critical = significant = minor = sme = 0

    sidecar_path = Path(args.sidecar)
    iteration = args.iteration if args.iteration is not None else detect_iteration(sidecar_path)

    sidecar = {
        "schema_version": 1,
        "step": "technical-review",
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "confidence": confidence,
        "severity_counts": {
            "critical": critical,
            "significant": significant,
            "minor": minor,
            "sme": sme,
        },
        "missing_batches": [b for b in args.missing_batches.split(",") if b],
        "iteration": iteration,
        "code_grounded": args.code_grounded == "true",
    }
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    print(f"Written {sidecar_path}")
    print(f"Overall technical confidence: {confidence}")
    print(f"Severity counts: critical={critical} significant={significant} minor={minor} sme={sme}")
    print(f"iteration={iteration}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

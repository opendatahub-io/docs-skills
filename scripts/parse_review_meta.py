#!/usr/bin/env python3
"""Extract confidence and severity counts from a technical review report.

Scans for:
  - "Overall technical confidence: HIGH|MEDIUM|LOW"
  - "Severity counts: critical=N significant=N minor=N sme=N"

Usage:
    python3 parse_review_meta.py <review.md>

Outputs JSON: {"confidence": "HIGH", "severity_counts": {...},
  "iteration": 1, "code_grounded": false}
"""

import json
import re
import sys


def parse_review(path):
    confidence = None
    severity = {"critical": 0, "significant": 0, "minor": 0, "sme": 0}

    with open(path) as f:
        for line in f:
            m = re.search(
                r"(?:Overall\s+)?(?:technical\s+)?confidence[:\s]*\*?\*?\s*(HIGH|MEDIUM|LOW)",
                line,
                re.IGNORECASE,
            )
            if m:
                confidence = m.group(1).upper()

            m = re.search(
                r"critical[=:]\s*(\d+)[,;\s]+significant[=:]\s*(\d+)[,;\s]+minor[=:]\s*(\d+)[,;\s]+sme[=:]\s*(\d+)",
                line,
                re.IGNORECASE,
            )
            if m:
                severity = {
                    "critical": int(m.group(1)),
                    "significant": int(m.group(2)),
                    "minor": int(m.group(3)),
                    "sme": int(m.group(4)),
                }

    return confidence, severity


def main():
    if len(sys.argv) < 2:
        print("Usage: parse_review_meta.py <review.md>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    if len(sys.argv) > 2:
        try:
            iteration = int(sys.argv[2])
        except ValueError:
            print("iteration must be an integer", file=sys.stderr)
            sys.exit(1)
    else:
        iteration = 1
    code_grounded = sys.argv[3].lower() == "true" if len(sys.argv) > 3 else False

    try:
        confidence, severity = parse_review(path)
    except FileNotFoundError:
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    if not confidence:
        print("WARNING: No confidence line found in review", file=sys.stderr)

    result = {
        "confidence": confidence,
        "severity_counts": severity,
        "iteration": iteration,
        "code_grounded": code_grounded,
    }

    json.dump(result, sys.stdout)
    print()


if __name__ == "__main__":
    main()

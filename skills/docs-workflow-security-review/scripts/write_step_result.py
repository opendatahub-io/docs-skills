#!/usr/bin/env python3
"""Write the security-review step-result.json sidecar.

Derives every scanner-based field from the PII scanner's JSON output so the
sidecar cannot drift from the schema the way a hand-authored one does. The
agent-analysis finding count comes from the security-reviewer agent's printed
``Agent findings: N`` line (the full report never enters orchestrator context),
and ``context_size_bytes`` is summed from the step's output folder.

Usage:
  write_step_result.py --ticket <id> --scanner-results <scanner-results.json> \
      --agent-findings <N> --output-dir <security-review dir> \
      --sidecar <step-result.json>
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = ("ip", "email", "credential", "url", "mac", "internal_hostname")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--scanner-results", required=True, help="pii_scanner scan JSON output")
    parser.add_argument("--agent-findings", type=int, default=0)
    parser.add_argument("--output-dir", required=True, help="Step output dir, summed for byte size")
    parser.add_argument("--sidecar", required=True, help="Path to write step-result.json")
    args = parser.parse_args()

    scanner_path = Path(args.scanner_results)
    if not scanner_path.is_file():
        print(f"ERROR: scanner results not found: {scanner_path}", file=sys.stderr)
        return 1
    try:
        scan = json.loads(scanner_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR: cannot parse scanner results: {e}", file=sys.stderr)
        return 1

    summary = scan.get("summary", {})
    by_severity = summary.get("by_severity", {})
    by_category = summary.get("by_category", {})

    context_size_bytes = 0
    out_dir = Path(args.output_dir)
    if out_dir.is_dir():
        context_size_bytes = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())

    sidecar = {
        "schema_version": 1,
        "step": "security-review",
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "scanner_findings": int(summary.get("total_findings", 0)),
        "critical_findings": int(by_severity.get("critical", 0)),
        "agent_findings": args.agent_findings,
        "categories": {cat: int(by_category.get(cat, 0)) for cat in CATEGORIES},
        "context_size_bytes": context_size_bytes,
    }

    sidecar_path = Path(args.sidecar)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    print(f"Written {sidecar_path}")
    print(
        f"scanner_findings={sidecar['scanner_findings']} "
        f"critical_findings={sidecar['critical_findings']} "
        f"agent_findings={sidecar['agent_findings']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

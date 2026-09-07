#!/usr/bin/env python3
"""Write the scope-req-audit step-result.json sidecar.

Reads evidence-status.json to extract summary counts, so the orchestrator
does not need to parse the file itself.

Usage:
  write_step_result.py --ticket <id> --base-path <workflow-dir>
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument(
        "--base-path", required=True, help="Workflow workspace; audit files are derived"
    )
    args = parser.parse_args()

    output_dir = Path(args.base_path) / "scope-req-audit"
    es_path = output_dir / "evidence-status.json"
    sidecar_path = output_dir / "step-result.json"

    if not es_path.is_file():
        print(f"ERROR: evidence-status.json not found: {es_path}", file=sys.stderr)
        return 1

    try:
        evidence = json.loads(es_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR: cannot read evidence-status.json: {e}", file=sys.stderr)
        return 1

    summary = evidence.get("summary", {})
    discovered_repos = evidence.get("discovered_repos", [])
    secondary_repos = evidence.get("secondary_repos", [])

    sidecar = {
        "schema_version": 1,
        "step": "scope-req-audit",
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "recommendation": evidence.get("recommendation", "unknown"),
        "grounded": summary.get("grounded", 0),
        "partial": summary.get("partial", 0),
        "absent": summary.get("absent", 0),
        "total": summary.get("total", 0),
        "discovered_repos_count": len(discovered_repos),
        "secondary_repos_count": len(secondary_repos),
    }

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    print(f"Written {sidecar_path}")
    print(
        f"recommendation={sidecar['recommendation']} "
        f"grounded={sidecar['grounded']} partial={sidecar['partial']} "
        f"absent={sidecar['absent']} total={sidecar['total']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

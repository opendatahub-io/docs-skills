#!/usr/bin/env python3
"""Write the requirements step-result.json sidecar.

Stamps a real wall-clock ``completed_at`` so the sidecar timestamp matches
when the step actually finished, not when the orchestrator got around to
recording it.

Usage:
  write_step_result.py --ticket <id> --base-path <workflow-dir> \
      --requirement-count <N>
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def extract_title(path):
    """Extract title from the first level-1 markdown heading."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                heading = stripped.lstrip("#").strip()
                heading = re.sub(r"^\[?[A-Z][A-Z0-9]+-\d+\]?\s*[:\-]?\s*", "", heading)
                return heading[:80] if heading else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument(
        "--base-path", required=True, help="Workflow workspace; requirements files are derived"
    )
    parser.add_argument("--requirement-count", type=int, required=True)
    args = parser.parse_args()

    output_dir = Path(args.base_path) / "requirements"
    output_file = output_dir / "requirements.md"
    sidecar_path = output_dir / "step-result.json"

    title = extract_title(str(output_file)) or "Requirements Analysis"

    sidecar = {
        "schema_version": 1,
        "step": "requirements",
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "requirement_count": args.requirement_count,
    }

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    print(f"Written {sidecar_path}")
    print(f"title={sidecar['title']!r} requirement_count={sidecar['requirement_count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

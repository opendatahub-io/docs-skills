#!/usr/bin/env python3
"""Write the style-review step-result.json sidecar.

Stamps a real wall-clock ``completed_at`` so the sidecar timestamp matches
when the step actually finished, not when the orchestrator got around to
recording it.

Usage:
  write_step_result.py --ticket <id> --fixes <N> --warnings <N> \
      --suggestions <N> --sidecar <step-result.json>
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--fixes", type=int, default=0, help="Number of fixes applied")
    parser.add_argument("--warnings", type=int, default=0, help="Number of warnings")
    parser.add_argument("--suggestions", type=int, default=0, help="Number of suggestions")
    parser.add_argument("--sidecar", required=True, help="Path to write step-result.json")
    args = parser.parse_args()

    sidecar = {
        "schema_version": 1,
        "step": "style-review",
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "fixes_applied": args.fixes,
        "warnings": args.warnings,
        "suggestions": args.suggestions,
    }

    sidecar_path = Path(args.sidecar)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    print(f"Written {sidecar_path}")
    print(
        f"fixes_applied={sidecar['fixes_applied']} "
        f"warnings={sidecar['warnings']} "
        f"suggestions={sidecar['suggestions']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

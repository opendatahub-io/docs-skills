#!/usr/bin/env python3
"""Write the planning step-result.json sidecar.

Counts module specifications in plan.md and stamps a real wall-clock
``completed_at``.

Usage:
  write_step_result.py --ticket <id> --plan-file <plan.md> --sidecar <path>
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def count_modules(path):
    """Count module specifications in the plan markdown.

    Counts:
    - Level-3 headings (###) whose text begins with 'Module:' or 'Update:'
    - Numbered or bulleted list items within the 'Module Specifications'
      section that start with 'Module:' or 'Update:'

    'Update' headings appear in in-place-update plans, where each entry
    describes an edit to an existing doc rather than a new module.

    Skips items inside code blocks or blockquotes.
    """
    count = 0
    in_module_specs_section = False
    in_code_block = False

    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()

            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            if stripped.startswith(">"):
                continue

            if re.match(r"^##\s", stripped) and not re.match(r"^###", stripped):
                in_module_specs_section = bool(
                    re.search(r"module\s+specifications?", stripped, re.IGNORECASE)
                )
                continue

            if re.match(r"^###\s+(?:Module|Update)[\s:\d]", stripped):
                count += 1
                continue

            if in_module_specs_section and re.match(
                r"^[\d]+[\.\)]\s+(?:Module|Update)[\s:\d]|^[-*]\s+(?:Module|Update)[\s:\d]",
                stripped,
            ):
                count += 1

    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--plan-file", required=True, help="Path to plan.md")
    parser.add_argument("--sidecar", required=True, help="Path to write step-result.json")
    args = parser.parse_args()

    plan_path = Path(args.plan_file)
    if not plan_path.is_file():
        print(f"ERROR: plan file not found: {plan_path}", file=sys.stderr)
        return 1

    module_count = count_modules(args.plan_file)

    sidecar = {
        "schema_version": 1,
        "step": "planning",
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "module_count": module_count,
    }

    sidecar_path = Path(args.sidecar)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    print(f"Written {sidecar_path}")
    print(f"module_count={module_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

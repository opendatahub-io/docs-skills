#!/usr/bin/env python3
"""Write the writing step-result.json sidecar.

Parses the _index.md manifest to extract file paths, stamps a real wall-clock
``completed_at``.

Usage:
  write_step_result.py --ticket <id> --manifest <_index.md> \
      --mode <mode> --format <fmt> --sidecar <path>
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def extract_files(manifest_path):
    """Extract absolute file paths from the manifest's markdown table rows."""
    files = []
    with open(manifest_path, encoding="utf-8") as f:
        for line in f:
            matches = re.findall(r"(/\S+\.(?:adoc|md|dita|ditamap))", line)
            files.extend(matches)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--manifest", required=True, help="Path to _index.md")
    parser.add_argument("--mode", required=True, help="Writing mode (update-in-place, draft)")
    parser.add_argument("--format", required=True, dest="fmt", help="Doc format (adoc, mkdocs)")
    parser.add_argument("--sidecar", required=True, help="Path to write step-result.json")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    files = extract_files(args.manifest)
    if not files:
        print(f"WARNING: no file paths found in manifest: {manifest_path}", file=sys.stderr)

    sidecar = {
        "schema_version": 1,
        "step": "writing",
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "mode": args.mode,
        "format": args.fmt,
    }

    sidecar_path = Path(args.sidecar)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    print(f"Written {sidecar_path}")
    print(f"files={len(files)} mode={args.mode} format={args.fmt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

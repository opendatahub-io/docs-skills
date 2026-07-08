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
    """Extract file paths from the manifest's markdown table rows.

    Only paths that resolve to a real file on disk are kept. The extraction
    regex matches from any interior ``/``, so a relative path like
    ``deploying-llmd/master.adoc`` would otherwise yield a bogus
    ``/master.adoc``. Validating existence drops those phantom entries before
    they reach the sidecar (and downstream tech-review / quality-gate).
    """
    files = []
    dropped = []
    with open(manifest_path, encoding="utf-8") as f:
        for line in f:
            matches = re.findall(r"(/\S+\.(?:adoc|md|dita|ditamap))", line)
            for m in matches:
                if Path(m).is_file():
                    files.append(m)
                else:
                    dropped.append(m)
    for m in dropped:
        print(f"WARNING: dropping non-existent manifest path: {m}", file=sys.stderr)
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

    sidecar_path = Path(args.sidecar)

    # "fix" is not a valid value for the sidecar's ``mode`` enum
    # (["update-in-place", "draft"]). A fix iteration re-runs the finalize to
    # refresh ``completed_at`` and re-validate ``files``, but must carry the
    # original mode/format forward from the iteration-1 sidecar.
    mode = args.mode
    fmt = args.fmt
    if mode == "fix":
        if sidecar_path.is_file():
            prior = json.loads(sidecar_path.read_text())
            mode = prior.get("mode", "update-in-place")
            fmt = prior.get("format", fmt)
        else:
            print(
                f"WARNING: fix mode with no prior sidecar at {sidecar_path}; "
                "falling back to mode=update-in-place",
                file=sys.stderr,
            )
            mode = "update-in-place"

    sidecar = {
        "schema_version": 1,
        "step": "writing",
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "files": files,
        "mode": mode,
        "format": fmt,
    }

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    print(f"Written {sidecar_path}")
    print(f"files={len(files)} mode={mode} format={fmt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

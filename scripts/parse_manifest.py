#!/usr/bin/env python3
"""Extract file paths from a writing manifest (_index.md).

Parses markdown tables structurally, extracting paths from the first content
column only (the Path column). Falls back to regex for non-table lines.

Usage:
    python3 parse_manifest.py <_index.md> [--mode <mode>] [--format <format>]

Outputs JSON: {"files": [...], "mode": "...", "format": "..."}
"""

import json
import re
import sys

_PATH_RE = re.compile(r"(/[^\s|`\]]+)")


def _is_table_separator(line):
    """Check if a line is a markdown table separator (e.g., |---|---|---|)."""
    return bool(re.match(r"^\s*\|[\s\-:|]+\|\s*$", line))


def parse_manifest(path):
    files = []
    seen = set()

    with open(path) as f:
        for line in f:
            stripped = line.strip()

            if "|" in stripped and not _is_table_separator(stripped):
                cols = stripped.split("|")
                # First content column is index 1 (index 0 is empty before first |)
                if len(cols) >= 2:
                    path_col = cols[1].strip()
                    for m in _PATH_RE.finditer(path_col):
                        fpath = m.group(1).rstrip(",;)")
                        if fpath not in seen and not fpath.startswith("//"):
                            seen.add(fpath)
                            files.append(fpath)
            else:
                for m in _PATH_RE.finditer(line):
                    fpath = m.group(1).rstrip(",;)")
                    if fpath not in seen and not fpath.startswith("//"):
                        seen.add(fpath)
                        files.append(fpath)

    return files


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Parse writing manifest")
    parser.add_argument("manifest", help="Path to _index.md")
    parser.add_argument("--mode", default="draft", help="Writing mode")
    parser.add_argument("--format", default="adoc", dest="fmt", help="Doc format")

    args = parser.parse_args()

    try:
        files = parse_manifest(args.manifest)
    except FileNotFoundError:
        print(f"File not found: {args.manifest}", file=sys.stderr)
        sys.exit(1)

    result = {
        "files": files,
        "mode": args.mode,
        "format": args.fmt,
    }

    json.dump(result, sys.stdout)
    print()


if __name__ == "__main__":
    main()

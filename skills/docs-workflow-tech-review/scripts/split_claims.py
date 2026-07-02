#!/usr/bin/env python3
"""Split an extracted claims list into per-doc-file batch files.

Reads claims-list.json (a flat array of claim objects) and writes one batch
file per source doc file. Each batch file holds the full claim objects for
that doc, so the code-questioner agents can read their claims from disk
instead of receiving claim text inline in their dispatch prompt.

When a single doc file produces more claims than ``--max-batch-size``, the
claims are split into numbered sub-batches (``-part1``, ``-part2``, …).

This keeps claim text out of the orchestrator's context: stdout carries only
counts and sanitized batch identifiers, never claim text.

Usage:
  split_claims.py --claims-list <path> --output-dir <dir> [--max-batch-size N]

Emits a JSON object on stdout:
  {
    "total_claims": N,
    "batch_count": M,
    "batches": [
      {"sanitized": "proc-foo", "file": "proc-foo.adoc",
       "count": 3, "claims_file": "<output-dir>/batch-claims-proc-foo.json"}
    ]
  }
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

DEFAULT_MAX_BATCH_SIZE = 15


def sanitize(filename: str) -> str:
    """Strip .adoc/.md and replace non-alphanumerics with hyphens.

    Mirrors the sanitization convention documented in SKILL.md step 3b
    (e.g. ``pre-loaded-mcp-servers.adoc`` -> ``pre-loaded-mcp-servers``).
    """
    stem = re.sub(r"\.(adoc|md)$", "", filename)
    return re.sub(r"[^A-Za-z0-9]+", "-", stem).strip("-")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-list", required=True, help="Path to claims-list.json")
    parser.add_argument("--output-dir", required=True, help="Directory to write batch files")
    parser.add_argument(
        "--max-batch-size",
        type=int,
        default=DEFAULT_MAX_BATCH_SIZE,
        help=f"Max claims per batch file (default: {DEFAULT_MAX_BATCH_SIZE}). "
        "Files with more claims are split into numbered sub-batches.",
    )
    args = parser.parse_args()

    claims_path = Path(args.claims_list)
    if not claims_path.is_file():
        print(f"ERROR: claims list not found: {claims_path}", file=sys.stderr)
        return 1

    try:
        claims = json.loads(claims_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: cannot read claims list: {exc}", file=sys.stderr)
        return 1

    if not isinstance(claims, list):
        print("ERROR: claims list must be a JSON array.", file=sys.stderr)
        return 1

    max_size = args.max_batch_size
    if max_size < 1:
        print("ERROR: --max-batch-size must be >= 1.", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    by_file: dict[str, list] = {}
    for claim in claims:
        doc = claim.get("file", "unknown")
        by_file.setdefault(doc, []).append(claim)

    batches = []
    seen_sanitized: dict[str, str] = {}
    for doc, doc_claims in sorted(by_file.items()):
        sanitized = sanitize(doc) or "unknown"
        previous = seen_sanitized.get(sanitized)
        if previous is not None and previous != doc:
            print(
                f"ERROR: batch id collision: {previous!r} and {doc!r} both map to {sanitized!r}",
                file=sys.stderr,
            )
            return 1
        seen_sanitized[sanitized] = doc

        if len(doc_claims) <= max_size:
            claims_file = output_dir / f"batch-claims-{sanitized}.json"
            claims_file.write_text(json.dumps(doc_claims, indent=2))
            batches.append(
                {
                    "sanitized": sanitized,
                    "file": doc,
                    "count": len(doc_claims),
                    "claims_file": str(claims_file),
                }
            )
        else:
            num_parts = math.ceil(len(doc_claims) / max_size)
            for part_idx in range(num_parts):
                start = part_idx * max_size
                chunk = doc_claims[start : start + max_size]
                part_label = f"{sanitized}-part{part_idx + 1}"
                claims_file = output_dir / f"batch-claims-{part_label}.json"
                claims_file.write_text(json.dumps(chunk, indent=2))
                batches.append(
                    {
                        "sanitized": part_label,
                        "file": doc,
                        "count": len(chunk),
                        "claims_file": str(claims_file),
                    }
                )

    json.dump(
        {"total_claims": len(claims), "batch_count": len(batches), "batches": batches},
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

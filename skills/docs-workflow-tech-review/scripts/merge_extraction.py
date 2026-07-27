#!/usr/bin/env python3
"""Assemble claims-list.json from carried and freshly extracted claims.

Second half of the incremental extraction gate. plan_extraction.py decides
which files the extractor reads and writes the prior claims for everything it
skipped; this script joins those carried claims to the fresh ones and refreshes
the manifest.

Two rules carry the correctness weight:

**Fresh ids are reassigned, never trusted.** SKILL.md asks the extractor for an
`id` field but specifies no scheme, so the agent invents one — `claim-1`,
`C001` and `B001` have all been observed from the identical prompt. A fresh id
that collides with a carried one is not an error anywhere downstream:
merge_verdicts.py does ``verdict_map[claim_id] = entry``, so the later entry
silently overwrites the earlier and a verdict lands on the wrong claim.

**Only files that actually produced claims are manifested.** Extraction drops a
file's claims from time to time (measured: one file in 25 across two runs of the
same input). Recording such a file with an empty claim list would cache it as
permanently claim-free until its bytes change again.

Usage:
  merge_extraction.py --base-path <path> --output-dir <dir> \
      [--repo <path>]...
"""

import argparse
import json
import re
import sys
from pathlib import Path

from plan_extraction import (
    CARRIED_NAME,
    CLAIMS_LIST_NAME,
    FRESH_NAME,
    MANIFEST_NAME,
    MANIFEST_VERSION,
    PLAN_NAME,
    claim_file_index,
    code_state,
    file_hash,
    load_json,
    read_manifest,
)
from prepare_review import resolve_source_files

# Trailing integer of an id in any format: claim-1, C001, B001, 17.
_TRAILING_INT = re.compile(r"(\d+)\s*$")


def id_number(claim_id):
    """Extract the numeric part of an id, or 0 when there isn't one."""
    match = _TRAILING_INT.search(str(claim_id or ""))
    return int(match.group(1)) if match else 0


def renumber(fresh_claims, start):
    """Return fresh claims with deterministic ids assigned from ``start``.

    Agent-supplied ids are discarded outright rather than de-duplicated: they
    carry no meaning, and any scheme that preserves them has to reason about
    collisions with the carried set.
    """
    out = []
    for offset, claim in enumerate(fresh_claims):
        if not isinstance(claim, dict):
            continue
        renamed = dict(claim)
        renamed["id"] = f"C{start + offset:03d}"
        out.append(renamed)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-path", required=True, help="Workflow base path for the ticket")
    parser.add_argument("--output-dir", required=True, help="Tech-review output directory")
    parser.add_argument("--repo", action="append", default=[], help="Source repo path (repeatable)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_dir():
        print(f"ERROR: output dir not found: {output_dir}", file=sys.stderr)
        return 1

    # A missing or unreadable fresh file is fatal. Merging only the carried
    # claims would look like success while deleting every changed file's
    # claims — the failure mode this whole feature exists to prevent.
    fresh = load_json(output_dir / FRESH_NAME)
    if not isinstance(fresh, list):
        print(
            f"ERROR: cannot read extractor output: {output_dir / FRESH_NAME}\n"
            "Refusing to write a claims list that would drop every changed file's claims.",
            file=sys.stderr,
        )
        return 1

    carried = load_json(output_dir / CARRIED_NAME)
    if not isinstance(carried, list):
        carried = []

    next_id = max((id_number(c.get("id")) for c in carried if isinstance(c, dict)), default=0) + 1
    renumbered = renumber(fresh, next_id)

    claims = carried + renumbered
    (output_dir / CLAIMS_LIST_NAME).write_text(json.dumps(claims, indent=2))

    source_files = resolve_source_files(args.base_path)
    index = claim_file_index(source_files)
    prior_files, _, _ = read_manifest(output_dir)
    prior_files = prior_files if isinstance(prior_files, dict) else {}

    plan = load_json(output_dir / PLAN_NAME)
    unchanged = set((plan or {}).get("unchanged_files") or [])

    by_file = {}
    for claim in renumbered:
        path = index.get(claim.get("file"))
        if path:
            by_file.setdefault(path, []).append(claim["id"])

    # Three cases, kept explicit because the wrong one is silent:
    #   re-extracted and produced claims -> fresh hash + fresh ids
    #   carried (never re-read)          -> keep the prior entry verbatim
    #   re-extracted and produced none   -> no entry, so it is re-extracted
    #                                       next iteration rather than cached
    #                                       as permanently claim-free
    files = {}
    for path in source_files:
        ids = by_file.get(path)
        if ids:
            digest = file_hash(path)
            if digest:
                files[path] = {"hash": digest, "claim_ids": ids}
        elif path in unchanged and path in prior_files:
            files[path] = prior_files[path]

    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "schema_version": MANIFEST_VERSION,
                "code_state": code_state(args.repo),
                "files": files,
            },
            indent=2,
        )
    )

    json.dump(
        {
            "total_claims": len(claims),
            "carried": len(carried),
            "fresh": len(renumbered),
            "files_manifested": len(files),
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

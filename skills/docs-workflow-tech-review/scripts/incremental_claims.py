#!/usr/bin/env python3
"""Compute the incremental claim-validation work for a tech-review re-run.

On iteration 2+ of the technical-review loop the source code is unchanged but
the documentation has been edited by a fix pass, so most extracted claims are
textually identical to the previous iteration and keep their verdicts. This
script diffs the freshly extracted claims against the prior
``claim-validation.json`` and splits the work:

  - claims whose (file, normalized-text) matches a prior claim carry that
    claim's verdict forward (written to ``batch-verdict-carryover.json`` with
    the NEW claim ids), so no code-questioner agent re-runs for them;
  - claims with no prior match are written to ``claims-to-validate.json`` for
    the caller to batch (via split_claims.py) and validate.

This keeps re-validation proportional to what actually changed and gives the
reviewer fresh (not stale) evidence for the claims the fix touched. A missing
or unreadable prior validation file means revalidate everything (safe default).

stdout carries only counts — never claim text — so claim details stay out of
the orchestrator's context.

Usage:
  incremental_claims.py --claims-list <path> --prior-validation <path> \
      --output-dir <dir>
"""

import argparse
import json
import sys
from pathlib import Path


def normalize(text):
    """Collapse whitespace so trivial reformatting still matches a prior claim."""
    return " ".join((text or "").split())


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (json.JSONDecodeError, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-list", required=True, help="Freshly extracted claims-list.json")
    parser.add_argument("--prior-validation", required=True, help="Prior claim-validation.json")
    parser.add_argument("--output-dir", required=True, help="Directory to write batch files")
    args = parser.parse_args()

    claims = load_json(args.claims_list)
    if not isinstance(claims, list):
        print(f"ERROR: cannot read claims list: {args.claims_list}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build a (file, normalized-text) -> {verdict, evidence} map from the prior
    # validation. Keying on file as well as text avoids cross-attributing an
    # identical sentence that appears in two different documents.
    prior = load_json(args.prior_validation)
    prior_map = {}
    if isinstance(prior, dict):
        for claim in prior.get("claims", []):
            if not isinstance(claim, dict):
                continue
            key = (claim.get("file", ""), normalize(claim.get("text", "")))
            prior_map[key] = {
                "verdict": claim.get("verdict", "no_evidence_found"),
                "evidence": claim.get("evidence", ""),
            }

    carryover = []
    to_validate = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        key = (claim.get("file", ""), normalize(claim.get("text", "")))
        match = prior_map.get(key)
        if match is not None:
            carryover.append(
                {
                    "claim_id": claim.get("id"),
                    "claim_text": claim.get("text", ""),
                    "verdict": match["verdict"],
                    "evidence": match["evidence"],
                }
            )
        else:
            to_validate.append(claim)

    # Carryover verdicts are written as a batch-verdict file so merge_verdicts.py
    # picks them up via its existing glob, keyed by the NEW claim ids.
    (output_dir / "batch-verdict-carryover.json").write_text(json.dumps(carryover, indent=2))
    (output_dir / "claims-to-validate.json").write_text(json.dumps(to_validate, indent=2))

    json.dump(
        {
            "total_claims": len(claims),
            "reused_count": len(carryover),
            "revalidate_count": len(to_validate),
        },
        sys.stdout,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

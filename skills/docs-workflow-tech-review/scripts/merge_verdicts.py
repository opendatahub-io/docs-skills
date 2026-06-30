#!/usr/bin/env python3
"""Assemble claim-validation.json and validation-summary.md from batch verdicts.

Deterministic merge step for the docs-workflow-tech-review claim-validation
sub-pipeline. Replaces the former merge subagent: there is no judgment here,
only JSON assembly and cross-referencing, so it belongs in a script (keeps an
agent turn and its prompt out of the orchestrator's context).

Reads:
  - claims-list.json            full claims list (id, text, file, line)
  - batch-verdict-*.json        per-batch verdict arrays written by code-questioner agents
  - <code-analysis-dir>/registry.json   optional module coverage context

Writes:
  - claim-validation.json       merged claims with verdicts + summary counts
  - validation-summary.md       human-readable summary for the reviewer agent

Any claim with no matching verdict gets a fallback verdict of
``no_evidence_found`` so the output always covers every claim.

Usage:
  merge_verdicts.py --claims-list <path> --output-dir <dir> \
      --claims-file <path> --summary-file <path> [--code-analysis-dir <dir>]
"""

import argparse
import json
import sys
from pathlib import Path

VERDICTS = ("supported", "partially_supported", "unsupported", "no_evidence_found")


def load_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-list", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--claims-file", required=True)
    parser.add_argument("--summary-file", required=True)
    parser.add_argument("--code-analysis-dir", default="")
    args = parser.parse_args()

    claims_list = load_json(Path(args.claims_list))
    if not isinstance(claims_list, list):
        print(f"ERROR: cannot read claims list: {args.claims_list}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)

    # Collect verdicts from every batch file, keyed by claim_id.
    verdict_map: dict[str, dict] = {}
    for batch_file in sorted(output_dir.glob("batch-verdict-*.json")):
        data = load_json(batch_file)
        if not isinstance(data, list):
            continue
        for entry in data:
            if not isinstance(entry, dict):
                continue
            claim_id = entry.get("claim_id")
            if claim_id:
                verdict_map[claim_id] = entry

    # Cross-reference against the full claims list; fall back where missing.
    merged = []
    counts = dict.fromkeys(VERDICTS, 0)
    for claim in claims_list:
        claim_id = claim.get("id")
        entry = verdict_map.get(claim_id)
        if entry:
            verdict = entry.get("verdict", "no_evidence_found")
            evidence = entry.get("evidence", "")
        else:
            verdict = "no_evidence_found"
            evidence = "Agent did not return a verdict for this claim"
        if verdict not in counts:
            verdict = "no_evidence_found"
        counts[verdict] += 1
        merged.append(
            {
                "id": claim_id,
                "text": claim.get("text", ""),
                "verdict": verdict,
                "evidence": evidence,
                "file": claim.get("file", ""),
                "line": claim.get("line"),
            }
        )

    Path(args.claims_file).write_text(json.dumps({"claims": merged, "summary": counts}, indent=2))

    # Module coverage context from registry.json, if available.
    coverage_line = ""
    if args.code_analysis_dir:
        registry = load_json(Path(args.code_analysis_dir) / "registry.json")
        if isinstance(registry, dict):
            modules = registry.get("modules", registry)
            if isinstance(modules, (list, dict)):
                coverage_line = f"Modules analyzed: {len(modules)}"

    flagged = [c for c in merged if c["verdict"] in ("unsupported", "partially_supported")]
    lines = [
        "# Claim Validation Summary",
        "",
        f"Total claims: {len(merged)}",
        f"- supported: {counts['supported']}",
        f"- partially_supported: {counts['partially_supported']}",
        f"- unsupported: {counts['unsupported']}",
        f"- no_evidence_found: {counts['no_evidence_found']}",
        "",
    ]
    if coverage_line:
        lines += [coverage_line, ""]
    lines.append("## Unsupported and partially supported claims")
    lines.append("")
    if flagged:
        for c in flagged:
            loc = f"{c['file']}:{c['line']}" if c.get("line") is not None else c["file"]
            lines.append(f"- **[{c['verdict']}]** ({loc}) {c['text']}")
            if c["evidence"]:
                lines.append(f"  - Evidence: {c['evidence']}")
    else:
        lines.append("None.")
    lines.append("")
    Path(args.summary_file).write_text("\n".join(lines))

    print(f"Written {args.claims_file}")
    print(f"Written {args.summary_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

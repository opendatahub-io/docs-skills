#!/usr/bin/env python3
"""Decide the next action in the orchestrator's review/gate iteration loops.

Pure decision logic extracted from docs-orchestrator/SKILL.md so the rules are
testable and cannot drift under context compaction. Reads a step-result sidecar
and emits a decision as JSON; the orchestrator performs the dispatch,
AskUserQuestion, and file writes — this script only decides.

Usage:
  iteration_decision.py tech-review   --sidecar <step-result.json> [--max-iter 2]
  iteration_decision.py quality-gate  --sidecar <step-result.json> [--max-iter 2]
"""

import argparse
import json
import sys
from pathlib import Path


def decide_tech_review(
    confidence: str,
    critical: int,
    significant: int,
    iteration: int,
    max_iter: int = 2,
) -> dict:
    """Technical-review loop decision (SKILL.md 'Technical review iteration')."""
    conf = (confidence or "").upper()

    if conf == "HIGH" or (conf == "MEDIUM" and critical == 0 and significant == 0):
        return {
            "decision": "done",
            "reason": f"{conf} confidence with no blocking issues — accept and proceed",
            "warning": None,
            "list_findings": False,
        }

    if iteration < max_iter:
        return {
            "decision": "fix",
            "reason": (
                f"{conf} confidence with unresolved issues at iteration {iteration} "
                f"(< {max_iter}) — run one fix-and-confirm pass"
            ),
            "warning": None,
            "list_findings": False,
        }

    if conf == "MEDIUM":
        warning = (
            f"Technical review proceeding at MEDIUM confidence with {critical} critical "
            f"+ {significant} significant issue(s) unresolved after {iteration} iterations. "
            "These were not fixed and need SME/human review:"
        )
        return {
            "decision": "proceed_with_warning",
            "reason": "MEDIUM confidence persists after max iterations — proceed but flag",
            "warning": warning,
            "list_findings": True,
        }

    return {
        "decision": "ask_user",
        "reason": (
            f"LOW confidence after {iteration} iterations — escalate to the user for "
            "SME/human review rather than another automated rewrite"
        ),
        "warning": None,
        "list_findings": False,
    }


def decide_quality_gate(
    intent_alignment: int,
    doc_quality: int,
    iteration: int,
    max_iter: int = 2,
) -> dict:
    """Quality-gate loop decision (SKILL.md 'Quality gate iteration')."""
    secondary_warning = None
    if isinstance(doc_quality, int) and doc_quality < 4:
        secondary_warning = (
            f"doc_quality={doc_quality}/5 is below 4 — manual review recommended "
            "(informational; does not trigger a fix pass)"
        )

    if intent_alignment >= 4:
        decision, reason = "done", f"intent_alignment={intent_alignment}/5 meets the threshold"
    elif iteration < max_iter:
        decision, reason = (
            "fix",
            (
                f"intent_alignment={intent_alignment}/5 below threshold at iteration {iteration} "
                f"(< {max_iter}) — run a fix pass from the feedback brief"
            ),
        )
    elif intent_alignment >= 3:
        decision, reason = (
            "accept_with_warning",
            (
                f"intent_alignment={intent_alignment}/5 after {iteration} iterations "
                "— accept with warning"
            ),
        )
    else:
        decision, reason = (
            "ask_user",
            (
                f"intent_alignment={intent_alignment}/5 after {iteration} iterations "
                "— escalate to the user"
            ),
        )

    return {"decision": decision, "reason": reason, "secondary_warning": secondary_warning}


def _load_sidecar(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        print(f"ERROR: sidecar not found: {p}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR: cannot parse sidecar {p}: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="gate", required=True)
    for gate in ("tech-review", "quality-gate"):
        p = sub.add_parser(gate)
        p.add_argument("--sidecar", required=True)
        p.add_argument("--max-iter", type=int, default=2)

    args = parser.parse_args()
    sidecar = _load_sidecar(args.sidecar)

    if args.gate == "tech-review":
        sev = sidecar.get("severity_counts") or {}
        decision = decide_tech_review(
            confidence=sidecar.get("confidence", ""),
            critical=int(sev.get("critical", 0)),
            significant=int(sev.get("significant", 0)),
            iteration=int(sidecar.get("iteration", 1)),
            max_iter=args.max_iter,
        )
    else:
        decision = decide_quality_gate(
            intent_alignment=int(sidecar.get("intent_alignment", 0)),
            doc_quality=int(sidecar.get("doc_quality", 0)),
            iteration=int(sidecar.get("iteration", 1)),
            max_iter=args.max_iter,
        )

    print(json.dumps(decision, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

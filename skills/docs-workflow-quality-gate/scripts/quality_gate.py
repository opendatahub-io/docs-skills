"""Quality gate support for docs-orchestrator pipeline.

Prepares judge inputs and classifies judge outputs. Judge scoring
is handled by Claude Code agents (not direct API calls).

Subcommands:
    prepare  — Read pipeline outputs, write judge prompt files
    classify — Read agent judge results, classify gaps, write step-result.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PASS_THRESHOLD_INTENT = 4
PASS_THRESHOLD_DOC_QUALITY = 3

DOC_QUALITY_PROMPT = """\
You are evaluating AI-generated AsciiDoc documentation for a Red Hat product feature.

Score the documentation on a 1-5 scale:
1 - Unusable: major errors, fabricated content, or missing critical sections
2 - Poor: significant gaps in coverage or accuracy
3 - Acceptable: covers the basics correctly but lacks depth or polish
4 - Good: comprehensive, accurate, well-structured, minor issues only
5 - Excellent: production-ready quality, matches what a senior tech writer would produce

Consider: technical accuracy, completeness relative to the JIRA ticket scope,
modular documentation structure (concept/procedure/reference separation),
and absence of fabricated commands, flags, or API details.

## Documentation to evaluate

{doc_content}
"""

INTENT_ALIGNMENT_PROMPT = """\
You are evaluating whether AI-generated documentation fulfills the intent
of the original JIRA ticket that requested it.

## JIRA ticket intent

{ticket_context}

## Documentation produced

{doc_content}

## Scoring criteria

Score on a 1-5 scale based on how well the documentation fulfills the ticket's intent:

1 - Off-target: documentation covers unrelated topics or misunderstands the request
2 - Partially relevant: touches on the right area but misses the core ask
3 - Addresses the intent: covers the main topic but misses key acceptance criteria or scope items
4 - Strong alignment: covers the intent well, addresses most acceptance criteria, correct audience
5 - Full alignment: directly addresses the ticket intent, covers all acceptance criteria, \
matches the target audience, stays within scope

Consider:
- **Scope match**: does the output address what the ticket asked for, not more, not less?
- **Acceptance criteria coverage**: are the specific deliverables listed in the ticket addressed?
- **Audience alignment**: does the content match the target audience \
(admin vs developer vs data scientist)?
- **Focus**: does the output stay on-topic or wander into areas outside the ticket's scope?

For each missed or incomplete acceptance criteria item, identify the specific file and \
section where the fix should be applied. Name the AsciiDoc filename (from the headers above) \
and the section heading or location where content should be added or expanded. If a new \
section is needed, name the file it belongs in and where it should be inserted relative to \
existing sections.
"""


def read_doc_content(base_path):
    """Read AsciiDoc/Markdown files listed in writing/step-result.json."""
    sidecar = Path(base_path) / "writing" / "step-result.json"
    if not sidecar.exists():
        print(f"ERROR: {sidecar} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(sidecar.read_text())
    files = data.get("files", [])
    if not files:
        print("ERROR: No files listed in writing/step-result.json", file=sys.stderr)
        sys.exit(1)

    root = Path(base_path).resolve()
    parts = []
    for fpath in files:
        p = Path(fpath).resolve()
        if not p.is_relative_to(root):
            print(f"ERROR: path outside workspace: {p}", file=sys.stderr)
            sys.exit(1)
        if not p.exists() or p.suffix not in (".adoc", ".md"):
            print(f"WARNING: skipping {p} (missing or unsupported suffix)", file=sys.stderr)
            continue
        parts.append(f"### {p.name}\n\n{p.read_text()}")
    if not parts:
        print("ERROR: No readable documentation files found", file=sys.stderr)
        sys.exit(1)
    return "\n\n".join(parts)


def read_ticket_context(base_path):
    """Read requirements/discovery.json and format as ticket context."""
    discovery = Path(base_path) / "requirements" / "discovery.json"
    if not discovery.exists():
        msg = f"ERROR: {discovery} not found — required for intent-alignment judge"
        print(msg, file=sys.stderr)
        sys.exit(1)

    data = json.loads(discovery.read_text())
    lines = [f"**Ticket**: {data.get('ticket_summary', 'Unknown')}"]

    reqs = data.get("requirements", [])
    if reqs:
        lines.append("\n**Requirements / Acceptance Criteria**:\n")
        for r in reqs:
            rid = r.get("id", "?")
            title = r.get("title", "")
            summary = r.get("one_line_summary", "")
            lines.append(f"- {rid}: {title} — {summary}")

    return "\n".join(lines)


def read_evidence_status(base_path):
    """Read scope-req-audit/evidence-status.json if available."""
    evidence = Path(base_path) / "scope-req-audit" / "evidence-status.json"
    if not evidence.exists():
        evidence = Path(base_path) / "validate" / "evidence-status.json"
    if not evidence.exists():
        return None
    return json.loads(evidence.read_text())


def classify_gaps(missed_items, evidence_status):
    """Cross-reference missed AC items against evidence status."""
    gaps = []
    req_statuses = {}
    if evidence_status:
        for req in evidence_status.get("requirements", []):
            req_statuses[req.get("id", "")] = req
            title_lower = req.get("title", "").lower()
            req_statuses[title_lower] = req

    for item in missed_items:
        ac_text = item.get("ac_item", "")
        ac_lower = ac_text.lower()
        req_id = item.get("id", "")

        ev_status = "unknown"
        action = "investigate"

        if req_id and req_id in req_statuses:
            ev_status = req_statuses[req_id].get("status", "unknown")
        else:
            for key, req in req_statuses.items():
                if isinstance(key, str) and key == ac_lower:
                    ev_status = req.get("status", "unknown")
                    break

        if ev_status == "absent":
            action = "document_as_unsupported"
        elif ev_status == "partial":
            action = "expand_with_evidence"
        elif ev_status == "grounded":
            action = "add_missing_section"

        gap = {
            "ac_item": ac_text,
            "judge": "intent_alignment",
            "evidence_status": ev_status,
            "action": action,
        }
        if item.get("file"):
            gap["file"] = item["file"]
        if item.get("section"):
            gap["section"] = item["section"]
        gaps.append(gap)

    return gaps


def write_results(output_dir, ticket, doc_quality_result, intent_result, gaps, iteration):
    """Write step-result.json and judge-results.md."""
    output_dir.mkdir(parents=True, exist_ok=True)

    dq_score = doc_quality_result.get("score", 0)
    ia_score = intent_result.get("score", 0)
    passed = ia_score >= PASS_THRESHOLD_INTENT and dq_score >= PASS_THRESHOLD_DOC_QUALITY

    sidecar = {
        "schema_version": 1,
        "step": "quality-gate",
        "ticket": ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "doc_quality": dq_score,
        "intent_alignment": ia_score,
        "passed": passed,
        "iteration": iteration,
        "gaps": gaps,
        "rationales": {
            "doc_quality": doc_quality_result.get("rationale", ""),
            "intent_alignment": intent_result.get("rationale", ""),
        },
    }
    (output_dir / "step-result.json").write_text(json.dumps(sidecar, indent=2))

    md_lines = [
        f"# Quality Gate Results — {ticket}\n",
        f"**doc_quality**: {dq_score}/5",
        f"**intent_alignment**: {ia_score}/5",
        f"**passed**: {passed}",
        f"**iteration**: {iteration}\n",
        "## Doc Quality Rationale\n",
        doc_quality_result.get("rationale", "(none)"),
        "\n## Intent Alignment Rationale\n",
        intent_result.get("rationale", "(none)"),
    ]

    if gaps:
        md_lines.append("\n## Identified Gaps\n")
        for g in gaps:
            md_lines.append(
                f"- **{g['ac_item']}** — evidence: {g['evidence_status']}, action: {g['action']}"
            )

    (output_dir / "judge-results.md").write_text("\n".join(md_lines))

    return sidecar


def cmd_prepare(args):
    """Read pipeline outputs and write judge prompt files."""
    base_path = Path(args.base_path)
    output_dir = base_path / "quality-gate"
    output_dir.mkdir(parents=True, exist_ok=True)

    doc_content = read_doc_content(base_path)
    ticket_context = read_ticket_context(base_path)

    safe_doc = doc_content.replace("{", "{{").replace("}", "}}")
    safe_ticket = ticket_context.replace("{", "{{").replace("}", "}}")

    dq_prompt = DOC_QUALITY_PROMPT.format(doc_content=safe_doc)
    ia_prompt = INTENT_ALIGNMENT_PROMPT.format(
        ticket_context=safe_ticket,
        doc_content=safe_doc,
    )

    (output_dir / "dq-prompt.md").write_text(dq_prompt)
    (output_dir / "ia-prompt.md").write_text(ia_prompt)

    result = {
        "dq_prompt": str(output_dir / "dq-prompt.md"),
        "ia_prompt": str(output_dir / "ia-prompt.md"),
    }
    json.dump(result, sys.stdout, indent=2)
    print()


def cmd_classify(args):
    """Read agent judge results, classify gaps, write step-result.json."""
    base_path = Path(args.base_path)
    output_dir = base_path / "quality-gate"

    judge_results = json.loads(Path(args.judge_results).read_text())
    evidence_status = read_evidence_status(base_path)

    dq_result = judge_results["doc_quality"]
    ia_result = judge_results["intent_alignment"]

    missed_items = ia_result.get("missed_items", [])
    gaps = classify_gaps(missed_items, evidence_status)

    sidecar = write_results(
        output_dir,
        args.ticket,
        dq_result,
        ia_result,
        gaps,
        args.iteration,
    )

    json.dump(sidecar, sys.stdout, indent=2)
    print()


def main():
    parser = argparse.ArgumentParser(description="Quality gate support")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prep = subparsers.add_parser("prepare", help="Read inputs, write judge prompts")
    prep.add_argument("--ticket", required=True)
    prep.add_argument("--base-path", required=True)

    classify = subparsers.add_parser("classify", help="Classify judge results")
    classify.add_argument("--ticket", required=True)
    classify.add_argument("--base-path", required=True)
    classify.add_argument(
        "--judge-results",
        required=True,
        help="Path to JSON file with doc_quality and intent_alignment results",
    )
    classify.add_argument("--iteration", type=int, default=1)

    args = parser.parse_args()
    if args.command == "prepare":
        cmd_prepare(args)
    elif args.command == "classify":
        cmd_classify(args)


if __name__ == "__main__":
    main()

"""Quality gate support for docs-orchestrator pipeline.

Subcommands:
    prepare  — Read pipeline outputs, write judge prompt files
    verify   — Per-AC coverage check (--prepare writes prompts, --classify validates quotes)
    classify — Read agent judge results, classify gaps, write step-result.json
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_artifact_id(value):
    """Sanitize a string for use as a filename component."""
    return _SAFE_ID_RE.sub("_", value).strip("._") or "item"


def _resolve_under(path, root):
    """Resolve path and verify it stays inside root."""
    resolved = Path(path).resolve()
    root = Path(root).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path outside workspace: {resolved}")
    return resolved

PASS_THRESHOLD_INTENT = 4

COVERAGE_CHECK_PROMPT = """\
Does this documentation address the following acceptance criterion?

## Acceptance criterion

{ac_text}

## Documentation

{doc_content}

## Instructions

1. Read the documentation carefully.
2. Determine whether the acceptance criterion is addressed.
3. If yes, quote the single most relevant supporting sentence from the \
documentation VERBATIM — copy it exactly as written, including punctuation.
4. If no, set covered to false and quote to null.
5. Return JSON only, with this exact shape:
   {{"covered": true, "quote": "verbatim sentence"}} or {{"covered": false, "quote": null}}
"""

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


def normalize_whitespace(text):
    """Collapse whitespace runs to single space for substring matching."""
    return " ".join(text.split())


def verify_quote(quote, doc_content):
    """Check if a quote exists in the doc content (whitespace-normalized)."""
    if not quote:
        return False
    return normalize_whitespace(quote) in normalize_whitespace(doc_content)


def read_ac_items(base_path):
    """Read discovery.json and flatten acceptance_criteria into a list."""
    discovery = Path(base_path) / "requirements" / "discovery.json"
    if not discovery.exists():
        print(f"ERROR: {discovery} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(discovery.read_text())
    items = []
    for req in data.get("requirements", []):
        req_id = req.get("id", "")
        for i, ac_text in enumerate(req.get("acceptance_criteria", [])):
            items.append({
                "req_id": req_id,
                "ac_index": i,
                "ac_text": ac_text,
            })
    return items


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
    reqs_by_id = {}
    reqs_by_title = {}
    if evidence_status:
        for req in evidence_status.get("requirements", []):
            rid = req.get("id", "")
            if rid:
                reqs_by_id[rid] = req
            title_lower = req.get("title", "").lower()
            if title_lower:
                reqs_by_title[title_lower] = req

    for item in missed_items:
        ac_text = item.get("ac_item", "")
        ac_lower = ac_text.lower()
        req_id = item.get("id", "")

        ev_status = "unknown"
        action = "investigate"

        if req_id and req_id in reqs_by_id:
            ev_status = reqs_by_id[req_id].get("status", "unknown")
        elif ac_lower in reqs_by_title:
            ev_status = reqs_by_title[ac_lower].get("status", "unknown")

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


def classify_coverage(manifest, doc_content, evidence_status, output_dir):
    """Validate quotes and join to evidence status for each AC item."""
    reqs_by_id = {}
    if evidence_status:
        for req in evidence_status.get("requirements", []):
            rid = req.get("id", "")
            if rid:
                reqs_by_id[rid] = req

    results = []
    for entry in manifest.get("items", []):
        result_file = _resolve_under(entry["result_file"], output_dir)
        agent_result = {"covered": False, "quote": None}
        if result_file.exists():
            try:
                agent_result = json.loads(result_file.read_text())
            except (json.JSONDecodeError, KeyError):
                pass

        agent_covered = agent_result.get("covered", False) is True
        quote = agent_result.get("quote")
        quote_verified = verify_quote(quote, doc_content) if agent_covered else False

        req_id = entry["req_id"]
        ev_status = "unknown"
        if req_id in reqs_by_id:
            ev_status = reqs_by_id[req_id].get("status", "unknown")

        if agent_covered and quote_verified:
            classification = "covered"
            action = None
        elif agent_covered and not quote_verified:
            classification = "unverified"
            action = "investigate"
        elif ev_status == "grounded":
            classification = "real_defect"
            action = "add_missing_section"
        elif ev_status == "partial":
            classification = "real_defect"
            action = "expand_with_evidence"
        elif ev_status == "absent":
            classification = "correctly_absent"
            action = "document_as_unsupported"
        else:
            classification = "investigate"
            action = "investigate"

        results.append({
            "id": entry["id"],
            "req_id": req_id,
            "ac_index": entry["ac_index"],
            "ac_text": entry["ac_text"],
            "covered": agent_covered and quote_verified,
            "quote": quote if quote_verified else None,
            "quote_verified": quote_verified,
            "evidence_status": ev_status,
            "classification": classification,
            "action": action,
        })

    covered_count = sum(1 for r in results if r["classification"] == "covered")
    return {
        "total": len(results),
        "covered": covered_count,
        "uncovered": len(results) - covered_count,
        "items": results,
    }


def write_results(output_dir, ticket, doc_quality_result, intent_result, gaps, iteration,
                  coverage_check=None):
    """Write step-result.json and judge-results.md."""
    output_dir.mkdir(parents=True, exist_ok=True)

    dq_score = doc_quality_result.get("score", 0)
    ia_score = intent_result.get("score", 0)
    passed = ia_score >= PASS_THRESHOLD_INTENT

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
    if coverage_check is not None:
        sidecar["coverage_check"] = {
            "total": coverage_check["total"],
            "covered": coverage_check["covered"],
            "uncovered": coverage_check["uncovered"],
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

    dq_prompt = DOC_QUALITY_PROMPT.format(doc_content=doc_content)
    ia_prompt = INTENT_ALIGNMENT_PROMPT.format(
        ticket_context=ticket_context,
        doc_content=doc_content,
    )

    (output_dir / "dq-prompt.md").write_text(dq_prompt)
    (output_dir / "ia-prompt.md").write_text(ia_prompt)

    result = {
        "dq_prompt": str(output_dir / "dq-prompt.md"),
        "ia_prompt": str(output_dir / "ia-prompt.md"),
    }
    json.dump(result, sys.stdout, indent=2)
    print()


def cmd_verify(args):
    """Per-AC coverage verification: prepare prompts or classify results."""
    base_path = Path(args.base_path)
    output_dir = base_path / "quality-gate"

    if args.prepare:
        ac_items = read_ac_items(base_path)
        if not ac_items:
            result = {"items": []}
            json.dump(result, sys.stdout, indent=2)
            print()
            return

        doc_content = read_doc_content(base_path)
        prompts_dir = output_dir / "coverage-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        results_dir = output_dir / "coverage-results"
        results_dir.mkdir(parents=True, exist_ok=True)

        for stale in results_dir.glob("*.json"):
            stale.unlink()
        stale_check = output_dir / "coverage-check.json"
        if stale_check.exists():
            stale_check.unlink()

        manifest_items = []
        for item in ac_items:
            item_id = f"{_safe_artifact_id(item['req_id'])}_AC{item['ac_index']:02d}"
            prompt = COVERAGE_CHECK_PROMPT.format(
                ac_text=item["ac_text"],
                doc_content=doc_content,
            )
            prompt_file = prompts_dir / f"{item_id}.md"
            prompt_file.write_text(prompt)

            manifest_items.append({
                "id": item_id,
                "req_id": item["req_id"],
                "ac_index": item["ac_index"],
                "ac_text": item["ac_text"],
                "prompt_file": str(prompt_file),
                "result_file": str(results_dir / f"{item_id}.json"),
            })

        manifest = {"items": manifest_items}
        (prompts_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2)
        )
        json.dump(manifest, sys.stdout, indent=2)
        print()

    elif args.classify:
        manifest_path = output_dir / "coverage-prompts" / "manifest.json"
        if not manifest_path.exists():
            print(f"ERROR: {manifest_path} not found", file=sys.stderr)
            sys.exit(1)

        manifest = json.loads(manifest_path.read_text())
        doc_content = read_doc_content(base_path)
        evidence_status = read_evidence_status(base_path)

        coverage = classify_coverage(manifest, doc_content, evidence_status, output_dir)
        coverage_path = output_dir / "coverage-check.json"
        coverage_path.write_text(json.dumps(coverage, indent=2))

        json.dump(coverage, sys.stdout, indent=2)
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

    coverage_check = None
    coverage_path = output_dir / "coverage-check.json"
    if coverage_path.exists():
        coverage_check = json.loads(coverage_path.read_text())
        judge_ac_texts = {g["ac_item"].lower() for g in gaps}
        for item in coverage_check.get("items", []):
            if item["classification"] == "covered":
                continue
            if item["ac_text"].lower() in judge_ac_texts:
                for g in gaps:
                    if g["ac_item"].lower() == item["ac_text"].lower():
                        g["judge"] = "coverage_check"
                        g["evidence_status"] = item["evidence_status"]
                        g["action"] = item["action"]
                        g["classification"] = item["classification"]
                        break
            else:
                gaps.append({
                    "ac_item": item["ac_text"],
                    "judge": "coverage_check",
                    "evidence_status": item["evidence_status"],
                    "action": item["action"],
                    "classification": item["classification"],
                })

    sidecar = write_results(
        output_dir,
        args.ticket,
        dq_result,
        ia_result,
        gaps,
        args.iteration,
        coverage_check=coverage_check,
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

    verify_parser = subparsers.add_parser(
        "verify", help="Per-AC coverage verification"
    )
    verify_parser.add_argument("--ticket", required=True)
    verify_parser.add_argument("--base-path", required=True)
    verify_mode = verify_parser.add_mutually_exclusive_group(required=True)
    verify_mode.add_argument(
        "--prepare", action="store_true", help="Write per-AC prompt files"
    )
    verify_mode.add_argument(
        "--classify", action="store_true",
        help="Validate quotes, classify coverage",
    )

    args = parser.parse_args()
    if args.command == "prepare":
        cmd_prepare(args)
    elif args.command == "classify":
        cmd_classify(args)
    elif args.command == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()

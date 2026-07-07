"""Quality gate support for docs-orchestrator pipeline.

Subcommands:
    prepare      — Read pipeline outputs, write judge prompt files
    verify       — AC coverage check (--prepare writes one combined prompt,
                   --classify validates quotes from the single results file)
    classify     — Read agent judge results, classify gaps, write step-result.json
    extract-json — Pull a JSON object from a judge/coverage agent's free-text
                   reply, validate it against a schema, and write it out
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


def extract_json_value(text):
    """Extract the first JSON object/array from an agent's free-text reply.

    The Agent tool has no schema-enforced output, so judge and coverage agents
    return prose that wraps the JSON — typically in a ```json fence. Prefer the
    last fenced block (agents sometimes echo the schema first), then fall back
    to the first balanced ``{...}`` or ``[...]`` span. Raises ValueError if no
    parseable JSON is found.
    """
    fences = re.findall(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    for block in reversed(fences):
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            continue

    closer_for = {"{": "}", "[": "]"}
    pos = 0
    while pos < len(text):
        # Start from whichever opener ('{' or '[') appears first from here.
        candidates = [text.find(c, pos) for c in closer_for]
        candidates = [c for c in candidates if c != -1]
        if not candidates:
            break
        start = min(candidates)
        opener = text[start]
        closer = closer_for[opener]
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
        pos = start + 1

    raise ValueError("no parseable JSON object or array found in agent reply")


def validate_against_schema(data, schema):
    """Validate ``data`` against a JSON Schema, returning a list of error strings.

    Uses ``jsonschema`` for full validation when available (CI, dev). Falls
    back to a shallow required-key/top-level-type check so the script stays
    usable in runtimes without the dependency installed.
    """
    try:
        import jsonschema
    except ImportError:
        errors = []
        expected = schema.get("type")
        type_map = {"object": dict, "array": list, "string": str, "integer": int}
        if expected in type_map and not isinstance(data, type_map[expected]):
            errors.append(f"top-level value is not a JSON {expected}")
            return errors
        if expected == "object":
            for key in schema.get("required", []):
                if key not in data:
                    errors.append(f"missing required key: {key}")
        return errors

    validator = jsonschema.Draft7Validator(schema)
    return [e.message for e in validator.iter_errors(data)]


def cmd_extract_json(args):
    raw_text = Path(args.raw).read_text()
    schema = json.loads(Path(args.schema).read_text())

    try:
        data = extract_json_value(raw_text)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    errors = validate_against_schema(data, schema)
    if errors:
        print("ERROR: agent output does not conform to schema:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if args.key:
        if not isinstance(data, dict) or args.key not in data:
            print(f"ERROR: extracted JSON has no '{args.key}' key", file=sys.stderr)
            return 1
        out = data[args.key]
    else:
        out = data
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"Written {out_path}")
    return 0


PASS_THRESHOLD_INTENT = 4

COVERAGE_CHECK_PROMPT = """\
Determine whether this documentation addresses each of the following acceptance criteria.

## Acceptance criteria

{ac_list}

## Documentation

{doc_content}

## Instructions

1. Read the documentation carefully — you read it once and answer for every criterion below.
2. For EACH acceptance criterion, decide whether the documentation addresses it.
3. If it is addressed, quote the single most relevant supporting sentence from the \
documentation VERBATIM — copy it exactly as written, including punctuation.
4. If it is not addressed, set covered to false and quote to null.
5. Output a single JSON object inside a ```json fenced code block, with an "items"
   array holding one object per criterion, in the same order, each shaped exactly:
   {{"id": "<the ID shown in brackets>", "covered": true, "quote": "verbatim sentence"}}
   or {{"id": "<the ID shown in brackets>", "covered": false, "quote": null}}
6. The full reply must be:
   ```json
   {{"items": [ ... ]}}
   ```
   Output only that fenced JSON object — no prose before or after it.
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

## Output

Output only a single JSON object inside a ```json fenced code block, shaped exactly:

```json
{{"score": <integer 1-5>, "rationale": "<detailed rationale for the score>"}}
```

No prose before or after the fenced block.
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

## Output

Output only a single JSON object inside a ```json fenced code block, shaped exactly:

```json
{{
  "score": <integer 1-5>,
  "rationale": "<detailed rationale>",
  "missed_items": [
    {{"ac_item": "<text>", "severity": "missing|incomplete",
      "file": "<filename>", "section": "<heading or location>"}}
  ]
}}
```

Use an empty array for "missed_items" if nothing is missed. No prose before or after \
the fenced block.
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
    """Read per-requirement analysis files and flatten acceptance_criteria."""
    req_dir = Path(base_path) / "requirements"
    items = []

    req_files = sorted(req_dir.glob("req-*.json"))
    if req_files:
        for req_file in req_files:
            try:
                data = json.loads(req_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            req_id = data.get("id", "")
            for i, ac_text in enumerate(data.get("acceptance_criteria", [])):
                items.append(
                    {
                        "req_id": req_id,
                        "ac_index": i,
                        "ac_text": ac_text,
                    }
                )
        if items:
            return items

    discovery = req_dir / "discovery.json"
    if not discovery.exists():
        print(f"ERROR: {discovery} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(discovery.read_text())
    req_count = len(data.get("requirements", []))
    for req in data.get("requirements", []):
        req_id = req.get("id", "")
        for i, ac_text in enumerate(req.get("acceptance_criteria", [])):
            items.append(
                {
                    "req_id": req_id,
                    "ac_index": i,
                    "ac_text": ac_text,
                }
            )
    if not items and req_count > 0:
        print(
            f"WARNING: 0 AC items found but {req_count} requirements exist. "
            f"Check whether per-requirement files contain acceptance_criteria.",
            file=sys.stderr,
        )
    return items


def read_doc_content(base_path):
    """Read AsciiDoc/Markdown files listed in writing/step-result.json."""
    sidecar = Path(base_path) / "writing" / "step-result.json"
    if not sidecar.exists():
        print(f"ERROR: {sidecar} not found", file=sys.stderr)
        sys.exit(1)

    data = json.loads(sidecar.read_text())
    files = data.get("files", [])
    mode = data.get("mode", "draft")
    if not files:
        print("ERROR: No files listed in writing/step-result.json", file=sys.stderr)
        sys.exit(1)

    if mode == "update-in-place":
        import subprocess

        root = Path(
            subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
        ).resolve()
    else:
        root = Path(base_path).resolve()

    parts = []
    for fpath in files:
        p = Path(fpath).resolve()
        if not p.is_relative_to(root):
            print(f"WARNING: skipping {p} (outside workspace root {root})", file=sys.stderr)
            continue
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
        if not isinstance(item, dict):
            continue
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
            "file": item.get("file") or None,
            "section": item.get("section") or None,
        }
        gaps.append(gap)

    return gaps


def classify_coverage(manifest, results_by_id, doc_content, evidence_status):
    """Validate quotes and join to evidence status for each AC item.

    ``results_by_id`` maps an AC item id to the coverage agent's result object
    (``{"covered": bool, "quote": str|None}``). Items with no agent result
    default to uncovered.
    """
    reqs_by_id = {}
    if evidence_status:
        for req in evidence_status.get("requirements", []):
            rid = req.get("id", "")
            if rid:
                reqs_by_id[rid] = req

    results = []
    for entry in manifest.get("items", []):
        agent_result = results_by_id.get(entry["id"]) or {"covered": False, "quote": None}

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

        results.append(
            {
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
            }
        )

    covered_count = sum(1 for r in results if r["classification"] == "covered")
    return {
        "total": len(results),
        "covered": covered_count,
        "uncovered": len(results) - covered_count,
        "items": results,
    }


def write_results(
    output_dir,
    ticket,
    doc_quality_result,
    intent_result,
    gaps,
    iteration,
    coverage_check=None,
    evidence_expected=False,
    evidence_warning=None,
):
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
        "evidence_expected": evidence_expected,
        "evidence_warning": evidence_warning,
        "gaps": gaps,
        "rationales": {
            "doc_quality": doc_quality_result.get("rationale", ""),
            "intent_alignment": intent_result.get("rationale", ""),
        },
    }
    sidecar["coverage_check"] = (
        {
            "total": coverage_check["total"],
            "covered": coverage_check["covered"],
            "uncovered": coverage_check["uncovered"],
        }
        if coverage_check is not None
        else None
    )
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


ACTION_INSTRUCTIONS = {
    "document_as_unsupported": (
        "Add a note stating that this capability is not supported in this release. "
        "Place it in the most relevant existing module — do not create a new module."
    ),
    "expand_with_evidence": (
        "Expand the existing content with available code evidence. Check the source repo "
        "for relevant API fields, flags, or config options."
    ),
    "add_missing_section": (
        "This content was in the plan but was not included in the writing output. "
        "Add the missing section based on the requirements and plan."
    ),
    "investigate": (
        "This gap could not be classified. Review the requirements and determine whether "
        "to document it or note it as out of scope."
    ),
}

UNVERIFIED_NOTE = (
    "Quote could not be verified in the document. Review whether this criterion is "
    "actually addressed."
)


def _action_instruction(classification, action):
    """Map a coverage classification/action to a fix instruction."""
    if classification == "unverified":
        return UNVERIFIED_NOTE
    return ACTION_INSTRUCTIONS.get(action, ACTION_INSTRUCTIONS["investigate"])


def render_brief(ticket, iteration, sidecar, coverage_check):
    """Render the feedback-brief markdown from the quality-gate sidecar + coverage check.

    Replaces the hand-rendered template in docs-workflow-quality-gate/SKILL.md step 7.
    """
    rationales = sidecar.get("rationales", {})
    gaps = sidecar.get("gaps", [])
    lines = [
        f"# Feedback Brief for {ticket} (iteration {iteration})",
        "",
        "## Intent Alignment Judge Assessment",
        "",
        rationales.get("intent_alignment", "(none)"),
        "",
        "## Doc Quality Judge Assessment",
        "",
        rationales.get("doc_quality", "(none)"),
        "",
    ]

    if coverage_check is not None:
        covered = coverage_check.get("covered", 0)
        total = coverage_check.get("total", 0)
        lines += [
            "## Coverage Check Results",
            "",
            f"AC coverage: {covered}/{total} acceptance criteria addressed with verified quotes.",
            "",
            "### Uncovered AC Items",
            "",
        ]
        uncovered = [
            it for it in coverage_check.get("items", []) if it.get("classification") != "covered"
        ]
        if uncovered:
            for it in uncovered:
                note = _action_instruction(it.get("classification"), it.get("action"))
                lines += [
                    f"- **{it.get('ac_text', '')}** (from {it.get('req_id', '?')})",
                    f"  - Classification: {it.get('classification', 'unknown')}",
                    f"  - Evidence status: {it.get('evidence_status', 'unknown')}",
                    f"  - Action: {note}",
                ]
        else:
            lines.append("All acceptance criteria are covered with verified quotes.")
        lines.append("")

    lines += ["## Classified Gaps with Recommended Actions", ""]
    if gaps:
        for g in gaps:
            lines += [
                f"### Gap: {g.get('ac_item', '')}",
                f"- **File**: {g.get('file', '(unspecified)')}",
                f"- **Section**: {g.get('section', '(unspecified)')}",
                f"- **Evidence status**: {g.get('evidence_status', 'unknown')}",
                f"- **Action**: {_action_instruction(g.get('classification'), g.get('action'))}",
                "",
            ]
    else:
        lines += ["No classified gaps.", ""]

    if iteration > 1:
        lines += [
            "## Prior attempts",
            "",
            f"This is iteration {iteration}. A previous fix pass was attempted but did not "
            "resolve these gaps. The writer must try a DIFFERENT approach — do not repeat the "
            "same fix. Consider:",
            "- Adding more concrete detail (specific API fields, config values, command examples)",
            "- Restructuring the section rather than appending",
            "- Checking source code for evidence that was missed in the first attempt",
            "",
        ]

    lines += [
        "## Priority",
        "",
        "Address gaps in this order:",
        '1. Items flagged as "missing" or "barely covered" — the largest scoring deductions',
        '2. Items flagged as "weakly covered" or "partially covered" — expand existing content',
        "3. Scope rebalancing — if the judge flagged over-indexing on one area, tighten it",
        "",
    ]

    return "\n".join(lines)


def cmd_brief(args):
    """Render feedback-brief-<iteration>.md from the quality-gate sidecar + coverage check."""
    output_dir = Path(args.base_path) / "quality-gate"
    sidecar_path = output_dir / "step-result.json"
    if not sidecar_path.exists():
        print(f"ERROR: {sidecar_path} not found", file=sys.stderr)
        sys.exit(1)
    sidecar = json.loads(sidecar_path.read_text())

    coverage_check = None
    coverage_path = output_dir / "coverage-check.json"
    if coverage_path.exists():
        coverage_check = json.loads(coverage_path.read_text())

    brief = render_brief(args.ticket, args.iteration, sidecar, coverage_check)
    brief_path = output_dir / f"feedback-brief-{args.iteration}.md"
    brief_path.write_text(brief)
    print(f"Written {brief_path}")


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
            print("prepared coverage prompt: 0 AC items (skip the coverage check)")
            return

        doc_content = read_doc_content(base_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Clear stale artifacts from a prior run so a re-run cannot mix results.
        for stale_name in ("coverage-results.json", "coverage-check.json"):
            stale = output_dir / stale_name
            if stale.exists():
                stale.unlink()

        manifest_items = []
        ac_lines = []
        for item in ac_items:
            item_id = f"{_safe_artifact_id(item['req_id'])}_AC{item['ac_index']:02d}"
            ac_lines.append(f"- [ID: {item_id}] {item['ac_text']}")
            manifest_items.append(
                {
                    "id": item_id,
                    "req_id": item["req_id"],
                    "ac_index": item["ac_index"],
                    "ac_text": item["ac_text"],
                }
            )

        # One combined prompt: the documentation is embedded once, every AC item
        # listed. A single agent answers all of them, reading the docs once.
        prompt = COVERAGE_CHECK_PROMPT.format(
            ac_list="\n".join(ac_lines),
            doc_content=doc_content,
        )
        prompt_file = output_dir / "coverage-prompt.md"
        prompt_file.write_text(prompt)

        manifest = {
            "items": manifest_items,
            "prompt_file": str(prompt_file),
            "result_file": str(output_dir / "coverage-results.json"),
        }
        (output_dir / "coverage-manifest.json").write_text(json.dumps(manifest, indent=2))
        print(f"prepared coverage prompt: {len(manifest_items)} AC items -> {prompt_file}")

    elif args.classify:
        manifest_path = output_dir / "coverage-manifest.json"
        if not manifest_path.exists():
            print(f"ERROR: {manifest_path} not found", file=sys.stderr)
            sys.exit(1)

        manifest = json.loads(manifest_path.read_text())
        items = manifest.get("items", [])

        # The coverage agent returns one JSON array; the orchestrator writes it
        # verbatim to coverage-results.json. Index it by AC item id.
        results_by_id = {}
        results_path = output_dir / "coverage-results.json"
        if results_path.exists():
            try:
                raw = json.loads(results_path.read_text())
            except json.JSONDecodeError:
                raw = []
            for entry in raw if isinstance(raw, list) else []:
                if isinstance(entry, dict) and entry.get("id"):
                    results_by_id[entry["id"]] = entry

        missing = [it["id"] for it in items if it["id"] not in results_by_id]
        if missing:
            print(
                f"WARNING: {len(missing)} of {len(items)} AC items have no agent result "
                f"(treated as uncovered): {', '.join(missing)}",
                file=sys.stderr,
            )

        doc_content = read_doc_content(base_path)
        evidence_status = read_evidence_status(base_path)

        if getattr(args, "evidence_expected", False) and evidence_status is None:
            print(
                "WARNING: --evidence-expected set but no evidence-status.json found. "
                "Gap classifications will degrade to unknown/investigate.",
                file=sys.stderr,
            )

        coverage = classify_coverage(manifest, results_by_id, doc_content, evidence_status)
        (output_dir / "coverage-check.json").write_text(json.dumps(coverage, indent=2))

        print(
            f"total={coverage['total']} covered={coverage['covered']} "
            f"uncovered={coverage['uncovered']}"
        )


def cmd_classify(args):
    """Read agent judge results, classify gaps, write step-result.json."""
    base_path = Path(args.base_path)
    output_dir = base_path / "quality-gate"

    if args.judge_results:
        judge_results = json.loads(Path(args.judge_results).read_text())
    else:
        judge_results = {
            "doc_quality": json.loads(Path(args.doc_quality).read_text()),
            "intent_alignment": json.loads(Path(args.intent_alignment).read_text()),
        }
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
                gaps.append(
                    {
                        "ac_item": item["ac_text"],
                        "judge": "coverage_check",
                        "evidence_status": item["evidence_status"],
                        "action": item["action"],
                        "classification": item["classification"],
                        "file": None,
                        "section": None,
                    }
                )

    evidence_expected = getattr(args, "evidence_expected", False)
    evidence_warning = None
    if evidence_expected and evidence_status is None:
        evidence_warning = (
            "scope-req-audit ran but evidence-status.json was not found; "
            "gap classifications may be incomplete"
        )
        print(f"WARNING: {evidence_warning}", file=sys.stderr)

    sidecar = write_results(
        output_dir,
        args.ticket,
        dq_result,
        ia_result,
        gaps,
        args.iteration,
        coverage_check=coverage_check,
        evidence_expected=evidence_expected,
        evidence_warning=evidence_warning,
    )

    print(
        f"doc_quality={sidecar['doc_quality']} "
        f"intent_alignment={sidecar['intent_alignment']} "
        f"passed={sidecar['passed']} gaps={len(sidecar['gaps'])}"
    )


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
        help="Combined JSON file with doc_quality and intent_alignment results",
    )
    classify.add_argument("--doc-quality", help="doc_quality result file (with --intent-alignment)")
    classify.add_argument(
        "--intent-alignment", help="intent_alignment result file (with --doc-quality)"
    )
    classify.add_argument("--iteration", type=int, default=1)
    classify.add_argument("--evidence-expected", action="store_true", default=False)

    verify_parser = subparsers.add_parser("verify", help="Per-AC coverage verification")
    verify_parser.add_argument("--ticket", required=True)
    verify_parser.add_argument("--base-path", required=True)
    verify_mode = verify_parser.add_mutually_exclusive_group(required=True)
    verify_mode.add_argument("--prepare", action="store_true", help="Write per-AC prompt files")
    verify_mode.add_argument(
        "--classify",
        action="store_true",
        help="Validate quotes, classify coverage",
    )
    verify_parser.add_argument(
        "--evidence-expected",
        action="store_true",
        help="Warn if evidence-status.json is missing (scope-req-audit ran)",
    )

    brief = subparsers.add_parser("brief", help="Render feedback-brief-<iteration>.md")
    brief.add_argument("--ticket", required=True)
    brief.add_argument("--base-path", required=True)
    brief.add_argument("--iteration", type=int, default=1)

    extract = subparsers.add_parser(
        "extract-json", help="Extract + validate a JSON object from an agent reply"
    )
    extract.add_argument("--raw", required=True, help="File holding the agent's raw reply")
    extract.add_argument("--schema", required=True, help="JSON Schema path to validate against")
    extract.add_argument("--out", required=True, help="Path to write the extracted JSON")
    extract.add_argument(
        "--key",
        default=None,
        help="Write only this top-level key's value (e.g. 'items' for coverage)",
    )

    args = parser.parse_args()
    if args.command == "prepare":
        cmd_prepare(args)
    elif args.command == "classify":
        if not args.judge_results and not (args.doc_quality and args.intent_alignment):
            parser.error(
                "classify requires --judge-results, or both --doc-quality and --intent-alignment"
            )
        cmd_classify(args)
    elif args.command == "verify":
        cmd_verify(args)
    elif args.command == "brief":
        cmd_brief(args)
    elif args.command == "extract-json":
        sys.exit(cmd_extract_json(args))


if __name__ == "__main__":
    main()

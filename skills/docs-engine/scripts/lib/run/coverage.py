#!/usr/bin/env python3
"""What the ticket asked for, measured against what the run wrote.

Every other gate reads one artifact. This one reads three: the requirements a
ticket yielded, the plan's claim about which deliverable answers each, and
what the writer did with those deliverables. A run can pass all three steps
and still answer half the ticket.

Deliberately arithmetic. A model decides which requirement a deliverable
covers; this checks that claim against the write records. A requirement
nothing claims is not documented, whatever the exit code said.
"""

from . import evidence

SCHEMA = "docs-skills/coverage/1"

# What a page resting on the ticket description alone proves. Under `strict`,
# only that the ticket agrees with itself. Under `accept`, the ticket is taken
# as the authority it often is on unreleased behaviour. The reason string names
# which one carried it, so `coverage.md` reads the same under both.
TICKET_POLICIES = ("strict", "accept")

# Best outcome first. Two deliverables can claim one requirement; the one that
# carried it decides, so a second page that gave up on the subject cannot pull
# a documented requirement back down.
RANK = ["documented", "needs-evidence", "deferred", "unsupported"]

WROTE = ("written", "unchanged")


def assess(requirements, plan, report, ticket_evidence="strict"):
    """One record per requirement, and whether the run is complete."""
    texts = [text for text in (requirements or []) if (text or "").strip()]
    if not texts:
        # Topic mode asks for nothing in particular. There is no claim to
        # check, and reporting that as a complete run would be a measurement
        # nobody took.
        return {"schema": SCHEMA, "status": "unassessed", "requirements": [], "unresolved": []}

    records = {r.get("deliverable"): r for r in (report or {}).get("results") or []}
    claims = _claims(plan, len(texts))
    deferred = _deferred(plan, len(texts))

    assessed = []
    for index, text in enumerate(texts, start=1):
        assessed.append(
            _one(
                index,
                text,
                claims.get(index, []),
                records,
                deferred.get(index),
                ticket_evidence,
            )
        )
    unresolved = [entry["id"] for entry in assessed if entry["status"] != "documented"]
    return {
        "schema": SCHEMA,
        "status": "complete" if not unresolved else "incomplete",
        "requirements": assessed,
        "unresolved": unresolved,
    }


def _one(index, text, paths, records, deferral, ticket_evidence="strict"):
    """This requirement's best outcome across every deliverable claiming it."""
    outcomes = [_outcome(records.get(path), path, ticket_evidence) for path in paths]
    if deferral:
        outcomes.append(("deferred", deferral))
    if not outcomes:
        outcomes = [("unsupported", "no deliverable in the plan covers it")]
    outcomes.sort(key=lambda outcome: RANK.index(outcome[0]))
    status, reason = outcomes[0]
    return {
        "id": index,
        "text": text,
        "status": status,
        "documents": sorted(paths),
        "reason": reason,
    }


def _outcome(record, path, ticket_evidence="strict"):
    """What one deliverable did with the requirement it claimed."""
    if record is None:
        return "unsupported", f"{path} is in the plan and not in the write report"
    status = record.get("status")
    if status not in WROTE:
        reason = record.get("reason") or f"{path} was {status}"
        return "deferred", f"{path}: {reason}"
    gaps = [gap for gap in record.get("gaps") or [] if (gap or "").strip()]
    if gaps:
        return "needs-evidence", f"{path} was written over its own gaps: {'; '.join(gaps[:3])}"
    cited = record.get("evidence") or []
    if not cited:
        dropped = record.get("evidence_unsupported") or []
        detail = f", and dropped {', '.join(dropped[:3])}" if dropped else ""
        return "needs-evidence", f"{path} cites no source this run read{detail}"
    if evidence.only_ticket(cited):
        reason = f"{path} rests on the ticket description and nothing this run could check"
        if ticket_evidence == "accept":
            return "documented", reason
        return "needs-evidence", reason
    return "documented", f"{path} cites {len(cited)} source(s)"


def _claims(plan, total):
    """Requirement id to the deliverables claiming it, ids out of range dropped."""
    claims = {}
    for item in (plan or {}).get("deliverables") or []:
        path = item.get("path")
        for number in item.get("requirements") or []:
            if isinstance(number, int) and 1 <= number <= total:
                claims.setdefault(number, [])
                if path not in claims[number]:
                    claims[number].append(path)
    return claims


def _deferred(plan, total):
    """Requirement id to the reason the plan gave for not covering it."""
    out = {}
    for entry in (plan or {}).get("deferred") or []:
        number = entry.get("requirement")
        if isinstance(number, int) and 1 <= number <= total:
            out[number] = (entry.get("reason") or "the plan deferred it").strip()
    return out


def render(subject, assessed):
    """`coverage.md`: one sourced bullet per requirement."""
    lines = [
        "---",
        "title: Coverage",
        "type: reference",
        "managed: generated",
        "---",
        "",
        f"# Coverage: {subject}",
        "",
    ]
    if assessed.get("status") == "unassessed":
        lines += ["No ticket set the requirements for this run [src:requirements.json]", ""]
        return "\n".join(lines)

    for entry in assessed.get("requirements") or []:
        source = ", ".join(entry["documents"]) or "nothing in the plan"
        lines.append(
            f"- {entry['text'].rstrip('.')}: {entry['status']}. "
            f"{entry['reason'].rstrip('.')} [src:{source}]"
        )
    lines += ["", "## Verdict", ""]
    unresolved = assessed.get("unresolved") or []
    if unresolved:
        lines.append(
            f"- {len(unresolved)} of {len(assessed['requirements'])} requirement(s) "
            "are not documented [src:write-report.json]"
        )
    else:
        lines.append("- Every requirement the ticket set is documented [src:write-report.json]")
    return "\n".join(lines) + "\n"

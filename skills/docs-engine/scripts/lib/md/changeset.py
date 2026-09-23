#!/usr/bin/env python3
"""One directory per run, holding new documents and updated ones side by side."""

from __future__ import annotations

import re
from pathlib import Path

from lib.md import docs_meta

_EDIT_SUFFIX = ".edit.md"
_DIFF_SUFFIX = ".diff"
_MD_SUFFIX = ".md"


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def marker_id(ticket, topic):
    """The ticket key, or the topic's slug when there is no ticket."""
    return ticket.strip() if ticket and ticket.strip() else _slug(topic)[:60]


def directory_for(docs_dir, ticket, topic, today, base=None):
    """Where this run's documents go, keyed by date and ticket."""
    name = marker_id(ticket, topic) or "run"
    if base is not None:
        parent = Path(base) / docs_dir
        if parent.is_dir():
            existing = sorted(p.name for p in parent.glob(f"changeset-*-{name}") if p.is_dir())
            if existing:
                return f"{docs_dir}/{existing[0]}"
    return f"{docs_dir}/changeset-{today}-{name}"


def index(report, placement, research=None, removals=None):
    """`index.md`: what the run produced, where it goes, and what it refused."""
    results = report.get("results") or []
    product = (placement or {}).get("product", "")
    version = (placement or {}).get("version", "")

    lines = [
        "---",
        "title: Changeset",
        "type: reference",
        "managed: generated",
        "---",
        "",
        "# Changeset",
        "",
        f"Targeting {product} {version}.".strip(),
        "",
        "## Documents",
        "",
        "| Deliverable | Kind | Goes | Why |",
        "| --- | --- | --- | --- |",
    ]
    written = [r for r in results if r.get("status") in ("written", "unchanged")]
    if written:
        for row in written:
            path = row.get("path", "")
            if row.get("kind") == "update":
                target = f"{row.get('guide_url', '')} section {row.get('section', '')}"
                goes = f"{path} → {target}" if path else target
            else:
                goes = path
            lines.append(
                f"| {row.get('deliverable', '')} | {row.get('kind', 'new')} | "
                f"{goes} | {row.get('summary') or row.get('reason', '')} |"
            )
    else:
        lines.append("| None | | | The run wrote nothing |")

    # A page kept in spite of prose that would not clear. It is in the table
    # above like any other, and this is where a reviewer is told which rules
    # it is still failing, so shipping it is a decision someone makes rather
    # than one nobody was told about.
    dirty = [r for r in written if r.get("prose") == "dirty"]
    if dirty:
        lines += ["", "## Unresolved prose", ""]
        for row in dirty:
            for alert in row.get("prose_unresolved") or []:
                lines.append(f"- {row.get('deliverable', '')}: {alert} [src:vale]")

    lines += ["", "## Not written", ""]
    refused = [r for r in results if r.get("status") in ("refused", "failed")]
    if refused:
        for row in refused:
            lines.append(f"- {row.get('deliverable', '')}: {row.get('reason', '')}")
    else:
        lines.append("- Every planned document was written")

    lines += ["", "## Gaps", ""]
    research_gaps = (research or {}).get("gaps") or []
    placement_gaps = (placement or {}).get("gaps") or []
    if research_gaps or placement_gaps:
        lines += [f"- {gap.rstrip('?')}? (research)" for gap in research_gaps]
        lines += [f"- {gap.rstrip('?')}? (placement)" for gap in placement_gaps]
    else:
        lines.append("- The run closed every question it raised")

    lines += ["", "## Removed", ""]
    removals = removals or []
    if removals:
        for row in removals:
            lines.append(
                f"- {row.get('path', '')}: {row.get('reason', '')} ({row.get('status', '')})"
            )
    else:
        lines.append("- Nothing needed removing")
    return "\n".join(lines) + "\n"


def _ownership_verdict(path):
    """Whether `path` may safely be deleted."""
    try:
        text = path.read_text()
    except OSError as exc:
        return None, f"could not be read: {exc}"
    try:
        front, _, _ = docs_meta.parse(text)
    except Exception as exc:
        return None, f"frontmatter could not be read: {exc}"
    if front.get("managed") == "manual":
        return True, "managed: manual"
    return False, None


def _record(repo, path, status, reason):
    return {"path": str(path.relative_to(repo)), "status": status, "reason": reason}


def _update_group_stem(name):
    """Return an update file's shared stem, or None for unrelated files."""
    if name.endswith(_EDIT_SUFFIX):
        return name[: -len(_EDIT_SUFFIX)]
    if name.endswith(_DIFF_SUFFIX):
        return name[: -len(_DIFF_SUFFIX)]
    if name.endswith(_MD_SUFFIX):
        return name[: -len(_MD_SUFFIX)]
    return None


def wipe(repo, docs_dir, name):
    """Remove a subject's changeset directories before a run writes into them.

    Without this, a draft from a run that stopped halfway sits beside this
    run's as though both belonged to it. `directory_for` reuses a directory
    whatever date it carries, so every dated one for this subject goes.

    A draft marked `managed: manual` is somebody's own work and is kept on the
    same promise `prune` makes, along with the directory holding it. Returns
    the records of what went and what stayed.
    """
    parent = Path(repo) / docs_dir
    if not parent.is_dir() or not name:
        return []
    records = []
    for changeset_dir in sorted(parent.glob(f"changeset-*-{name}")):
        if not changeset_dir.is_dir():
            continue
        for path in sorted(changeset_dir.rglob("*"), key=lambda p: -len(p.parts)):
            if path.is_dir():
                # Emptied by the files above it, or empty already. A directory
                # holding a kept draft still has it and stays.
                if not any(path.iterdir()):
                    path.rmdir()
                continue
            manual, reason = _ownership_verdict(path)
            if manual is False:
                path.unlink()
                records.append(_record(repo, path, "removed", "cleared before this run"))
            else:
                records.append(_record(repo, path, "kept", reason or "managed: manual"))
        if changeset_dir.is_dir() and not any(changeset_dir.iterdir()):
            changeset_dir.rmdir()
    return records


def prune(repo, changeset_dir, results):
    """Remove `new/` and `updates/` files this run's plan no longer accounts for."""
    repo = Path(repo)
    changeset_dir = Path(changeset_dir)
    records = []

    def exists(path):
        return bool(path) and (repo / path).is_file()

    new_dir = changeset_dir / "new"
    protected_new = {
        Path(r["path"]).name for r in results if r.get("kind") != "update" and exists(r.get("path"))
    }
    if new_dir.is_dir():
        for f in sorted(new_dir.iterdir()):
            if not f.is_file() or f.name in protected_new:
                continue
            manual, reason = _ownership_verdict(f)
            if manual is False:
                f.unlink()
                records.append(_record(repo, f, "removed", "no longer in the plan"))
            else:
                records.append(_record(repo, f, "kept", reason or "managed: manual"))

    updates_dir = changeset_dir / "updates"
    protected_stems = {
        _update_group_stem(Path(r["path"]).name)
        for r in results
        if r.get("kind") == "update" and exists(r.get("path"))
    }
    if updates_dir.is_dir():
        groups = {}
        for f in sorted(updates_dir.iterdir()):
            if not f.is_file():
                continue
            stem = _update_group_stem(f.name)
            if stem is None:
                continue
            groups.setdefault(stem, []).append(f)
        for stem in sorted(groups):
            if stem in protected_stems:
                continue
            files = groups[stem]
            edit = next((f for f in files if f.name == f"{stem}{_EDIT_SUFFIX}"), None)
            if edit is not None:
                # The normal shape of an update group: the `.edit.md` is the
                # file a human would mark, so its verdict speaks for the
                # whole set of three.
                verdict, reason = _ownership_verdict(edit)
                for f in files:
                    if verdict is False:
                        f.unlink()
                        records.append(_record(repo, f, "removed", "no longer in the plan"))
                    else:
                        records.append(_record(repo, f, "kept", reason or "managed: manual"))
            else:
                # No `.edit.md` means the group is not necessarily this
                # tool's output: it could be a bare `<stem>.md` someone put in
                # `updates/` by hand. Unlinking on sight would delete an
                # explicit `managed: manual` file unread, so each file stands
                # on its own verdict.
                for f in files:
                    verdict, reason = _ownership_verdict(f)
                    if verdict is False:
                        f.unlink()
                        records.append(_record(repo, f, "removed", "no longer in the plan"))
                    else:
                        records.append(_record(repo, f, "kept", reason or "managed: manual"))
    return records

"""The ownership contract both writers enforce.

`reference/generated-documents.md` states the rules. This is where they are
applied, so the two writers cannot drift apart on what `managed` means or on
how much of an existing document a model is allowed to see.
"""

import os
from pathlib import Path

from lib.md import docs_meta, fences, render


def claimed_paths(repo, docs_dir, plan, changeset_dir=None):
    """Every repo-relative path this plan accounts for.

    A deliverable's `path` is not a destination, and the three kinds disagree
    about what it is relative to. A foundation one is repo-relative and already
    carries the docs directory. An `update` names a page under `docs_dir`,
    nested or not, so it is `docs_dir`-relative: `update_deliverable` joins it
    onto `repo/docs_dir`, and `docs_inventory` produced it by relativising
    against that same root. A new topic page is a bare file name that
    `run_plan` joins onto the changeset directory, or onto `docs_dir` when
    there is none.

    Comparing the raw field against a path on disk matches none of them, which
    is how a prune deleted the pages the same run had just written, and how a
    review reported the page it had just updated as an orphan. Both callers
    read it from here so the joins cannot drift apart.
    """
    claimed = set()
    for item in plan.get("deliverables") or []:
        path = item.get("path")
        if not path:
            continue
        if item.get("foundation"):
            claimed.add(path)
            continue
        if item.get("kind") == "update":
            claimed.add(str(Path(docs_dir) / path))
            continue
        base = os.path.relpath(Path(changeset_dir) / "new", repo) if changeset_dir else docs_dir
        claimed.add(str(Path(base) / path))
    return claimed


class WriteRefusedError(RuntimeError):
    """The ownership contract forbids this write."""


def ownership(path):
    """Read a document's `managed` value. A file that is not there is `absent`."""
    if not path.exists():
        return "absent", {}, ""
    text = path.read_text()
    front, body, _ = docs_meta.parse(text)
    return front.get("managed", "manual"), front, text


def existing_summary(text, front, limit=12000):
    """What the writer may see of an existing document.

    An `assisted` file hands over only its fenced regions. The prose around
    them is the human's, and a model that never receives it cannot restate it,
    drift from it, or be talked into replacing it.
    """
    if front.get("managed") == "assisted":
        try:
            regions = fences.parse(text)
        except fences.FenceError as exc:
            raise WriteRefusedError(f"fence structure is broken: {exc}")
        return {
            "managed": "assisted",
            "regions": [
                {"section": r.section, "source": r.source, "body": r.body[:4000]} for r in regions
            ],
        }
    return {
        "managed": front.get("managed", "generated"),
        "frontmatter": front,
        "body": text[:limit],
    }


def write_assisted(target, payload, sha):
    """Within-file ownership. Only the fenced regions move."""
    text = target.read_text()
    try:
        regions = {r.section for r in fences.parse(text)}
    except fences.FenceError as exc:
        raise WriteRefusedError(f"fence structure is broken: {exc}")
    if not regions:
        raise WriteRefusedError("managed: assisted but the file has no docs-gen regions")

    original = text
    touched, skipped = [], []
    for section in payload.get("sections") or []:
        if section["id"] not in regions:
            skipped.append(section["id"])
            continue
        body = render.normalize(section.get("body") or "")
        text = fences.replace(text, section["id"], body, sha=sha)
        touched.append(section["id"])

    if text == original:
        return False, "no fenced region changed", skipped
    target.write_text(text)
    return True, f"rewrote {', '.join(touched)}", skipped

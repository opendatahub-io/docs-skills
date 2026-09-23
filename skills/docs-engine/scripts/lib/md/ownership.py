"""The ownership contract both writers enforce.

`reference/generated-documents.md` states the rules. This is where they are
applied, so the two writers cannot drift apart on what `managed` means or on
how much of an existing document a model is allowed to see.
"""

from lib.md import docs_meta, fences, render


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

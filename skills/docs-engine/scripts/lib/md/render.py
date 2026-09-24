#!/usr/bin/env python3
"""Turn a writer's JSON into Markdown, deterministically."""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.md import docs_meta  # noqa: E402

SCHEMA = "docs-skills/render/1"

# Prose churn under this many changed lines leaves the file alone. Section
# adds and removes bypass it: structural change is always worth showing.
DEFAULT_FLOOR = 3

TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
BLANK_RUN = re.compile(r"\n{3,}")


# ------------------------------------------------------------------ rendering


def body(sections, level=2):
    """Render `sections[]` to Markdown."""
    parts = []
    for section in sections:
        heading = (section.get("heading") or "").strip()
        depth = int(section.get("level") or level)
        depth = max(1, min(6, depth))
        if heading:
            parts.append("#" * depth + " " + heading)
        text = normalize(section.get("body") or "")
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip() + "\n"


def normalize(text):
    """Whitespace normalization only. Never reflows, never rewrites content."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = TRAILING_SPACE.sub("", text)
    text = BLANK_RUN.sub("\n\n", text)
    return text.strip()


def document(payload, front_overrides=None):
    """Full file: frontmatter block, then the rendered sections."""
    front = dict(payload.get("frontmatter") or {})
    front.update(front_overrides or {})
    text = body(payload.get("sections") or [], payload.get("level") or 2)
    if not front:
        return text
    return docs_meta.render(front, text)


MARKER_START = "<!-- docs-gen output {marker} -->"
MARKER_END = "<!-- end docs-gen -->"
MARKER_PATTERN = re.compile(
    r"<!--\s*docs-gen output\s+\S+\s*-->\n(?P<body>.*?)\n?<!--\s*end docs-gen\s*-->",
    re.DOTALL,
)


def wrap_marker(text, marker):
    """`text` bracketed in comment markers naming the run that produced it."""
    if not marker:
        return text
    return f"{MARKER_START.format(marker=marker)}\n{text.strip()}\n{MARKER_END}"


def marked_spans(text):
    """The content between each `docs-gen` marker pair, in order."""
    return [match.group("body") for match in MARKER_PATTERN.finditer(text or "")]


def merge_front(existing, generated, preserve=()):
    """Frontmatter for a regenerated file."""
    merged = dict(generated)
    keep = set(preserve) | {"managed"}
    for key in keep:
        if key in existing:
            merged[key] = existing[key]
    for key, value in existing.items():
        if key not in merged and key not in ("lastUpdated", "source_sha"):
            merged[key] = value
    return merged


# ---------------------------------------------------------------- diff floor


def changed_lines(before, after):
    """Count of added and removed lines between two renderings."""
    old = (before or "").splitlines()
    new = (after or "").splitlines()
    added = removed = 0
    for line in difflib.unified_diff(old, new, n=0, lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def structural_change(before, after):
    """Whether the heading set moved."""
    return _headings(before) != _headings(after)


def _headings(text):
    return [line.strip() for line in (text or "").splitlines() if line.lstrip().startswith("#")]


def worth_writing(before, after, floor=DEFAULT_FLOOR):
    """Whether a rewrite clears the churn floor."""
    if before is None:
        return True, "new file"
    if before == after:
        return False, "identical"

    _, old_body, _ = docs_meta.parse(before)
    _, new_body, _ = docs_meta.parse(after)
    if normalize(old_body) == normalize(new_body):
        return False, "frontmatter only"
    if structural_change(old_body, new_body):
        return True, "section structure changed"

    added, removed = changed_lines(normalize(old_body), normalize(new_body))
    total = added + removed
    if total < floor:
        return False, f"prose churn below floor ({total} < {floor} lines)"
    return True, f"{added} added, {removed} removed"


# ----------------------------------------------------------------------- cli


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render writer JSON to Markdown")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("document", help="Render one writer output file")
    p.add_argument("input", help="Writer output JSON, or - for stdin")
    p.add_argument("--out", help="Write here instead of stdout")
    p.add_argument(
        "--floor",
        type=int,
        default=DEFAULT_FLOOR,
        help="Churn floor in changed lines. 0 disables",
    )

    p = sub.add_parser("diff", help="Report whether a rewrite clears the floor")
    p.add_argument("before")
    p.add_argument("after")
    p.add_argument("--floor", type=int, default=DEFAULT_FLOOR)

    args = parser.parse_args(argv)

    if args.command == "diff":
        before = Path(args.before).read_text() if Path(args.before).exists() else None
        after = Path(args.after).read_text()
        write, reason = worth_writing(before, after, args.floor)
        print(json.dumps({"write": write, "reason": reason}, indent=2))
        return 0

    try:
        raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"render: cannot read input: {exc}", file=sys.stderr)
        return 2

    text = document(payload)
    target = args.out or payload.get("path")
    if not args.out and not target:
        sys.stdout.write(text)
        return 0

    destination = Path(target)
    existing = destination.read_text() if destination.exists() else None
    write, reason = worth_writing(existing, text, args.floor)
    if not write:
        print(f"render: {destination} unchanged ({reason})", file=sys.stderr)
        return 0

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text)
    print(f"render: wrote {destination} ({reason})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

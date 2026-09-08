#!/usr/bin/env python3
"""Fenced regions: within-file ownership for `managed: assisted` documents.

A document a human owns can still carry generated sections, marked off like
this:

    <!-- docs-gen:begin section=api source=pkg/scheduler sha=a1b2c3d -->
    ...generated body...
    <!-- docs-gen:end -->

`replace` rewrites the inside of a named region and guarantees every byte
outside it survives unchanged. That guarantee lives here, in a script, rather
than in a prompt. A model cannot be argued past a function that never receives
the surrounding text.

    from lib.md import fences
    regions = fences.parse(text)                       # what exists, and where
    text = fences.replace(text, "api", body, sha=head) # rewrite one region
    fences.outside(text) == fences.outside(original)   # the invariant
"""

import argparse
import json
import re
import sys
from pathlib import Path

BEGIN = re.compile(
    r"^(?P<indent>[ \t]*)<!--[ \t]*docs-gen:begin(?P<attrs>[^>]*?)-->[ \t]*$",
    re.MULTILINE,
)
END = re.compile(r"^[ \t]*<!--[ \t]*docs-gen:end[ \t]*-->[ \t]*$", re.MULTILINE)
ATTR = re.compile(r"(?P<key>[a-zA-Z_][a-zA-Z0-9_-]*)=(?P<value>\"[^\"]*\"|\S+)")


class FenceError(RuntimeError):
    """Unbalanced markers, a duplicate section id, or an unknown section."""


class Region:
    """One fenced region: its attributes, its body, and its byte offsets."""

    def __init__(self, attrs, body, start, end, marker_start, body_start, body_end, indent):
        self.attrs = attrs
        self.body = body
        self.start = start
        self.end = end
        self.marker_start = marker_start
        self.body_start = body_start
        self.body_end = body_end
        self.indent = indent

    @property
    def section(self):
        return self.attrs.get("section")

    @property
    def source(self):
        return self.attrs.get("source")

    @property
    def sha(self):
        return self.attrs.get("sha")

    def as_dict(self):
        return {
            "section": self.section,
            "source": self.source,
            "sha": self.sha,
            "attrs": self.attrs,
            "lines": [self.start, self.end],
            "body_length": len(self.body),
        }

    def __repr__(self):
        return f"<Region {self.section!r} source={self.source!r} sha={self.sha!r}>"


# ------------------------------------------------------------------- parsing


def parse_attrs(text):
    """Read `key=value` pairs off a begin marker. Quoted values may hold spaces."""
    attrs = {}
    for match in ATTR.finditer(text):
        value = match.group("value")
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        attrs[match.group("key")] = value
    return attrs


def parse(text):
    """Every fenced region in document order.

    Raises FenceError on a begin without an end, an end without a begin, a
    nested begin, or two regions claiming the same section id. All four mean
    the file cannot be rewritten safely, so failing here is the point.
    """
    events = []
    for match in BEGIN.finditer(text):
        events.append(("begin", match))
    for match in END.finditer(text):
        events.append(("end", match))
    events.sort(key=lambda item: item[1].start())

    regions = []
    open_match = None
    for kind, match in events:
        if kind == "begin":
            if open_match is not None:
                raise FenceError(
                    f"nested docs-gen:begin at line {_line(text, match.start())}; "
                    f"the region opened at line {_line(text, open_match.start())} "
                    "is still open"
                )
            open_match = match
            continue
        if open_match is None:
            raise FenceError(f"docs-gen:end at line {_line(text, match.start())} with no begin")
        body_start = open_match.end() + 1
        body_end = match.start()
        regions.append(
            Region(
                attrs=parse_attrs(open_match.group("attrs")),
                body=text[body_start:body_end],
                start=_line(text, open_match.start()),
                end=_line(text, match.start()),
                marker_start=open_match.start(),
                body_start=body_start,
                body_end=body_end,
                indent=open_match.group("indent"),
            )
        )
        open_match = None

    if open_match is not None:
        raise FenceError(
            f"docs-gen:begin at line {_line(text, open_match.start())} is never closed"
        )

    seen = set()
    for region in regions:
        if region.section is None:
            raise FenceError(f"region at line {region.start} has no section attribute")
        if region.section in seen:
            raise FenceError(f"two regions claim section {region.section!r}")
        seen.add(region.section)
    return regions


def _line(text, offset):
    return text.count("\n", 0, offset) + 1


def find(text, section):
    for region in parse(text):
        if region.section == section:
            return region
    return None


def outside(text):
    """Everything a generated write may not touch, with each region collapsed.

    The span from the begin marker through the body counts as inside, because
    a writer stamps a fresh `sha` onto the marker as part of a legitimate
    rewrite. The section id survives into the placeholder, so renaming a
    region still shows up as a change. Everything else, the end marker
    included, has to come back byte for byte.

    Comparing this before and after a write proves nothing outside the fences
    moved. `replace` asserts it on every call.
    """
    regions = parse(text)
    if not regions:
        return text
    parts = []
    cursor = 0
    for region in regions:
        parts.append(text[cursor : region.marker_start])
        parts.append(f"\x00docs-gen:{region.section}\x00")
        cursor = region.body_end
    parts.append(text[cursor:])
    return "".join(parts)


# ------------------------------------------------------------------ rewriting


def render_marker(attrs, indent=""):
    """Serialize a begin marker with a fixed attribute order.

    Section, then source, then sha, then anything else alphabetically. Fixed
    order is what stops a rewrite from producing a diff on attribute shuffling
    alone.
    """
    order = [key for key in ("section", "source", "sha") if key in attrs]
    order += sorted(key for key in attrs if key not in ("section", "source", "sha"))
    rendered = " ".join(f"{key}={_quote(attrs[key])}" for key in order)
    return f"{indent}<!-- docs-gen:begin {rendered} -->"


def _quote(value):
    text = str(value)
    return f'"{text}"' if (not text or re.search(r"\s", text)) else text


def replace(text, section, body, **attrs):
    """Rewrite one region's body, leaving every byte outside it alone.

    Attributes passed here are merged over the existing ones, which is how a
    writer stamps a fresh `sha`. Returns the new text. Raises FenceError when
    the section is absent, so a caller cannot silently write nothing.
    """
    region = find(text, section)
    if region is None:
        raise FenceError(f"no region with section={section!r}")

    merged = dict(region.attrs)
    merged.update({key: value for key, value in attrs.items() if value is not None})

    body = body.rstrip("\n")
    marker = render_marker(merged, region.indent)
    head = text[: region.marker_start] + marker + "\n"
    result = head + (body + "\n" if body else "") + text[region.body_end :]
    _assert_outside_unchanged(text, result, section)
    return result


def _assert_outside_unchanged(before_text, after_text, section):
    """Guard the ownership contract rather than trusting the arithmetic above."""
    try:
        before = outside(before_text)
        after = outside(after_text)
    except FenceError as exc:
        raise FenceError(f"rewrite of {section!r} broke the fence structure: {exc}")
    if before != after:
        raise FenceError(f"rewrite of {section!r} would change bytes outside its region; refusing")


def stale(text, current_sha, sections=None):
    """Regions whose recorded sha is missing or behind the current one."""
    out = []
    for region in parse(text):
        if sections is not None and region.section not in sections:
            continue
        if not region.sha or not current_sha.startswith(region.sha):
            out.append(region)
    return out


# ----------------------------------------------------------------------- cli


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect docs-gen fenced regions")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="Regions in a file, as JSON")
    p.add_argument("file")

    p = sub.add_parser("check", help="Validate fence structure. Exit 3 on error")
    p.add_argument("file", nargs="+")

    p = sub.add_parser("replace", help="Rewrite one region's body from stdin")
    p.add_argument("file")
    p.add_argument("--section", required=True)
    p.add_argument("--sha")
    p.add_argument("--source")
    p.add_argument("--write", action="store_true", help="Edit in place")

    args = parser.parse_args(argv)

    if args.command == "check":
        failures = 0
        for name in args.file:
            try:
                regions = parse(Path(name).read_text())
            except (FenceError, OSError) as exc:
                failures += 1
                print(f"FAIL  {name}: {exc}", file=sys.stderr)
            else:
                print(f"ok    {name} ({len(regions)} region(s))")
        return 3 if failures else 0

    try:
        text = Path(args.file).read_text()
        if args.command == "list":
            print(json.dumps([r.as_dict() for r in parse(text)], indent=2))
            return 0
        result = replace(text, args.section, sys.stdin.read(), sha=args.sha, source=args.source)
    except (FenceError, OSError) as exc:
        print(f"fences: {exc}", file=sys.stderr)
        return 3

    if args.write:
        Path(args.file).write_text(result)
        print(f"fences: rewrote {args.section} in {args.file}", file=sys.stderr)
    else:
        sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())

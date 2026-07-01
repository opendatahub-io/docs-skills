#!/usr/bin/env python3
"""Build the per-module writing decision and module map for docs-workflow-writing.

Parses the plan.md to enumerate discrete documentation modules,
derives a compact module map (deterministic anchors + output paths), and decides
whether the writing step should use the per-module subagent strategy or the
default single-writer strategy.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# Module sections in the JTBD plan template whose top-level bullets enumerate
# discrete modules. "New Docs" entries look like "* Title (Type)"; "Updated
# Docs" entries look like "* existing-filename.adoc".
_MODULE_SECTIONS = ("new docs", "updated docs")

_TYPE_CANON = {
    "concept": "concept",
    "procedure": "procedure",
    "reference": "reference",
}

# Filename-prefix → canonical type, used when an Updated Docs entry is a bare
# filename with a modular-docs prefix.
_PREFIX_TYPE = {
    "con": "concept",
    "proc": "procedure",
    "ref": "reference",
    "assembly": "concept",
}


def slugify(text: str) -> str:
    """Lowercase, drop a trailing doc extension, hyphenate non-alphanumerics."""
    text = re.sub(r"\.(adoc|md)$", "", text.strip(), flags=re.IGNORECASE)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _canon_type(raw: str | None, title: str) -> str:
    """Resolve a canonical module type from a parenthetical label or filename prefix."""
    if raw:
        key = raw.strip().lower()
        if key in _TYPE_CANON:
            return _TYPE_CANON[key]
    prefix = title.split("-", 1)[0].split("_", 1)[0].lower()
    if prefix in _PREFIX_TYPE:
        return _PREFIX_TYPE[prefix]
    return "concept"


def parse_modules(plan_text: str) -> list[dict]:
    """Extract module entries from the New Docs / Updated Docs sections.

    Returns one dict per module with keys: id, anchor, title, type, scope.
    Output paths are added later by ``build_map`` (they depend on format/dir).
    """
    modules: list[dict] = []
    in_section = False
    pending: dict | None = None

    bullet_re = re.compile(r"^[*\-]\s+(.*)$")
    title_type_re = re.compile(r"^(?P<title>.*?)\s*\((?P<type>[^)]+)\)\s*$")

    def flush(p: dict | None) -> None:
        if p is not None:
            modules.append(p)

    for raw_line in plan_text.splitlines():
        line = raw_line.rstrip()
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading:
            flush(pending)
            pending = None
            in_section = heading.group(1).strip().lower() in _MODULE_SECTIONS
            continue
        if not in_section:
            continue

        bullet = bullet_re.match(line)
        if bullet:
            flush(pending)
            content = bullet.group(1).strip()
            m = title_type_re.match(content)
            if m:
                title = m.group("title").strip()
                raw_type = m.group("type")
            else:
                title = content
                raw_type = None
            if not title:
                pending = None
                continue
            pending = {
                "id": slugify(title),
                "anchor": slugify(title),
                "title": title,
                "type": _canon_type(raw_type, title),
                "scope": "",
            }
            continue

        # Indented continuation line = the one-line scope for the pending module.
        if pending is not None and line.strip() and (raw_line[:1] in (" ", "\t")):
            if not pending["scope"]:
                pending["scope"] = line.strip()

    flush(pending)
    # Drop entries that slugged to nothing (defensive).
    return [m for m in modules if m["id"]]


def decide(
    modules: list[dict], module_count: int, threshold: int, mode: str
) -> tuple[str, str | None]:
    """Choose the writer strategy. Returns (strategy, fallback_reason)."""
    if mode == "fix":
        return "single", "fix_mode"
    if module_count <= threshold:
        return "single", "below_threshold"
    if not modules:
        return "single", "no_module_ids"
    return "per_module", None


def _read_module_count(planning_result_path: str | None, parsed_len: int) -> int:
    """module_count from planning's sidecar, falling back to the parsed count."""
    if planning_result_path:
        try:
            with open(planning_result_path, encoding="utf-8") as fh:
                data = json.load(fh)
            value = data.get("module_count")
            if isinstance(value, int):
                return value
        except (OSError, ValueError):
            pass
    return parsed_len


def _output_file(output_dir: str, anchor: str, fmt: str) -> str:
    if fmt == "mkdocs":
        return f"{output_dir.rstrip('/')}/docs/{anchor}.md"
    return f"{output_dir.rstrip('/')}/modules/{anchor}.adoc"


def build_map(
    plan_path: str,
    planning_result_path: str | None,
    output_dir: str,
    fmt: str,
    mode: str,
    threshold: int,
) -> dict:
    """Parse the plan, derive the module map, and decide the writer strategy."""
    try:
        with open(plan_path, encoding="utf-8") as fh:
            plan_text = fh.read()
    except OSError:
        plan_text = ""

    modules = parse_modules(plan_text)
    for m in modules:
        m["output_file"] = _output_file(output_dir, m["anchor"], fmt)

    module_count = _read_module_count(planning_result_path, len(modules))
    strategy, reason = decide(modules, module_count, threshold, mode)

    return {
        "writer_strategy": strategy,
        "module_count": module_count,
        "threshold": threshold,
        "fallback_reason": reason,
        "modules": modules if strategy == "per_module" else [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the per-module writing decision and module map."
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--planning-result", default=None)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--format", choices=["adoc", "mkdocs"], default="adoc")
    parser.add_argument(
        "--mode",
        choices=["update-in-place", "draft", "fix"],
        default="update-in-place",
    )
    parser.add_argument("--threshold", type=int, default=8)
    args = parser.parse_args(argv)

    result = build_map(
        plan_path=args.plan,
        planning_result_path=args.planning_result,
        output_dir=args.output_dir,
        fmt=args.format,
        mode=args.mode,
        threshold=args.threshold,
    )
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Check that platform-specific skills route to compatibility guidance."""

from __future__ import annotations

import argparse
from pathlib import Path

COMPATIBILITY_LINE = (
    "Codex: read [runtime compatibility](../../reference/runtime-compatibility.md)."
)
LEGACY_COMPATIBILITY_LINE = (
    "For Codex, read [runtime compatibility](../../reference/runtime-compatibility.md) "
    "before using platform-specific paths or subagents. Claude Code can follow the "
    "commands as written."
)
PLATFORM_MARKERS = ("CLAUDE_SKILL_DIR", "CLAUDE_PLUGIN_ROOT", "subagent_type", "Agent tool")
PLATFORM_MARKERS += ("AskUserQuestion", "Skill tool", "WebSearch", "WebFetch")


def needs_guidance(contents: str) -> bool:
    return any(marker in contents for marker in PLATFORM_MARKERS)


def add_guidance(contents: str) -> str:
    if COMPATIBILITY_LINE in contents or not needs_guidance(contents):
        return contents
    if LEGACY_COMPATIBILITY_LINE in contents:
        return contents.replace(LEGACY_COMPATIBILITY_LINE, COMPATIBILITY_LINE)
    frontmatter_end = contents.find("\n---\n", 4)
    if frontmatter_end == -1:
        raise ValueError("SKILL.md has no closing frontmatter delimiter")
    heading_start = contents.find("\n# ", frontmatter_end + 5)
    if heading_start == -1:
        raise ValueError("SKILL.md has no level-one heading")
    heading_end = contents.find("\n", heading_start + 1)
    if heading_end == -1:
        heading_end = len(contents)
    return contents[: heading_end + 1] + f"\n{COMPATIBILITY_LINE}\n" + contents[heading_end + 1 :]


def process(skills_root: Path, *, fix: bool) -> list[Path]:
    missing: list[Path] = []
    for skill_path in sorted(skills_root.glob("*/SKILL.md")):
        contents = skill_path.read_text(encoding="utf-8")
        if not needs_guidance(contents) or COMPATIBILITY_LINE in contents:
            continue
        missing.append(skill_path)
        if fix:
            skill_path.write_text(add_guidance(contents), encoding="utf-8")
    return missing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Insert missing guidance.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    missing = process(repo_root / "skills", fix=args.fix)
    if missing and not args.fix:
        rendered = "\n".join(f"- {path.relative_to(repo_root)}" for path in missing)
        raise SystemExit(f"Skills missing runtime compatibility guidance:\n{rendered}")
    if missing:
        print(f"Updated {len(missing)} skill files.")
    else:
        print("Runtime compatibility guidance is current.")


if __name__ == "__main__":
    main()

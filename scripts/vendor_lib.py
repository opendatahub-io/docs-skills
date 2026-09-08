#!/usr/bin/env python3
"""Copy the shared trees into each generator skill, for a standalone install.

A skill installer copies one skill directory to a harness-specific location and
drops symlinks with a warning on the way, so a shared `lib/` at the repository
root cannot be linked in and does not survive the copy. Vendoring is the answer
that costs nothing at runtime: each skill's scripts walk up from `__file__` and
find the vendored copy before they would find the repository root.

    python3 scripts/vendor_lib.py            # write the copies
    python3 scripts/vendor_lib.py --check    # fail if any copy has drifted

`--check` is what CI runs. A vendored copy that has fallen behind its source is
a silent bug, because the skill keeps working from the repository root during
development and breaks only once installed.
"""

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Skills whose scripts import from the shared trees.
SKILLS = ["repo-analyze", "docs-write", "docs-review", "docs-sync", "changelog"]

# What each vendored copy needs. `lib` is the import root the walk looks for.
TREES = ["lib", "prompts", "schemas", "languages", "config"]

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def targets():
    for skill in SKILLS:
        base = ROOT / "skills" / skill / "scripts"
        if base.is_dir():
            yield skill, base


def vendor(base):
    for tree in TREES:
        source = ROOT / tree
        if not source.is_dir():
            continue
        destination = base / tree
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, ignore=IGNORE)


def drifted(base):
    """Files that differ between a vendored copy and its source."""
    out = []
    for tree in TREES:
        source = ROOT / tree
        destination = base / tree
        if not source.is_dir():
            continue
        if not destination.is_dir():
            out.append(f"{destination.relative_to(ROOT)} is missing")
            continue
        for path in sorted(source.rglob("*")):
            if path.is_dir() or "__pycache__" in path.parts:
                continue
            mirror = destination / path.relative_to(source)
            if not mirror.exists():
                out.append(f"{mirror.relative_to(ROOT)} is missing")
            elif not filecmp.cmp(path, mirror, shallow=False):
                out.append(f"{mirror.relative_to(ROOT)} differs from {tree}/")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Vendor shared trees into skills")
    parser.add_argument(
        "--check", action="store_true", help="Report drift and exit 1. Writes nothing"
    )
    parser.add_argument("--clean", action="store_true", help="Remove every vendored copy")
    args = parser.parse_args(argv)

    if args.clean:
        for skill, base in targets():
            for tree in TREES:
                if (base / tree).exists():
                    shutil.rmtree(base / tree)
            print(f"cleaned {skill}")
        return 0

    if args.check:
        problems = []
        for skill, base in targets():
            problems += [f"{skill}: {item}" for item in drifted(base)]
        if problems:
            for item in problems[:40]:
                print(f"drift  {item}", file=sys.stderr)
            print(
                f"\n{len(problems)} vendored file(s) out of date. Run `make vendor`.",
                file=sys.stderr,
            )
            return 1
        print("vendored copies are current")
        return 0

    for skill, base in targets():
        vendor(base)
        print(f"vendored {', '.join(TREES)} into skills/{skill}/scripts/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Inventory the artifacts a workflow step has historically produced.

When prose instructions in a SKILL.md are replaced by a script, the script
inherits only the behaviour someone wrote down. Anything the prose runs did
incidentally — extra artifacts, retained intermediates — stops happening
silently, because no test covers a file nobody specified.

This script makes that visible. It walks every run of a step under the
workspace, takes the UNION of the paths those runs wrote (union, not one run:
prose output varies between runs), and optionally diffs that union against a
directory the scripted version produced. Paths in the historical set but not
the current one are what the conversion dropped.

Run-specific segments are normalized so paths from different runs collapse
together: digit runs become ``N`` (``iteration-1/`` and ``iteration-2/`` both
become ``iteration-N/``). Pass --no-normalize to compare raw paths.

This finds dropped *artifacts*. It cannot find dropped *decisions* — prose that
chose to re-read a file, reorder work, or batch differently leaves nothing on
disk to diff.

Usage:
  artifact_inventory.py --step technical-review
  artifact_inventory.py --step technical-review --current /path/to/new/output
  artifact_inventory.py --list-steps
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_WORKSPACE = ".agent_workspace"

# Collapse run-specific digits so paths from different runs compare equal.
_DIGITS = re.compile(r"\d+")


def normalize(rel_path, enabled=True):
    """Collapse digit runs in a relative path so runs compare equal."""
    return _DIGITS.sub("N", rel_path) if enabled else rel_path


def collect(step_dir, enabled=True):
    """Return the set of normalized relative paths under a step directory.

    Directories are recorded with a trailing slash so a dropped directory is
    distinguishable from a dropped file of the same name.
    """
    paths = set()
    for entry in step_dir.rglob("*"):
        rel = entry.relative_to(step_dir).as_posix()
        if entry.is_dir():
            rel += "/"
        paths.add(normalize(rel, enabled))
    return paths


def find_runs(workspace, step):
    """Yield (ticket, step_dir) for every run that has this step's output."""
    for ticket_dir in sorted(workspace.iterdir()):
        if not ticket_dir.is_dir():
            continue
        step_dir = ticket_dir / step
        if step_dir.is_dir():
            yield ticket_dir.name, step_dir


def list_steps(workspace):
    """Return step names seen across all runs, with run counts."""
    counts = Counter()
    for ticket_dir in workspace.iterdir():
        if not ticket_dir.is_dir():
            continue
        for child in ticket_dir.iterdir():
            if child.is_dir():
                counts[child.name] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", help="Step directory name, e.g. technical-review")
    parser.add_argument(
        "--workspace",
        default=DEFAULT_WORKSPACE,
        help=f"Workspace root (default {DEFAULT_WORKSPACE})",
    )
    parser.add_argument(
        "--current", help="Directory produced by the scripted version, to diff against history"
    )
    parser.add_argument(
        "--no-normalize", action="store_true", help="Compare raw paths without collapsing digits"
    )
    parser.add_argument("--list-steps", action="store_true", help="List step names found and exit")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    if not workspace.is_dir():
        print(f"ERROR: workspace not found: {workspace}", file=sys.stderr)
        return 1

    if args.list_steps:
        counts = list_steps(workspace)
        if args.json:
            json.dump(dict(counts.most_common()), sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            for name, n in counts.most_common():
                print(f"{n:4d}  {name}")
        return 0

    if not args.step:
        print("ERROR: --step is required (or use --list-steps)", file=sys.stderr)
        return 1

    normalize_on = not args.no_normalize
    runs = list(find_runs(workspace, args.step))
    if not runs:
        print(f"ERROR: no runs found for step '{args.step}' under {workspace}", file=sys.stderr)
        return 1

    # Count how many runs produced each path. A path seen in one run of ten is
    # more likely incidental than one seen in all ten — the reviewer needs that
    # signal to classify it.
    seen = Counter()
    for _, step_dir in runs:
        for path in collect(step_dir, normalize_on):
            seen[path] += 1

    current_paths = None
    dropped = None
    if args.current:
        current_dir = Path(args.current)
        if not current_dir.is_dir():
            print(f"ERROR: --current is not a directory: {current_dir}", file=sys.stderr)
            return 1
        current_paths = collect(current_dir, normalize_on)
        dropped = sorted(p for p in seen if p not in current_paths)

    if args.json:
        output = {
            "step": args.step,
            "run_count": len(runs),
            "runs": [t for t, _ in runs],
            "historical_paths": {p: seen[p] for p in sorted(seen)},
        }
        if dropped is not None:
            output["current_paths"] = sorted(current_paths)
            output["dropped_paths"] = dropped
        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"Step: {args.step}")
    print(f"Runs inspected: {len(runs)} ({', '.join(t for t, _ in runs)})")
    print()
    print(f"{'runs':>5}  path")
    for path in sorted(seen, key=lambda p: (-seen[p], p)):
        print(f"{seen[path]:5d}  {path}")

    if dropped is not None:
        print()
        if dropped:
            print(f"NOT produced by {args.current} ({len(dropped)}):")
            for path in dropped:
                print(f"  {path}   (seen in {seen[path]}/{len(runs)} runs)")
            print()
            print("Classify each in the PR: dead weight, feature to preserve,")
            print("or accident dropped on purpose.")
        else:
            print("Nothing dropped — the scripted version produces every historical path.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

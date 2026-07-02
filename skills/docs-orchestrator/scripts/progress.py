#!/usr/bin/env python3
"""Create and rewind the docs-orchestrator progress file.

Owns the stateful progress-file transitions that were previously executed by
hand in docs-orchestrator/SKILL.md:

  init   — build the progress skeleton from a validated step list.
  rewind — reset a completed step whose output folder vanished, and every step
           ordered after it, back to pending (clearing stale results).

Usage:
  progress.py init --base-path P --ticket T --workflow W --steps <steps.json> \
      [--options <options.json>] [--force]
  progress.py rewind --progress-file <progress.json>
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def progress_path_for(base_path: str, workflow: str, ticket: str) -> str:
    return os.path.join(base_path, "workflow", f"{workflow}_{ticket.lower()}.json")


def build_progress(
    ticket: str, workflow: str, base_path: str, steps: list[dict], options: dict
) -> dict:
    """Build the progress skeleton from a validated step list (load_workflow output)."""
    now = _now()
    step_order = [s["name"] for s in steps]
    steps_map = {
        s["name"]: {"status": s.get("status", "pending"), "output": None, "result": None}
        for s in steps
    }
    return {
        "workflow": workflow,
        "ticket": ticket,
        "base_path": base_path,
        "status": "in_progress",
        "created_at": now,
        "updated_at": now,
        "options": options or {},
        "step_order": step_order,
        "steps": steps_map,
        "workarounds": [],
    }


def rewind_progress(progress: dict, base_path: str) -> dict:
    """Reset the first completed step whose output is missing, plus all downstream
    completed steps, back to pending. Mutates ``progress`` in place; returns a summary.

    Downstream is positional (every step ordered after the stale one). Only
    ``completed`` steps are reset — ``skipped``/``deferred``/``pending`` are left
    as-is so conditional steps keep their classification.
    """
    step_order = progress.get("step_order", [])
    steps = progress.get("steps", {})

    stale_index = None
    for i, name in enumerate(step_order):
        info = steps.get(name, {})
        if info.get("status") != "completed":
            continue
        if not os.path.isdir(os.path.join(base_path, name)):
            stale_index = i
            break

    reset_steps = []
    if stale_index is not None:
        for name in step_order[stale_index:]:
            info = steps.get(name, {})
            # always reset the stale step itself; downstream only if completed
            if name == step_order[stale_index] or info.get("status") == "completed":
                info["status"] = "pending"
                info["output"] = None
                info["result"] = None
                reset_steps.append(name)
        progress["updated_at"] = _now()

    return {
        "rewound_from": step_order[stale_index] if stale_index is not None else None,
        "reset_steps": reset_steps,
    }


def _cmd_init(args) -> int:
    try:
        with open(args.steps) as f:
            steps = json.load(f).get("steps", [])
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read steps file {args.steps}: {e}", file=sys.stderr)
        return 1

    options = {}
    if args.options:
        try:
            with open(args.options) as f:
                options = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"ERROR: cannot read options file {args.options}: {e}", file=sys.stderr)
            return 1

    base_path = os.path.abspath(args.base_path)
    path = progress_path_for(base_path, args.workflow, args.ticket)
    if os.path.isfile(path) and not args.force:
        print(
            f"ERROR: progress file already exists: {path} (use --force to overwrite)",
            file=sys.stderr,
        )
        return 1

    progress = build_progress(args.ticket, args.workflow, base_path, steps, options)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(progress, f, indent=2)
    print(path)
    return 0


def _cmd_rewind(args) -> int:
    try:
        with open(args.progress_file) as f:
            progress = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read progress file {args.progress_file}: {e}", file=sys.stderr)
        return 1

    base_path = progress.get("base_path") or os.path.dirname(
        os.path.dirname(os.path.abspath(args.progress_file))
    )
    summary = rewind_progress(progress, base_path)
    with open(args.progress_file, "w") as f:
        json.dump(progress, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--base-path", required=True)
    init.add_argument("--ticket", required=True)
    init.add_argument("--workflow", required=True)
    init.add_argument("--steps", required=True, help="Path to load_workflow JSON output")
    init.add_argument("--options", help="Path to a JSON options file")
    init.add_argument("--force", action="store_true")

    rewind = sub.add_parser("rewind")
    rewind.add_argument("--progress-file", required=True)

    args = parser.parse_args()
    if args.command == "init":
        return _cmd_init(args)
    return _cmd_rewind(args)


if __name__ == "__main__":
    sys.exit(main())

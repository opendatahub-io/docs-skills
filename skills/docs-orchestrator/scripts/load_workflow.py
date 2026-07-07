#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pyyaml",
# ]
# ///
"""Load, classify, and validate a docs-orchestrator workflow step list.

Replaces the inline "Load the step list" procedure in docs-orchestrator/SKILL.md.
Resolves the workflow YAML (project override → plugin default), evaluates the
deterministic `when` conditions against the run options, validates the step list,
and emits a validated step list as JSON for `progress.py init` to consume.

Usage:
  load_workflow.py --workflow <name> --plugin-root <root> --options <options.json> \
      [--base-path <path>] [--output <path>]
"""

import argparse
import json
import os
import sys


class WorkflowError(Exception):
    """A workflow could not be resolved, parsed, or validated."""


def resolve_yaml_path(workflow_name: str, plugin_root: str, base_path: str | None) -> str | None:
    """Resolve the workflow YAML: project override first, then the plugin default.

    Project override lives next to the workspace (``<base_path>/../docs-<name>.yaml``,
    i.e. ``.agent_workspace/docs-<name>.yaml``); the fallback is the bundled
    ``skills/docs-orchestrator/defaults/docs-<name>.yaml``.
    """
    filename = f"docs-{workflow_name}.yaml"

    if base_path:
        project = os.path.join(os.path.dirname(os.path.abspath(base_path)), filename)
        if os.path.isfile(project):
            return project

    default = os.path.join(plugin_root, "skills", "docs-orchestrator", "defaults", filename)
    if os.path.isfile(default):
        return default

    return None


def evaluate_when(when: str | None, options: dict) -> str:
    """Map a step's `when` condition + run options to an initial status.

    Deterministic conditions resolve now; `has_many_requirements` and an
    unresolved `has_source_repo` defer until after the requirements step.
    """
    if not when:
        return "pending"
    if when == "create_merge_request":
        return "pending" if options.get("create_merge_request") else "skipped"
    if when == "has_pr":
        has_pr = bool(options.get("pr_urls")) or bool(options.get("has_pr"))
        return "pending" if has_pr else "skipped"
    if when == "has_source_repo":
        if options.get("no_source_repo"):
            return "skipped"
        if options.get("has_source_repo"):
            return "pending"
        return "deferred"
    if when == "has_many_requirements":
        return "deferred"
    # Unknown condition: fail open to pending rather than silently skipping.
    return "pending"


def _skill_dir_name(skill_ref: str) -> str:
    """Strip an optional `plugin:` prefix from a skill reference."""
    return skill_ref.split(":", 1)[1] if ":" in skill_ref else skill_ref


def validate_steps(steps: list[dict], plugin_root: str) -> list[str]:
    """Return a list of validation errors (empty when the step list is valid)."""
    errors = []
    names = [s.get("name") for s in steps]

    seen = set()
    for n in names:
        if n in seen:
            errors.append(f"Duplicate step name: '{n}' — step names must be unique")
        seen.add(n)

    name_set = set(names)
    for s in steps:
        skill = s.get("skill", "")
        skill_dir = os.path.join(plugin_root, "skills", _skill_dir_name(skill))
        if not os.path.isdir(skill_dir):
            errors.append(f"Step '{s.get('name')}' references unknown skill: '{skill}'")
        for dep in s.get("inputs", []) or []:
            if dep not in name_set:
                errors.append(f"Step '{s.get('name')}' input '{dep}' is not a step in the workflow")

    return errors


def load(workflow_name: str, plugin_root: str, options: dict, base_path: str | None = None) -> dict:
    """Resolve, parse, classify, and validate a workflow. Raises WorkflowError on failure."""
    import yaml  # deferred so pure helpers import without the YAML dependency

    yaml_path = resolve_yaml_path(workflow_name, plugin_root, base_path)
    if yaml_path is None:
        raise WorkflowError(f"No workflow YAML found for '{workflow_name}'")

    try:
        with open(yaml_path) as f:
            doc = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as e:
        raise WorkflowError(f"Cannot parse workflow YAML {yaml_path}: {e}") from e

    raw_steps = ((doc.get("workflow") or {}).get("steps")) or []
    steps = []
    for s in raw_steps:
        steps.append(
            {
                "name": s.get("name"),
                "skill": s.get("skill"),
                "description": s.get("description"),
                "when": s.get("when"),
                "inputs": s.get("inputs", []) or [],
                "status": evaluate_when(s.get("when"), options),
            }
        )

    errors = validate_steps(steps, plugin_root)
    if errors:
        raise WorkflowError("Invalid workflow step list:\n  - " + "\n  - ".join(errors))

    return {"workflow": workflow_name, "yaml_path": yaml_path, "steps": steps}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", default="workflow")
    parser.add_argument("--plugin-root", required=True)
    parser.add_argument("--options", required=True, help="Path to a JSON options file")
    parser.add_argument("--base-path")
    parser.add_argument("--output", help="Write JSON to file instead of stdout")
    args = parser.parse_args()

    try:
        with open(args.options) as f:
            options = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read options file {args.options}: {e}", file=sys.stderr)
        return 1

    try:
        result = load(args.workflow, args.plugin_root, options, args.base_path)
    except WorkflowError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    payload = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w") as f:
            f.write(payload + "\n")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())

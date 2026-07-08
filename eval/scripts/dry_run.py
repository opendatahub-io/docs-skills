#!/usr/bin/env python3
"""Dry-run validator for eval harness configs.

Validates config loading, judge resolution, and dataset wiring without
executing the pipeline. Exit 0 = all checks pass; exit 1 = failures found.

Usage:
    python3 eval/scripts/dry_run.py eval/eval.yaml [--cases case-001 case-002]

Requires PYTHONPATH to include the agent-eval-harness package, e.g.:
    PYTHONPATH=/path/to/agent-eval-harness python3 eval/scripts/dry_run.py eval/eval.yaml
"""

import argparse
import importlib
import sys
from pathlib import Path


def _load_config(config_path: str):
    from agent_eval.config import EvalConfig

    return EvalConfig.from_yaml(config_path)


def _check_dataset(config, project_root: Path, case_filter: list[str]):
    errors = []
    dataset_path = Path(config.dataset.path)
    if not dataset_path.is_absolute():
        dataset_path = project_root / dataset_path

    if not dataset_path.is_dir():
        errors.append(f"Dataset path not found: {dataset_path}")
        return [], errors

    cases = sorted(
        d.name
        for d in dataset_path.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name != "TEMPLATE"
    )

    if not cases:
        errors.append(f"No case directories in {dataset_path}")
        return cases, errors

    if case_filter:
        missing = [c for c in case_filter if c not in cases]
        if missing:
            errors.append(f"Case IDs not found: {', '.join(missing)}")

    return cases, errors


def _check_arguments_template(config, project_root: Path, cases: list[str]):
    errors = []
    template = getattr(config.execution, "arguments", "")
    if not template:
        return errors

    dataset_path = Path(config.dataset.path)
    if not dataset_path.is_absolute():
        dataset_path = project_root / dataset_path

    import re

    import yaml

    placeholders = re.findall(r"\{([^}?]+)\??}", template)

    warnings = []
    for case_id in cases[:3]:
        input_file = dataset_path / case_id / "input.yaml"
        if not input_file.exists():
            errors.append(f"{case_id}: missing input.yaml")
            continue

        with open(input_file) as f:
            data = yaml.safe_load(f) or {}

        missing = [p for p in placeholders if p not in data]
        if missing:
            warnings.append(
                f"{case_id}: input.yaml missing template fields "
                f"(may be injected at runtime): {', '.join(missing)}"
            )

    return errors, warnings


def _check_judges(config, project_root: Path):
    errors = []
    warnings = []

    names_seen = set()
    for jc in config.judges:
        if jc.name in names_seen:
            errors.append(f"Judge '{jc.name}': duplicate name")
        names_seen.add(jc.name)

        judge_type = _classify_judge(jc)

        if judge_type == "builtin":
            _check_builtin(jc, errors)
        elif judge_type == "check":
            _check_inline(jc, errors)
        elif judge_type == "prompt_file":
            _check_prompt_file(jc, project_root, errors)
        elif judge_type == "prompt":
            _check_prompt(jc, errors)
        elif judge_type == "module":
            _check_module(jc, project_root, errors)
        else:
            warnings.append(f"Judge '{jc.name}': no type detected (will be skipped)")

        if jc.condition:
            try:
                compile(jc.condition, f"<condition:{jc.name}>", "eval")
            except SyntaxError as e:
                errors.append(f"Judge '{jc.name}': condition syntax error: {e}")

    return errors, warnings


def _classify_judge(jc) -> str:
    if jc.builtin:
        return "builtin"
    if jc.check:
        return "check"
    if jc.prompt_file:
        return "prompt_file"
    if jc.prompt:
        return "prompt"
    if jc.module and jc.function:
        return "module"
    return "unknown"


def _check_builtin(jc, errors):
    try:
        from agent_eval.judges import BuiltinJudgeRegistry

        registry = BuiltinJudgeRegistry()
        registry.discover()
        registry.get(jc.builtin)
    except (ValueError, ImportError) as e:
        errors.append(f"Judge '{jc.name}': builtin '{jc.builtin}' — {e}")


def _check_inline(jc, errors):
    source = "def _check(outputs, arguments):\n"
    for line in jc.check.splitlines():
        source += f"    {line}\n"
    try:
        compile(source, f"<check:{jc.name}>", "exec")
    except SyntaxError as e:
        errors.append(f"Judge '{jc.name}': check syntax error: {e}")


def _check_prompt_file(jc, project_root, errors):
    path = project_root / jc.prompt_file
    if not path.exists():
        errors.append(f"Judge '{jc.name}': prompt_file not found: {jc.prompt_file}")


def _check_prompt(jc, errors):
    try:
        from jinja2 import Environment

        env = Environment()
        env.parse(jc.prompt)
    except Exception as e:
        errors.append(f"Judge '{jc.name}': prompt template parse error: {e}")


def _check_module(jc, project_root, errors):
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        mod = importlib.import_module(jc.module)
    except Exception as e:
        errors.append(f"Judge '{jc.name}': module '{jc.module}' import failed: {e}")
        return
    if not hasattr(mod, jc.function):
        errors.append(
            f"Judge '{jc.name}': function '{jc.function}' not found in {jc.module}"
        )


def main():
    parser = argparse.ArgumentParser(description="Dry-run eval config validation")
    parser.add_argument("config", help="Path to eval.yaml")
    parser.add_argument("--cases", nargs="*", default=[], help="Case IDs to validate")
    args = parser.parse_args()

    config_path = Path(args.config)
    project_root = config_path.resolve().parent
    while project_root != project_root.parent:
        if (project_root / ".git").exists():
            break
        project_root = project_root.parent

    all_errors = []
    all_warnings = []

    # 1. Config + judges load
    print(f"Config: {args.config}")
    try:
        config = _load_config(args.config)
    except Exception as e:
        print(f"  FAIL  config load: {e}")
        sys.exit(1)
    print(f"  OK    {len(config.judges)} judges parsed")

    # 2. Dataset
    cases, errors = _check_dataset(config, project_root, args.cases)
    all_errors.extend(errors)
    if cases:
        print(f"  OK    {len(cases)} cases in dataset")
    for e in errors:
        print(f"  FAIL  {e}")

    # 3. Arguments template
    check_cases = args.cases if args.cases else cases
    errors, warnings = _check_arguments_template(config, project_root, check_cases)
    all_errors.extend(errors)
    all_warnings.extend(warnings)
    if not errors and not warnings:
        template = getattr(config.execution, "arguments", "")
        if template:
            print("  OK    arguments template resolves")
    for e in errors:
        print(f"  FAIL  {e}")
    for w in warnings:
        print(f"  WARN  {w}")

    # 4. Judges
    errors, warnings = _check_judges(config, project_root)
    all_errors.extend(errors)
    all_warnings.extend(warnings)

    judge_types = {}
    for jc in config.judges:
        t = _classify_judge(jc)
        judge_types.setdefault(t, []).append(jc.name)

    for t, names in sorted(judge_types.items()):
        failed = [n for n in names if any(f"'{n}'" in e for e in errors)]
        ok = [n for n in names if n not in failed]
        if ok:
            print(f"  OK    {t}: {', '.join(ok)}")
        for n in failed:
            for e in errors:
                if f"'{n}'" in e:
                    print(f"  FAIL  {e}")

    for w in warnings:
        print(f"  WARN  {w}")

    # Summary
    print()
    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
        if all_warnings:
            print(f"  ({len(all_warnings)} warning(s))")
        sys.exit(0)


if __name__ == "__main__":
    main()

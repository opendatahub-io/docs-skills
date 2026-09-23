#!/usr/bin/env python3
"""The Vale workspace a run lints against, and the linting of its own notes."""

from __future__ import annotations

import shutil
from pathlib import Path

from lib.vale import check, compose

VALE_DIR = "vale-run"
VALE_PACKAGES_DIR = "vale-packages"
TARGET_CONFIGS = (".vale.ini", "vale.ini", ".vale/config.ini")


def build(repo, out_dir, config, package_root, packages_dir=None):
    """A composed Vale config for this run, or None when prose checking is off.

    `out_dir` is one run's own directory and the workspace is rebuilt inside
    it. `packages_dir` is where `--sync-styles` put the downloaded packages,
    which is one directory shared by every run: re-downloading them per ticket
    would spend a network round trip on files that never differ, and the
    repository's own `.vale.ini` names that path once.
    """
    workspace = Path(out_dir) / VALE_DIR
    settings = config.get("vale") or {}
    target = next(
        (Path(repo) / name for name in TARGET_CONFIGS if (Path(repo) / name).is_file()), None
    )
    downloaded = Path(packages_dir) if packages_dir else Path(out_dir) / VALE_PACKAGES_DIR
    try:
        if workspace.exists():
            shutil.rmtree(workspace)
        built = compose.build(
            workspace,
            package_root,
            downloaded_styles=downloaded,
            target_config=target,
            budgets=settings.get("budgets"),
            base_styles=settings.get("base_styles"),
        )
    except (ValueError, OSError, compose.WorkspaceError) as exc:
        # Returned rather than logged: the caller owns its own output, and a
        # library that prints cannot be used from anything that does.
        return None, f"prose checking is off: {exc}"
    return str(built), ""


# --------------------------------------------------------------- loop guard


def artifact_files(root, keys=None):
    """Every existing file under `root` matching the chain's own artifact globs."""
    root = Path(root)
    wanted = set(keys) if keys is not None else set(compose.DEFAULT_BUDGETS)
    found = {}
    for key, glob, *_rest in compose.ARTIFACT_SECTIONS:
        if key not in wanted:
            continue
        matches = sorted(path for path in root.glob(glob.strip("[]")) if path.is_file())
        if matches:
            found[key] = matches
    return found


def lint_artifacts(root, vale_config, keys=None, files=None):
    """Alerts against the voices written for the chain's own artifacts.

    Returns `(alerts, reason)`. A non-empty reason means Vale could not be run
    and the alerts are not a verdict: an empty list from a linter that never
    started is indistinguishable from a clean pass, and the caller was reading
    it as one.
    """
    if not vale_config:
        return [], ""
    if files is not None:
        present = [Path(f) for f in files if Path(f).is_file()]
    else:
        present = [path for paths in artifact_files(root, keys=keys).values() for path in paths]
    if not present:
        return [], ""
    try:
        alerts = check.run(vale_config, present)
    except check.ValeError as exc:
        # Returned rather than logged, for the reason `build` gives above.
        return [], f"prose check skipped: {exc}"
    return alerts, ""

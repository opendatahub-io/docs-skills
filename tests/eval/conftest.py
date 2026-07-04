"""Shared test configuration for eval scripts."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (
    _ROOT / "eval" / "scripts",
    _ROOT / "skills" / "docs-workflow-pipeline-diagnostics" / "scripts",
):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

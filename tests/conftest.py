"""Shared test configuration.

Adds skill script directories to sys.path so tests can import modules
using the same bare imports they used when co-located with the scripts.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_DIRS = [
    _REPO_ROOT / "skills" / "docs-review-security" / "scripts",
    _REPO_ROOT / "skills" / "docs-workflow-pipeline-diagnostics" / "scripts",
    _REPO_ROOT / "skills" / "docs-workflow-requirements" / "scripts",
    _REPO_ROOT / "skills" / "docs-workflow-scope-req-audit" / "scripts",
    _REPO_ROOT / "skills" / "docs-workflow-writing" / "scripts",
    _REPO_ROOT / "skills" / "git-pr-reader" / "scripts",
]

for d in _SCRIPT_DIRS:
    s = str(d)
    if s not in sys.path:
        sys.path.insert(0, s)

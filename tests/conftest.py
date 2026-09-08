"""Shared test configuration.

Puts the docs-engine skill's `scripts/` on the path, which is the import root
for the generator's shared runtime. Each test module does the same for itself so
it can be run directly; this keeps a bare `pytest` run consistent with that.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE_SCRIPTS = _REPO_ROOT / "skills" / "docs-engine" / "scripts"

if str(_ENGINE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SCRIPTS))

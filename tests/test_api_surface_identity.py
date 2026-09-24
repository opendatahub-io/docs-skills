"""lib/git/api_surface.usable_modules: whether this run has a surface to ground on.

The cross-run identity check went with docs-sources: nothing records a
ticket or a repository list in a surface any more, because the analyzer
writes one per run from the repository in front of it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIB = REPO_ROOT / "skills" / "docs-engine" / "scripts"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from lib.git import api_surface  # noqa: E402


def write_json(path, data):
    path.write_text(json.dumps(data))


def test_no_surface_at_all_is_reported_as_such(tmp_path):
    surface, reason = api_surface.usable_modules(tmp_path)
    assert surface == {}
    assert reason


def test_a_surface_with_no_recorded_identity_is_trusted(tmp_path):
    """Built directly (`api_surface.py snapshot`, or a test fixture), not
    through docs-sources: it carries nothing to check, so it is used as-is."""
    write_json(tmp_path / "api-surface.json", {"schema": "api-surface/1", "modules": {"a": {}}})
    surface, reason = api_surface.usable_modules(tmp_path)
    assert surface["modules"] == {"a": {}}
    assert not reason

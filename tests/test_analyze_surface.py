"""docs-repo-analyze writes the API surface the rest of the chain grounds on.

`docs-sources` was the only thing that ever wrote `api-surface.json`, and it
went with the ticket reader. Both `docs-plan` and `docs-write` read it, and a
missing surface is silent: the writer simply grounds against nothing and every
backticked symbol reports as unverified.

So the analyzer writes it, from the per-module API files it has just extracted.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ANALYZE = _ROOT / "skills" / "docs-repo-analyze" / "scripts" / "analyze.py"
_ENGINE = _ROOT / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lib.git import api_surface  # noqa: E402


def _python_repo(tmp_path):
    pkg = tmp_path / "pkg" / "queue"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "queue.py").write_text(
        "def push(item):\n"
        '    """Add an item."""\n'
        "    return item\n"
        "\n"
        "\n"
        "def _private(item):\n"
        "    return item\n"
    )
    return tmp_path


def _analyze(repo, out):
    return subprocess.run(
        [sys.executable, str(_ANALYZE), "--repo", str(repo), "--out", str(out)],
        capture_output=True,
        text=True,
    )


def test_the_analyzer_writes_an_api_surface(tmp_path):
    repo = _python_repo(tmp_path / "repo")
    out = tmp_path / ".docs-gen"
    done = _analyze(repo, out)
    assert done.returncode == 0, done.stderr
    surface = out / "api-surface.json"
    assert surface.is_file(), f"no api-surface.json; stderr was:\n{done.stderr}"
    assert json.loads(surface.read_text())["modules"]


def test_the_surface_it_writes_is_usable_by_the_grounding_check(tmp_path):
    """`usable_modules` is what docs-write and docs-review read it through."""
    repo = _python_repo(tmp_path / "repo")
    out = tmp_path / ".docs-gen"
    assert _analyze(repo, out).returncode == 0
    modules, reason = api_surface.usable_modules(out)
    assert reason == ""
    assert modules.get("modules")


def test_a_public_symbol_reaches_the_surface_and_a_private_one_does_not(tmp_path):
    repo = _python_repo(tmp_path / "repo")
    out = tmp_path / ".docs-gen"
    assert _analyze(repo, out).returncode == 0
    surface = json.loads((out / "api-surface.json").read_text())
    names = {
        symbol for entry in surface["modules"].values() for symbol in (entry.get("symbols") or {})
    }
    assert any("push" in name for name in names), names
    assert not any("_private" in name for name in names), names

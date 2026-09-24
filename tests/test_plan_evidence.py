"""docs-plan: what a plan rests on, now that nothing is published to research.

The registry says which modules exist, the API surface says what they expose,
git context says what moved, and the docs tree says what is already written.

A repository yielding no modules has nothing to plan, and saying so is cheaper
and more honest than asking a model to invent deliverables from a topic phrase.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PLAN = _ROOT / "skills" / "docs-plan" / "scripts" / "plan.py"

sys.path.insert(0, str(_PLAN.parent))

import plan  # noqa: E402


def _run(out, repo=None, extra=()):
    argv = [sys.executable, str(_PLAN), "--out", str(out), "--llm-cmd", "false", *extra]
    if repo is not None:
        argv += ["--repo", str(repo)]
    return subprocess.run(argv, capture_output=True, text=True)


def test_an_empty_registry_plans_nothing_and_spends_no_call(tmp_path):
    out = tmp_path / ".docs-gen"
    out.mkdir()
    (out / "registry.json").write_text(json.dumps({"modules": {}, "module_count": 0}))
    done = _run(out, tmp_path)
    assert done.returncode == 1, done.stderr
    assert "no modules" in done.stderr.lower()


def test_a_missing_registry_is_a_configuration_error(tmp_path):
    out = tmp_path / ".docs-gen"
    out.mkdir()
    done = _run(out, tmp_path)
    assert done.returncode == 2, done.stderr
    assert "registry.json" in done.stderr


def test_the_existing_docs_inventory_reaches_the_planner(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "queue.md").write_text("---\nmanaged: generated\ntitle: Queue\n---\n\n# Queue\n")
    (docs / "held.md").write_text("---\nmanaged: manual\ntitle: Held\n---\n\n# Held\n")
    inventory = plan.docs_inventory(tmp_path, "docs")
    assert {entry["path"] for entry in inventory} == {"queue.md", "held.md"}
    by_path = {entry["path"]: entry for entry in inventory}
    assert by_path["queue.md"]["managed"] == "generated"
    assert by_path["held.md"]["managed"] == "manual"
    assert by_path["queue.md"]["title"] == "Queue"


def test_a_page_with_no_frontmatter_reads_as_manual(tmp_path):
    """The same default the writer applies: an unmarked file is a human's."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("# Notes\n\nHand-written.\n")
    assert plan.docs_inventory(tmp_path, "docs")[0]["managed"] == "manual"


def test_a_missing_docs_directory_is_an_empty_inventory(tmp_path):
    assert plan.docs_inventory(tmp_path, "docs") == []

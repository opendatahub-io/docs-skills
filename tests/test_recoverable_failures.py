"""One item failing must not end the step that was processing many.

`rhd` folds every unfetchable URL into one message: "Not a valid Red Hat
Documentation link (error 2001)". Measured against the live CLI, a guide that
does not exist, a product that does not exist, a knowledge base article and a
marketing page all answer with it. A product catalog lists cross-product links
and knowledge base articles beside its guides, and a search ranks pages that
have since been withdrawn, so one of these arrives in the course of an
ordinary run rather than an unusual one.

The line this file holds runs between an item that cannot be read and a tool
that cannot work. The first is skipped and reported. The second still stops
the step, because an expired token failing every call alike must never read as
"every page is missing".
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
_PLACE = REPO_ROOT / "skills" / "docs-place" / "scripts"
_RESEARCH = REPO_ROOT / "skills" / "docs-research" / "scripts"
_SOURCES = REPO_ROOT / "skills" / "docs-sources" / "scripts"
_WRITE = REPO_ROOT / "skills" / "docs-write" / "scripts"
for path in (_ENGINE, _PLACE, _RESEARCH, _SOURCES, _WRITE):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import write  # noqa: E402
from lib.md import docs_meta  # noqa: E402

# ------------------------------------------------------------------- the line


def test_one_deliverable_that_raises_does_not_discard_the_others(monkeypatch, tmp_path):
    """The documents beside it were drafted at model cost. The report already
    had a `failed` bucket that nothing could reach while the call raised."""
    out = tmp_path / ".docs-gen"
    out.mkdir()
    deliverables = [
        {"path": "boom.md", "type": "concept", "title": "Boom", "rationale": "r", "kind": "new"},
        {"path": "fine.md", "type": "concept", "title": "Fine", "rationale": "r", "kind": "new"},
    ]
    (out / "plan.json").write_text(json.dumps({"deliverables": deliverables}))

    def one_raises(repo, item, out_dir, *a, **k):
        if item["path"] == "boom.md":
            raise RuntimeError("the archetype file is missing")
        return {"deliverable": item["path"], "status": "written", "path": "docs/fine.md"}

    monkeypatch.setattr(write, "write_deliverable", one_raises)
    args = types.SimpleNamespace(
        llm_cmd="fake",
        timeout=10,
        floor=0,
        vale_config=None,
        vale_level="error",
        vale_attempts=1,
        repair_attempts=1,
        docs_dir="docs",
        plan=str(out / "plan.json"),
        changeset=str(tmp_path / "repo" / "docs" / "changeset-x"),
        changes=None,
        topic="t",
    )
    (tmp_path / "repo").mkdir()

    write.write_from_plan(tmp_path / "repo", out, args)

    report = json.loads((out / "write-report.json").read_text())
    assert [r["deliverable"] for r in report["written"]] == ["fine.md"]
    assert [r["deliverable"] for r in report["failed"]] == ["boom.md"]
    assert "archetype" in report["failed"][0]["reason"]


# ----------------------------------------------------------------- frontmatter


def test_invalid_frontmatter_yaml_arrives_as_this_module_s_own_error():
    """A `YAMLError` reaching a caller is a different exception for the same
    fact, and it escaped every guard written for malformed frontmatter."""
    with pytest.raises(docs_meta.MetaError):
        docs_meta.parse("---\ntitle: [unclosed\n---\n\nBody.\n")

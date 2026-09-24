"""docs-write: a foundation deliverable reaches the model with its own payload.

A foundation document is grounded in the slice its gate chose, never in the
symbol list a topic deliverable would carry. The stem travels into the
frontmatter so the sync step can map a changed module back to the documents
citing it.

A foundation deliverable's `path` is repo-relative and already contains the
docs directory, e.g. `docs/README.md`. That is unlike a topic `new` page,
whose bare kebab-case name is joined onto the changeset directory. Routing a
foundation item through that same join double-joins the docs directory (or,
with a changeset configured, nests it under the changeset's `new/` folder),
so it is tested directly here against the real seam (`write.run_plan`) rather
than against a helper that reimplements the join.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs-write" / "scripts"))

import write  # noqa: E402


def test_a_foundation_deliverable_builds_its_own_payload(tmp_path):
    out = tmp_path / ".docs-gen"
    (out / "modules").mkdir(parents=True)
    (out / "registry.json").write_text(
        json.dumps({"modules": {"pkg/a": {"kind": "library"}, "pkg/b": {"kind": "library"}}})
    )
    (out / "dep-pairs.json").write_text(json.dumps({"pairs": [{"from": "pkg/a", "to": "pkg/b"}]}))
    item = {
        "path": "docs/ARCHITECTURE.md",
        "type": "concept",
        "title": "Architecture",
        "rationale": "2 modules across 1 edge",
        "sources": ["pkg/a", "pkg/b"],
        "foundation": "architecture",
        "kind": "new",
    }
    payload = write.foundation_payload(item, tmp_path, out)
    assert payload["doc_type"] == "concept"
    assert payload["foundation"] == "architecture"
    assert payload["edges"] == [{"from": "pkg/a", "to": "pkg/b"}]
    assert "Architecture" in payload["archetype"] or "architecture" in payload["archetype"].lower()


def test_the_stem_lands_in_the_frontmatter_contract():
    assert write.foundation_frontmatter("architecture", ["pkg/a"]) == {
        "foundation": "architecture",
        "source_modules": ["pkg/a"],
    }


_STUB_REPLY = {
    "path": "docs/README.md",
    "frontmatter": {
        "title": "What this repository is",
        "description": "An overview a new reader can act on.",
        "type": "reference",
    },
    "sections": [
        {"id": "overview", "heading": "Overview", "body": "This repository holds a small library."}
    ],
    "evidence": [],
    "gaps": [],
}


def _stub_llm(tmp_path, name="stub_llm.py"):
    """A fake `--llm-cmd` that always returns the same valid write-out document."""
    script = tmp_path / name
    script.write_text(f"import sys, json\nsys.stdin.read()\nprint(json.dumps({_STUB_REPLY!r}))\n")
    return f"{sys.executable} {script}"


def test_a_foundation_document_writes_in_place_not_in_a_changeset(tmp_path):
    """A fixed destination, never a staged proposal.

    `docs/README.md` carries a separator, which the changeset path handling
    refuses for a `new` topic page for exactly that reason, and which the
    changeset directory would otherwise relocate. Getting this wrong puts all
    five foundation documents somewhere nobody looks -- and `docs_meta.stale`,
    which walks `docs_dir` for `source_modules`, would never see them again.
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    item = {
        "path": "docs/README.md",
        "type": "reference",
        "title": "What this repository is",
        "rationale": "the registry holds 2 module(s)",
        "sources": ["pkg/a"],
        "foundation": "readme",
        "kind": "new",
    }
    changeset_dir = repo / "docs" / "changeset-x"
    report = write.run_plan(
        repo,
        {"deliverables": [item]},
        docs_dir="docs",
        llm_cmd=_stub_llm(tmp_path),
        out=tmp_path / "out",
        changeset_dir=changeset_dir,
    )
    result = report["results"][0]
    assert result["status"] == "written", result

    target = repo / "docs" / "README.md"
    assert target.is_file()
    # Nowhere else: not double-joined under `docs/docs/`, and not staged
    # inside the changeset directory's `new/`.
    assert [p for p in repo.rglob("README.md")] == [target]
    assert not changeset_dir.exists() or not any(changeset_dir.rglob("*.md"))


def test_a_foundation_path_may_not_escape_the_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    item = {
        "path": "../../etc/passwd.md",
        "type": "reference",
        "title": "T",
        "rationale": "R",
        "sources": [],
        "foundation": "readme",
        "kind": "new",
    }
    report = write.run_plan(
        repo,
        {"deliverables": [item]},
        docs_dir="docs",
        llm_cmd=_stub_llm(tmp_path),
        out=tmp_path / "out",
        changeset_dir=None,
    )
    result = report["results"][0]
    assert result["status"] == "refused"
    assert "escape" in result["reason"]


def test_write_module_is_gone():
    assert not (_ROOT / "skills" / "docs-write" / "scripts" / "write_module.py").exists()
    assert not (_ROOT / "skills" / "docs-engine" / "prompts" / "write-module.md").exists()
    assert (
        "write_module" not in (_ROOT / "skills" / "docs-write" / "scripts" / "write.py").read_text()
    )

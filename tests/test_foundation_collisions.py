"""lib/foundation/gates: what an existing file does to a deliverable.

A page someone owns is not a target. A path differing only by case is one file
on macOS and two on Linux, so creating the second breaks the repository for
half the team whatever the local filesystem reports.

A first run has no docs tree at all, and the gates must survive that rather
than raising on a directory nobody created yet.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))

from lib.foundation import gates  # noqa: E402


def _artifacts(tmp_path, modules, edges=()):
    out = tmp_path / ".docs-gen"
    out.mkdir(parents=True)
    (out / "registry.json").write_text(json.dumps({"modules": modules}))
    (out / "dep-pairs.json").write_text(json.dumps({"pairs": list(edges)}))
    return out


def test_a_repository_with_no_docs_tree_still_gates(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {"kind": "library"}})
    written, skipped = gates.evaluate(tmp_path, out, "docs")
    assert written, "a first run has no docs tree and must still plan"
    assert all("gate" in entry for entry in skipped)


def test_a_manual_page_is_skipped_with_its_owner_named(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text(
        "---\ntitle: Architecture\nmanaged: manual\nowner: someone@example.com\n---\n\n# A\n"
    )
    out = _artifacts(
        tmp_path,
        {"pkg/a": {}, "pkg/b": {}, "pkg/c": {}},
        edges=[{"from": "pkg/a", "to": "pkg/b"}],
    )
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    entry = next(item for item in skipped if item["doc"].endswith("ARCHITECTURE.md"))
    assert entry["gate"] == "manual_page"
    assert "docs/ARCHITECTURE.md" in entry["reason"]


def test_a_path_differing_only_by_case_is_a_collision(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text("# Hand written\n")
    out = _artifacts(
        tmp_path,
        {"pkg/a": {}, "pkg/b": {}, "pkg/c": {}},
        edges=[{"from": "pkg/a", "to": "pkg/b"}],
    )
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    entry = next(item for item in skipped if item["doc"].endswith("ARCHITECTURE.md"))
    assert entry["gate"] == "path_collision"
    assert "differs only by case" in entry["reason"]


def test_two_modules_differing_only_by_case_are_both_kept(tmp_path):
    """The case-insensitive rule is about file paths, never about modules.

    Collapsing `pkg/Cache` and `pkg/cache` would drop a real module from every
    document's sources.
    """
    out = _artifacts(tmp_path, {"pkg/Cache": {"kind": "library"}, "pkg/cache": {"kind": "library"}})
    written, _ = gates.evaluate(tmp_path, out, "docs")
    readme = next(item for item in written if item["path"].endswith("README.md"))
    assert readme["sources"] == ["pkg/Cache", "pkg/cache"]


def test_a_page_marked_generated_is_not_a_collision(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("---\ntitle: R\nmanaged: generated\n---\n\n# R\n")
    out = _artifacts(tmp_path, {"pkg/a": {}})
    written, _ = gates.evaluate(tmp_path, out, "docs")
    assert any(item["path"].endswith("README.md") for item in written)


def test_a_file_with_no_frontmatter_is_treated_as_owned(tmp_path):
    """The behaviour this task changes.

    An unmarked file is somebody's. The writer's own default for one is
    `manual`, and the gate must reach the same answer rather than planning a
    deliverable that overwrites hand-written prose nobody stamped.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("# Hand written, no frontmatter\n")
    out = _artifacts(tmp_path, {"pkg/a": {}})
    written, skipped = gates.evaluate(tmp_path, out, "docs")
    assert not any(item["path"].endswith("README.md") for item in written)
    entry = next(item for item in skipped if item["doc"].endswith("README.md"))
    assert entry["gate"] == "manual_page"


def test_an_unparseable_page_is_treated_as_owned(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("---\n: : not: yaml: at all\n---\n\n# R\n")
    out = _artifacts(tmp_path, {"pkg/a": {}})
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    entry = next(item for item in skipped if item["doc"].endswith("README.md"))
    assert entry["gate"] == "manual_page"

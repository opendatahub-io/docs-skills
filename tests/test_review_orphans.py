"""docs-review: pages this tool wrote that no deliverable claims any more.

Dropping the per-module writer leaves whatever it wrote sitting in the docs
tree, and stale generated prose is the condition the foundation set exists to
remove.

Reporting it is the tool's job. Deleting it is a person's, because those files
carry inbound links from hand-written pages, and a tool that breaks them
unasked has done more damage than the staleness it fixed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs-review" / "scripts"))

import review  # noqa: E402

_GENERATED = (
    "---\ntitle: {title}\nmanaged: generated\ngenerator: docs-skills/0.4.2\n"
    "source_sha: abc1234\n---\n\n# {title}\n"
)


def test_a_generated_page_no_deliverable_claims_is_an_orphan(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "pkg__queue.md").write_text(_GENERATED.format(title="Queue"))
    (docs / "README.md").write_text(_GENERATED.format(title="Readme"))
    found = review.orphans(tmp_path, "docs", claimed={"docs/README.md"})
    assert [entry["doc"] for entry in found] == ["docs/pkg__queue.md"]
    assert found[0]["kind"] == "orphan"
    assert found[0]["source_sha"] == "abc1234"


def test_a_manual_page_is_never_an_orphan(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text("---\ntitle: A\nmanaged: manual\n---\n\n# A\n")
    assert review.orphans(tmp_path, "docs", claimed=set()) == []


def test_a_page_this_tool_did_not_write_is_never_an_orphan(tmp_path):
    """`managed: generated` without this tool's stamp belongs to someone else.

    Without the generator check, dropping a writer would report every
    hand-managed page in the tree as rubbish to delete.
    """
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.md").write_text("---\ntitle: N\nmanaged: generated\n---\n\n# N\n")
    assert review.orphans(tmp_path, "docs", claimed=set()) == []


def test_reporting_an_orphan_does_not_delete_it(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    page = docs / "pkg__queue.md"
    page.write_text(_GENERATED.format(title="Queue"))
    review.orphans(tmp_path, "docs", claimed=set())
    assert page.exists(), "review reports; it never deletes"


def test_a_missing_docs_tree_yields_nothing(tmp_path):
    assert review.orphans(tmp_path, "docs", claimed=set()) == []


def test_an_unreadable_page_is_left_to_the_main_loop(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "broken.md").write_text("---\n: : not: yaml: at all\n---\n\n# B\n")
    assert review.orphans(tmp_path, "docs", claimed=set()) == []


def _write_py():
    sys.path.insert(0, str(_ROOT / "skills" / "docs-write" / "scripts"))
    import write

    return write


def test_pruning_removes_only_unclaimed_generated_pages(tmp_path):
    """The deletion half, which only runs when someone asks for it."""
    write = _write_py()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "pkg__queue.md").write_text(_GENERATED.format(title="Queue"))
    (docs / "README.md").write_text(_GENERATED.format(title="Readme"))
    (docs / "architecture.md").write_text("---\ntitle: A\nmanaged: manual\n---\n\n# A\n")
    (docs / "notes.md").write_text("---\ntitle: N\nmanaged: generated\n---\n\n# N\n")

    plan = {"deliverables": [{"path": "docs/README.md", "foundation": "readme"}]}
    removed = write.prune_orphans(tmp_path, "docs", plan)

    assert [entry["path"] for entry in removed] == ["docs/pkg__queue.md"]
    assert not (docs / "pkg__queue.md").exists()
    assert (docs / "README.md").exists(), "a claimed page stays"
    assert (docs / "architecture.md").exists(), "a manual page is never pruned"
    assert (docs / "notes.md").exists(), "a page this tool did not write is never pruned"


def test_pruning_a_tree_with_nothing_orphaned_removes_nothing(tmp_path):
    write = _write_py()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text(_GENERATED.format(title="Readme"))
    plan = {"deliverables": [{"path": "docs/README.md", "foundation": "readme"}]}
    removed = write.prune_orphans(tmp_path, "docs", plan)
    assert removed == []
    assert (docs / "README.md").exists()


def test_a_topic_page_the_same_run_wrote_is_not_pruned(tmp_path):
    """The defect this join exists to prevent.

    A topic deliverable's `path` is a bare name that the writer joins onto the
    changeset directory. Comparing that field against a path on disk matched
    nothing, so a prune deleted every page the same run had just paid a model
    to write.
    """
    write = _write_py()
    new = tmp_path / "docs" / "changeset-2026-09-24-x" / "new"
    new.mkdir(parents=True)
    page = new / "configure-the-scheduler.md"
    page.write_text(_GENERATED.format(title="Configure the scheduler"))

    plan = {"deliverables": [{"path": "configure-the-scheduler.md", "kind": "new"}]}
    removed = write.prune_orphans(
        tmp_path, "docs", plan, changeset_dir=tmp_path / "docs" / "changeset-2026-09-24-x"
    )

    assert removed == []
    assert page.exists(), "the page this run just wrote must survive its own prune"


def test_a_topic_page_written_in_place_is_not_pruned(tmp_path):
    """Without a changeset the writer joins onto docs_dir instead."""
    write = _write_py()
    docs = tmp_path / "docs"
    docs.mkdir()
    page = docs / "configure-the-scheduler.md"
    page.write_text(_GENERATED.format(title="Configure the scheduler"))
    plan = {"deliverables": [{"path": "configure-the-scheduler.md", "kind": "new"}]}
    assert write.prune_orphans(tmp_path, "docs", plan) == []
    assert page.exists()

"""docs-sync: which modules the watermark may advance after a run.

A write record names a document, and a document cites several modules, so the
watermark is joined back through the queue that `docs_meta.stale()` produced.

The join has to be conservative. A module whose documents are only partly
written must stay behind, because the next run's fingerprint diff will find it
unchanged, never queue the missing documents again, and leave them stale for
good. Holding the module back costs one repeated write; advancing it costs a
page that is wrong until someone notices by hand.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs-sync" / "scripts"))

import sync  # noqa: E402


def _queued(*pairs):
    return [{"doc": doc, "modules": list(modules)} for doc, modules in pairs]


def test_a_module_advances_when_every_document_citing_it_was_written():
    queued = _queued(
        ("docs/ARCHITECTURE.md", ["pkg/scheduler", "pkg/datalayer"]),
        ("docs/GET-STARTED.md", ["pkg/scheduler"]),
    )
    advanced, stranded = sync.modules_fully_written(
        queued, {"docs/ARCHITECTURE.md", "docs/GET-STARTED.md"}
    )
    assert sorted(advanced) == ["pkg/datalayer", "pkg/scheduler"]
    assert stranded == []


def test_a_partly_written_module_is_held_back():
    """The defect this join exists to prevent.

    ARCHITECTURE wrote and GET-STARTED did not. Advancing `pkg/scheduler` here
    means the next run sees it unchanged and GET-STARTED never catches up.
    """
    queued = _queued(
        ("docs/ARCHITECTURE.md", ["pkg/scheduler", "pkg/datalayer"]),
        ("docs/GET-STARTED.md", ["pkg/scheduler"]),
    )
    advanced, stranded = sync.modules_fully_written(queued, {"docs/ARCHITECTURE.md"})
    assert stranded == ["pkg/scheduler"]
    assert "pkg/scheduler" not in advanced
    # datalayer is cited only by the document that did write, so it advances.
    assert advanced == {"pkg/datalayer": "docs/ARCHITECTURE.md"}


def test_nothing_written_advances_nothing():
    queued = _queued(("docs/ARCHITECTURE.md", ["pkg/scheduler"]))
    advanced, stranded = sync.modules_fully_written(queued, set())
    assert advanced == {}
    assert stranded == ["pkg/scheduler"]


def test_an_empty_queue_advances_nothing_and_strands_nothing():
    advanced, stranded = sync.modules_fully_written([], {"docs/ARCHITECTURE.md"})
    assert advanced == {}
    assert stranded == []


def test_the_recorded_document_is_stable_across_runs():
    """The watermark stores one document per module, so the choice must not
    wobble between runs and produce a spurious diff."""
    queued = _queued(
        ("docs/README.md", ["pkg/scheduler"]),
        ("docs/ARCHITECTURE.md", ["pkg/scheduler"]),
    )
    written = {"docs/README.md", "docs/ARCHITECTURE.md"}
    first, _ = sync.modules_fully_written(queued, written)
    second, _ = sync.modules_fully_written(list(reversed(queued)), written)
    assert first == second == {"pkg/scheduler": "docs/ARCHITECTURE.md"}


def test_the_attribution_join_survives_an_unparseable_page(tmp_path):
    """One page nobody can parse must not end every sync.

    `docs_meta.stale()` gates the whole incremental chain, and
    `docs_meta.MetaError` subclasses `RuntimeError`, so a `ValueError` catch
    elsewhere never covered it.
    """
    from lib.md import docs_meta

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "bad.md").write_text("---\nkey: [unclosed\n---\n\n# B\n")
    (docs / "good.md").write_text(
        "---\ntitle: G\nmanaged: generated\nsource_modules:\n  - pkg/a\n---\n\n# G\n"
    )
    result = docs_meta.stale(tmp_path, {"rebuild": ["pkg/a"]}, "docs")
    assert [entry["doc"] for entry in result["queued"]] == ["docs/good.md"]

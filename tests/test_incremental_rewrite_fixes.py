"""The incremental chain: what a rewrite queues, writes and settles.

A sync run is a join between a relevance verdict and what each page says it
was written from. Each test here stands for a way that join quietly produced
nothing: a verdict the writer never saw, a page refused on every run for a
reason no run could clear, and a sources list frozen at the shape the
repository had when the page was first written.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs-write" / "scripts"))

import write  # noqa: E402
from lib.md import docs_meta, ownership  # noqa: E402

_PAGE = (
    "---\ntitle: {title}\nmanaged: generated\ngenerator: docs-skills/0.4.2\n"
    "{extra}source_modules:\n  - pkg/a\n---\n\n# {title}\n"
)


def _page(tmp_path, name, title, extra=""):
    target = tmp_path / "docs" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_PAGE.format(title=title, extra=extra))
    return target


# ------------------------------------------------- a verdict the writer sees


def test_a_full_rebuild_verdict_queues_every_page_citing_a_module(tmp_path):
    """`sync` expands a `full_rebuild` into the registry's modules. A verdict
    record carries no `rebuild` key of its own, so passing the untouched
    verdict to the join queued nothing and the run rewrote none of the pages
    it had just declared untrustworthy."""
    _page(tmp_path, "ARCHITECTURE.md", "Architecture", extra="foundation: architecture\n")
    relevance = {"schema": "x", "verdict": "full_rebuild", "reason": "registry hash moved"}
    assert docs_meta.stale(tmp_path, relevance, "docs")["queued"] == []

    expanded = {**relevance, "rebuild": ["pkg/a"]}
    queued = docs_meta.stale(tmp_path, expanded, "docs")["queued"]
    assert [record["doc"] for record in queued] == ["docs/ARCHITECTURE.md"]


# ------------------------------------------------- a refusal a run can clear


def test_a_page_written_before_the_foundation_key_is_still_rewritten(tmp_path):
    """A page from an earlier release carries `source_modules` but no
    `foundation` key. Refusing it stranded every module it cites, and the
    next run produced the same queue and the same refusal for good."""
    _page(tmp_path, "ARCHITECTURE.md", "Architecture")
    deliverable, refusal = write._deliverable_from_document(tmp_path, "docs/ARCHITECTURE.md")
    assert refusal is None
    assert deliverable["foundation"] == "architecture"


def test_a_page_this_writer_does_not_own_is_refused_once_and_for_all(tmp_path):
    """Nothing a later run does makes a topic page a foundation document, so
    the refusal says so and the caller settles the module on it rather than
    queueing the same page to the same refusal on every run."""
    _page(tmp_path, "pkg__queue.md", "Queue")
    deliverable, refusal = write._deliverable_from_document(tmp_path, "docs/pkg__queue.md")
    assert deliverable is None
    assert refusal["permanent"] is True


def test_a_missing_document_is_not_a_permanent_refusal(tmp_path):
    """It is a page somebody deleted between the queue and the write, which a
    later run does resolve."""
    (tmp_path / "docs").mkdir()
    _, refusal = write._deliverable_from_document(tmp_path, "docs/gone.md")
    assert not refusal.get("permanent")


# --------------------------------------------------------- sources that move


def test_a_rewrite_takes_the_registry_as_it_is_now(tmp_path):
    """Reading `source_modules` back off the page and stamping it again froze
    the list, so a module added after the last full run appeared in no page's
    sources and nothing ever queued the document describing it."""
    _page(tmp_path, "ARCHITECTURE.md", "Architecture", extra="foundation: architecture\n")
    deliverable, _ = write._deliverable_from_document(
        tmp_path, "docs/ARCHITECTURE.md", fresh_sources=["pkg/a", "pkg/router"]
    )
    assert deliverable["sources"] == ["pkg/a", "pkg/router"]


def test_a_page_the_gates_no_longer_plan_keeps_its_own_sources(tmp_path):
    _page(tmp_path, "ARCHITECTURE.md", "Architecture", extra="foundation: architecture\n")
    deliverable, _ = write._deliverable_from_document(tmp_path, "docs/ARCHITECTURE.md")
    assert deliverable["sources"] == ["pkg/a"]


# ------------------------------------------------------- one set of joins


def test_an_update_deliverable_is_claimed_at_the_path_it_lands_on():
    """`update` names a page under `docs_dir`. Comparing the raw field
    against disk reported the page a run had just updated as an orphan."""
    plan = {"deliverables": [{"path": "guides/install.md", "kind": "update"}]}
    assert ownership.claimed_paths(".", "docs", plan) == {"docs/guides/install.md"}


def test_a_foundation_deliverable_is_already_repo_relative():
    plan = {"deliverables": [{"path": "docs/README.md", "foundation": "readme"}]}
    assert ownership.claimed_paths(".", "docs", plan) == {"docs/README.md"}


# ----------------------------------------------- one page nobody can parse


def test_the_frontmatter_fill_survives_a_page_that_will_not_parse(tmp_path):
    """`mark` was the one helper left without the guard. An unhandled
    `MetaError` exited a code the caller allows, so every page went unstamped
    and nothing in the log told it apart from a clean no-op."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "broken.md").write_text("---\n: : not: yaml: at all\n---\n\nbody\n")
    (docs / "fine.md").write_text("---\ntitle: Fine\n---\n\nbody\n")
    result = docs_meta.mark(
        tmp_path,
        {"context"},
        write=True,
        docs_dir="docs",
        context={"generator": "docs-skills/1", "head": "abcdef1234567890"},
    )
    assert [entry["doc"] for entry in result["skipped"]] == ["docs/broken.md"]
    assert "source_sha: abcdef123456" in (docs / "fine.md").read_text()


# ------------------------------------------------- which pages the walk sees


_FOUNDATION_PAGE = (
    "---\ntitle: What this is\ndescription: d\ntype: reference\nmanaged: generated\n"
    "foundation: readme\nsource_modules:\n  - pkg/a\n---\n\n# What this is\n"
)


def _repo_with_both_readmes(tmp_path):
    (tmp_path / "README.md").write_text("# The project\n\nnobody's tool wrote this\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text(_FOUNDATION_PAGE)
    return tmp_path


def test_the_readme_the_foundation_set_writes_is_walked(tmp_path):
    """Skipping the name everywhere swept up the page this tool writes, so
    the one document every reader starts at was the one document no
    incremental run could stamp, index or queue."""
    root = _repo_with_both_readmes(tmp_path)
    walked = sorted(str(path.relative_to(root)) for path in docs_meta.walk(root, "docs"))
    assert walked == ["docs/README.md"]


def test_the_repository_front_page_is_still_left_alone(tmp_path):
    """It belongs to whoever wrote it, and a walk with no docs directory
    reaches it."""
    root = _repo_with_both_readmes(tmp_path)
    walked = sorted(str(path.relative_to(root)) for path in docs_meta.walk(root))
    assert walked == ["docs/README.md"]


def test_a_changed_module_queues_the_generated_readme(tmp_path):
    root = _repo_with_both_readmes(tmp_path)
    queued = docs_meta.stale(root, {"rebuild": ["pkg/a"]}, "docs")["queued"]
    assert [record["doc"] for record in queued] == ["docs/README.md"]


def test_the_generated_readme_reaches_the_index(tmp_path):
    root = _repo_with_both_readmes(tmp_path)
    assert [entry["path"] for entry in docs_meta.build_index(root, "docs")] == ["docs/README.md"]


def test_agent_instructions_are_skipped_wherever_they_sit(tmp_path):
    """A nested AGENTS.md is read the same way the root one is."""
    nested = tmp_path / "docs" / "pkg"
    nested.mkdir(parents=True)
    (nested / "AGENTS.md").write_text("# instructions\n")
    (nested / "CLAUDE.md").write_text("# instructions\n")
    (nested / "guide.md").write_text("---\ntitle: G\n---\n\n# G\n")
    walked = sorted(str(path.relative_to(tmp_path)) for path in docs_meta.walk(tmp_path, "docs"))
    assert walked == ["docs/pkg/guide.md"]

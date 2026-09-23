"""docs-write: an update deliverable names a file in this repository.

An update target is a path under `docs_dir`, and the ownership contract is
what decides whether it may be written.

`run_plan` is the seam these test through. A `llm_cmd` of `None` short-circuits
before any model call, which is what lets a refusal be tested without one: every
case here is refused before a prompt would be built.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SKILL = Path(__file__).resolve().parent.parent / "skills" / "docs-write" / "scripts"
if str(_SKILL) not in sys.path:
    sys.path.insert(0, str(_SKILL))

import write  # noqa: E402


def _repo(tmp_path, pages):
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    for name, text in pages.items():
        (tmp_path / "docs" / name).write_text(text)
    return tmp_path


def _deliverable(path, **extra):
    return {
        "path": path,
        "kind": "update",
        "title": path.removesuffix(".md").replace("-", " ").capitalize(),
        "type": "concept",
        "rationale": "the subject moved",
        "sources": [],
        **extra,
    }


def test_an_update_target_that_does_not_exist_is_refused_not_crashed(tmp_path):
    repo = _repo(tmp_path, {})
    report = write.run_plan(
        repo,
        {"deliverables": [_deliverable("gone.md")]},
        docs_dir="docs",
        llm_cmd=None,
        out=tmp_path / "out",
    )
    entry = report["results"][0]
    assert entry["status"] == "refused"
    assert "does not exist" in entry["reason"]


def test_a_manual_target_is_never_opened(tmp_path):
    repo = _repo(tmp_path, {"queue.md": "---\nmanaged: manual\ntitle: Queue\n---\n\n# Queue\n"})
    before = (repo / "docs" / "queue.md").read_text()
    report = write.run_plan(
        repo,
        {"deliverables": [_deliverable("queue.md")]},
        docs_dir="docs",
        llm_cmd=None,
        out=tmp_path / "out",
    )
    assert report["results"][0]["status"] == "refused"
    assert "manual" in report["results"][0]["reason"]
    assert (repo / "docs" / "queue.md").read_text() == before


def test_a_run_whose_every_write_is_refused_reports_nothing_written(tmp_path):
    repo = _repo(
        tmp_path,
        {
            "a.md": "---\nmanaged: manual\ntitle: A\n---\n\n# A\n",
            "b.md": "---\nmanaged: manual\ntitle: B\n---\n\n# B\n",
        },
    )
    report = write.run_plan(
        repo,
        {"deliverables": [_deliverable("a.md"), _deliverable("b.md")]},
        docs_dir="docs",
        llm_cmd=None,
        out=tmp_path / "out",
    )
    assert report["written"] == 0
    assert [r["status"] for r in report["results"]] == ["refused", "refused"]


def test_an_update_target_escaping_the_docs_directory_is_refused(tmp_path):
    repo = _repo(tmp_path, {})
    (repo / "secret.md").write_text("---\nmanaged: generated\n---\n\n# Secret\n")
    report = write.run_plan(
        repo,
        {"deliverables": [_deliverable("../secret.md")]},
        docs_dir="docs",
        llm_cmd=None,
        out=tmp_path / "out",
    )
    assert report["results"][0]["status"] == "refused"

"""Linting only what the tool wrote.

`write.py` already lints an update's rewritten section alone, never the
published guide around it. The `docs-gen` comment markers are the same idea
applied to review: once they exist, the published prose surrounding an
edited section is never linted by review either.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_REVIEW = REPO_ROOT / "skills" / "docs-review" / "scripts"
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
for path in (_ENGINE, _REVIEW):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import review  # noqa: E402

MARKED = (
    "Published prose before, untouched.\n\n"
    "<!-- docs-gen output RHOAIENG-82726 -->\n"
    "The new bit the tool wrote.\n"
    "<!-- end docs-gen -->\n\n"
    "Published prose after, also untouched.\n"
)


def test_prose_targets_narrows_a_marked_page_to_its_span(tmp_path):
    out = tmp_path / ".docs-gen"
    page = review.Page(Path("guide.edit.md"), "docs/cs/guide.edit.md", MARKED, {}, MARKED)
    targets, names = review.prose_targets([page], out)
    assert len(targets) == 1
    content = targets[0].read_text()
    assert "The new bit the tool wrote." in content
    assert "untouched" not in content
    assert names[str(targets[0].resolve())] == "docs/cs/guide.edit.md"


def test_prose_targets_lints_the_whole_file_without_any_markers(tmp_path):
    out = tmp_path / ".docs-gen"
    path = tmp_path / "plain.md"
    page = review.Page(path, "plain.md", "No markers here.\n", {}, "No markers here.\n")
    targets, names = review.prose_targets([page], out)
    assert targets == [path]
    assert names[str(path.resolve())] == "plain.md"


def test_check_prose_uses_doc_names_to_report_the_real_file(monkeypatch, tmp_path):
    scratch = tmp_path / "scratch.md"
    scratch.write_text("x")
    alert = review.check.Alert(
        file=str(scratch),
        line=1,
        span=(0, 0),
        check="Some.Rule",
        severity="error",
        message="m",
        match="",
    )
    monkeypatch.setattr(review.check, "run", lambda config, docs, timeout=120: [alert])
    findings = review.check_prose(
        [scratch],
        tmp_path,
        "config.ini",
        doc_names={str(scratch.resolve()): "docs/cs/guide.edit.md"},
    )
    assert findings[0]["doc"] == "docs/cs/guide.edit.md"


@pytest.mark.skipif(shutil.which("vale") is None, reason="vale is not installed")
def test_review_never_lints_published_prose_outside_the_markers(tmp_path):
    repo = tmp_path / "repo"
    changeset = repo / "docs" / "changeset-2026-09-14-X"
    updates = changeset / "updates"
    updates.mkdir(parents=True)

    draft = (
        "Published prose with a bare claim that would fail CitationRequired.\n\n"
        "<!-- docs-gen output X -->\n"
        "- A sourced claim [src:main.py]\n"
        "<!-- end docs-gen -->\n"
    )
    (updates / "guide.edit.md").write_text(draft)
    (updates / "guide.md").write_text("Published prose with a bare claim.\n")

    out = tmp_path / ".docs-gen"
    out.mkdir()
    draft_rel = str((updates / "guide.edit.md").relative_to(repo))
    report = {
        "schema": "docs-skills/write/1",
        "written": [{"path": draft_rel, "status": "written", "kind": "update"}],
        "unchanged": [],
        "refused": [],
        "failed": [],
        "deferred": [],
        "results": [{"path": draft_rel, "status": "written", "kind": "update"}],
    }
    (out / "write-report.json").write_text(json.dumps(report))

    config = tmp_path / "config.ini"
    config.write_text(
        f"StylesPath = {REPO_ROOT / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n"
        "[*.md]\nBasedOnStyles = DocsNotes\n"
    )

    code = review.main(
        [
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--docs-dir",
            "docs",
            "--vale-config",
            str(config),
        ]
    )
    findings = json.loads((out / "review.json").read_text())["findings"]
    prose_findings = [f for f in findings if f["kind"] == "prose"]
    assert prose_findings == [], prose_findings
    assert code == 0


# --------------------------------------------------------------- changed_span


def test_changed_span_returns_the_joined_marked_spans():
    page = review.Page(Path("guide.edit.md"), "docs/cs/guide.edit.md", MARKED, {}, MARKED)
    assert review.changed_span(page) == "The new bit the tool wrote."


def test_changed_span_returns_none_without_any_markers():
    text = "No markers here.\n"
    page = review.Page(Path("plain.md"), "plain.md", text, {}, text)
    assert review.changed_span(page) is None


# -------------------------------------------- the style judge reads the span


DISTINCTIVE_OUTSIDE = "FROM apache/spark, published prose the tool never touched."
DISTINCTIVE_INSIDE = (
    "sparkoperator is the two-token change this run authored, and the rest of "
    "this paragraph exists only to clear the style floor so the pass actually "
    "runs a model call over the span, since a document under the word count "
    "floor is never worth spending a call on at all in this pipeline."
)

STYLE_MARKED = (
    f"Published prose before. {DISTINCTIVE_OUTSIDE}\n\n"
    "<!-- docs-gen output RHOAIENG-82726 -->\n"
    f"{DISTINCTIVE_INSIDE}\n"
    "<!-- end docs-gen -->\n\n"
    "Published prose after, also untouched.\n"
)


def test_judgeable_narrows_a_marked_page_to_its_span():
    """Required test 1: the style judge sees only the marked span."""
    page = review.Page(
        Path("guide.edit.md"),
        "docs/cs/guide.edit.md",
        STYLE_MARKED,
        {"managed": "generated"},
        STYLE_MARKED,
    )
    pairs = review.judgeable([page], floor=0)
    assert len(pairs) == 1
    rel, text = pairs[0]
    assert rel == "docs/cs/guide.edit.md"
    assert DISTINCTIVE_INSIDE in text
    assert DISTINCTIVE_OUTSIDE not in text


def test_judgeable_sends_the_whole_document_without_markers():
    """Required test 2: a page with no markers is unchanged from today."""
    body = "No markers here. " + " ".join(f"word{i}" for i in range(40))
    page = review.Page(
        Path("new/guide.md"), "docs/cs/new/guide.md", body, {"managed": "generated"}, body
    )
    pairs = review.judgeable([page], floor=0)
    assert pairs == [("docs/cs/new/guide.md", body)]


def test_vale_grounding_and_style_receive_the_same_span_for_the_same_document(tmp_path):
    """Required test 3: the three checks agree on what "the change" means."""
    page = review.Page(
        Path("guide.edit.md"), "docs/cs/guide.edit.md", MARKED, {"managed": "generated"}, MARKED
    )

    targets, _ = review.prose_targets([page], tmp_path)
    vale_text = targets[0].read_text().strip()

    grounding_span = review.changed_span(page)

    _, style_text = review.judgeable([page], floor=0)[0]

    assert vale_text == "The new bit the tool wrote."
    assert grounding_span == vale_text
    assert style_text.strip() == vale_text


def test_style_judge_payload_contains_only_the_marked_span_end_to_end(monkeypatch, tmp_path):
    """Required test 1, exercised through the real payload a model would see."""
    repo = tmp_path / "repo"
    changeset = repo / "docs" / "changeset-2026-09-14-RHOAIENG-82726"
    updates = changeset / "updates"
    updates.mkdir(parents=True)
    (updates / "guide.edit.md").write_text(STYLE_MARKED)

    out = tmp_path / ".docs-gen"
    out.mkdir()
    draft_rel = str((updates / "guide.edit.md").relative_to(repo))
    report = {
        "schema": "docs-skills/write/1",
        "written": [{"path": draft_rel, "status": "written", "kind": "update"}],
        "unchanged": [],
        "refused": [],
        "failed": [],
        "deferred": [],
        "results": [{"path": draft_rel, "status": "written", "kind": "update"}],
    }
    (out / "write-report.json").write_text(json.dumps(report))

    captured = []

    def fake_run_step(prompt_text, payload, schema, command, timeout, retries=1, values=None):
        captured.append(payload)
        return {"findings": []}, 1

    monkeypatch.setattr(review.step, "run_step", fake_run_step)
    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--llm-cmd", "fake"])

    assert len(captured) == 1
    body_sent = captured[0]["body"]
    assert DISTINCTIVE_INSIDE in body_sent
    assert DISTINCTIVE_OUTSIDE not in body_sent


# --------------------------------------------- the tool's own marker is not content


def test_marker_lines_never_reach_the_style_judges_payload():
    """Required FIX 2 test: marker lines never reach the judge's payload."""
    page = review.Page(
        Path("guide.edit.md"), "docs/cs/guide.edit.md", MARKED, {"managed": "generated"}, MARKED
    )
    _, text = review.judgeable([page], floor=0)[0]
    assert "docs-gen output" not in text
    assert "end docs-gen" not in text


def test_marker_lines_stay_in_the_file_on_disk_after_a_style_pass(monkeypatch, tmp_path):
    """Required FIX 2 test: the marker is stripped only from the payload, never
    from the file -- it is meant to be stripped when porting into AsciiDoc,
    which happens outside this tool, and it tells a human which span the tool
    wrote."""
    repo = tmp_path / "repo"
    changeset = repo / "docs" / "changeset-2026-09-14-RHOAIENG-82726"
    updates = changeset / "updates"
    updates.mkdir(parents=True)
    draft = updates / "guide.edit.md"
    draft.write_text(STYLE_MARKED)

    out = tmp_path / ".docs-gen"
    out.mkdir()
    draft_rel = str(draft.relative_to(repo))
    report = {
        "schema": "docs-skills/write/1",
        "written": [{"path": draft_rel, "status": "written", "kind": "update"}],
        "unchanged": [],
        "refused": [],
        "failed": [],
        "deferred": [],
        "results": [{"path": draft_rel, "status": "written", "kind": "update"}],
    }
    (out / "write-report.json").write_text(json.dumps(report))

    monkeypatch.setattr(review.step, "run_step", lambda *a, **k: ({"findings": []}, 1))
    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--llm-cmd", "fake"])

    on_disk = draft.read_text()
    assert "<!-- docs-gen output RHOAIENG-82726 -->" in on_disk
    assert "<!-- end docs-gen -->" in on_disk


# ------------------------------------------------- grounding reads the span too


def test_grounding_never_flags_an_identifier_outside_the_markers(tmp_path):
    """The grounding check must not judge published prose a run never touched."""
    repo = tmp_path / "repo"
    changeset = repo / "docs" / "changeset-2026-09-14-RHOAIENG-82726"
    updates = changeset / "updates"
    updates.mkdir(parents=True)

    draft = (
        "Published prose that names `some_untouched_symbol`, never edited.\n\n"
        "<!-- docs-gen output RHOAIENG-82726 -->\n"
        "This run's own text, naming `sparkoperator` only.\n"
        "<!-- end docs-gen -->\n"
    )
    (updates / "guide.edit.md").write_text(draft)

    out = tmp_path / ".docs-gen"
    out.mkdir()
    draft_rel = str((updates / "guide.edit.md").relative_to(repo))
    report = {
        "schema": "docs-skills/write/1",
        "written": [{"path": draft_rel, "status": "written", "kind": "update"}],
        "unchanged": [],
        "refused": [],
        "failed": [],
        "deferred": [],
        "results": [{"path": draft_rel, "status": "written", "kind": "update"}],
    }
    (out / "write-report.json").write_text(json.dumps(report))
    (out / "api-surface.json").write_text(
        json.dumps(
            {
                "ticket": "RHOAIENG-82726",
                "repositories": ["https://example/a"],
                "modules": {"a/b": {"symbols": {"class:Unrelated": {}}}},
            }
        )
    )
    (out / "sources.json").write_text(
        json.dumps(
            {
                "ticket": "RHOAIENG-82726",
                "repositories": [{"url": "https://example/a", "status": "cloned"}],
            }
        )
    )

    code = review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs"])
    report_out = json.loads((out / "review.json").read_text())
    symbols = {f["symbol"] for f in report_out["findings"] if f["kind"] == "ungrounded-identifier"}
    assert symbols == {"sparkoperator"}
    assert code == 0

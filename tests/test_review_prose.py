"""Vale's verdict, folded into the deterministic review.

The review's contract is that it blocks on errors and reports everything else.
Prose joins that contract without changing it: a dirty document is an error, a
Vale that cannot run is a warning.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_REVIEW = REPO_ROOT / "skills" / "docs-review" / "scripts"
if str(_REVIEW) not in sys.path:
    sys.path.insert(0, str(_REVIEW))

import review  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("vale") is None, reason="vale is not installed")


def config_for(tmp_path, styles="DocsNotes"):
    config = tmp_path / "config.ini"
    config.write_text(
        f"StylesPath = {REPO_ROOT / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n"
        f"[*.md]\nBasedOnStyles = {styles}\n"
    )
    return config


def test_clean_document_yields_no_findings(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text("# Notes\n\n- A sourced claim [src:main.py]\n")
    assert review.check_prose([doc], tmp_path, config_for(tmp_path)) == []


def test_dirty_document_is_an_error(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text("# Notes\n\n- A claim with nothing behind it\n")
    findings = review.check_prose([doc], tmp_path, config_for(tmp_path))
    assert [f["severity"] for f in findings] == ["error"]
    assert findings[0]["kind"] == "prose"
    assert findings[0]["check"] == "DocsNotes.CitationRequired"
    assert findings[0]["doc"] == "notes.md"


def test_finding_detail_names_the_line_and_stays_short(tmp_path):
    """A finding that quotes the offending paragraph costs more than it saves."""
    doc = tmp_path / "notes.md"
    doc.write_text("# Notes\n\n- A claim with nothing behind it\n")
    detail = review.check_prose([doc], tmp_path, config_for(tmp_path))[0]["detail"]
    assert detail.startswith("line 3:")
    assert len(detail) < 200


def test_unusable_config_is_a_warning_not_an_error(tmp_path):
    """A repository that has not synced third-party styles still gets reviewed."""
    doc = tmp_path / "notes.md"
    doc.write_text("# Notes\n\n- A sourced claim [src:main.py]\n")
    findings = review.check_prose([doc], tmp_path, config_for(tmp_path, styles="NoSuchStyle"))
    assert [f["severity"] for f in findings] == ["warning"]
    assert findings[0]["kind"] == "vale-unavailable"


def test_one_warning_covers_the_whole_run(tmp_path):
    """Vale runs once for the set, so a broken config is reported once."""
    for name in ("a.md", "b.md", "c.md"):
        (tmp_path / name).write_text("# T\n\n- sourced [src:x.py]\n")
    findings = review.check_prose(
        sorted(tmp_path.glob("*.md")), tmp_path, config_for(tmp_path, styles="NoSuchStyle")
    )
    assert len(findings) == 1


def test_no_documents_means_no_vale_call(tmp_path):
    assert review.check_prose([], tmp_path, config_for(tmp_path)) == []


def test_level_floor_drops_alerts_below_it(tmp_path):
    """A suggestion-level rule must not block a run whose floor is error."""
    style = tmp_path / "styles" / "Loud"
    style.mkdir(parents=True)
    (style / "Hint.yml").write_text(
        "extends: existence\nmessage: 'A hint.'\nlevel: suggestion\ntokens:\n  - hintword\n"
    )
    config = tmp_path / "loud.ini"
    config.write_text(
        f"StylesPath = {tmp_path / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n"
        "[*.md]\nBasedOnStyles = Loud\n"
    )
    doc = tmp_path / "notes.md"
    doc.write_text("# Notes\n\nA hintword lives here.\n")
    assert review.check_prose([doc], tmp_path, config, level="error") == []
    # The severity matters as much as the count. A refactor that mapped every
    # alert clearing the floor to "error" would pass a count-only assertion and
    # turn a suggestion into a blocking finding.
    lowered = review.check_prose([doc], tmp_path, config, level="suggestion")
    assert [f["severity"] for f in lowered] == ["warning"]
    assert [f["check"] for f in lowered] == ["Loud.Hint"]


def test_cli_reports_dirty_prose_without_blocking(tmp_path):
    """A style rule is guidance about wording, weighed by a person against the
    page in front of them. `Direct.Length` measuring a Markdown table row as a
    sentence settled it: the rule was right about the word count and wrong
    about the document, and the run could not tell those apart."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "notes.md").write_text(
        "---\nmanaged: generated\ndescription: d\nsource_sha: abc1234\n---\n\n"
        "# Notes\n\n- A claim with nothing behind it\n"
    )
    out = tmp_path / "out"
    out.mkdir()
    code = review.main(
        [
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--docs-dir",
            "docs",
            "--vale-config",
            str(config_for(tmp_path)),
        ]
    )
    assert code == 0
    report = json.loads((out / "review.json").read_text())
    assert report["counts"]["advisory"] == 1
    assert report["counts"]["blocking"] == 0
    assert [f["kind"] for f in report["findings"]] == ["prose"]


def test_strict_still_blocks_on_dirty_prose(tmp_path):
    """The gate is kept, behind the flag whose name says what it does."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "notes.md").write_text(
        "---\nmanaged: generated\ndescription: d\nsource_sha: abc1234\n---\n\n"
        "# Notes\n\n- A claim with nothing behind it\n"
    )
    out = tmp_path / "out"
    out.mkdir()
    code = review.main(
        [
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--docs-dir",
            "docs",
            "--vale-config",
            str(config_for(tmp_path)),
            "--strict",
        ]
    )
    assert code == 3


def test_cli_without_the_flag_never_calls_vale(tmp_path, monkeypatch):
    """Deterministic-only stays the default. Prose checking is opt-in per run."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "notes.md").write_text(
        "---\nmanaged: generated\ndescription: d\nsource_sha: abc1234\n---\n\n"
        "# Notes\n\n- A claim with nothing behind it\n"
    )
    out = tmp_path / "out"
    out.mkdir()

    def explode(*args, **kwargs):
        raise AssertionError("vale was invoked without --vale-config")

    monkeypatch.setattr(review.check, "run", explode)
    assert review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs"]) == 0


def test_manual_documents_are_exempt_from_the_prose_check(tmp_path):
    """Every other check here exempts a hand-written page, and prose must too.

    A Vale error in a file the writer never opens would exit 3 and block the
    sync with nothing the pipeline could do to clear it.
    """
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "hand.md").write_text(
        "---\nmanaged: manual\ndescription: d\n---\n\n"
        "# Hand written\n\n- A claim with nothing behind it\n"
    )
    out = tmp_path / "out"
    out.mkdir()
    code = review.main(
        [
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--docs-dir",
            "docs",
            "--vale-config",
            str(config_for(tmp_path)),
        ]
    )
    assert code == 0
    findings = json.loads((out / "review.json").read_text())["findings"]
    assert [f for f in findings if f["kind"] == "prose"] == []


def test_a_generated_document_beside_a_manual_one_is_still_checked(tmp_path):
    """The exemption is per document, not a switch that turns the check off."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "hand.md").write_text(
        "---\nmanaged: manual\ndescription: d\n---\n\n- Unsourced by a human\n"
    )
    (repo / "docs" / "made.md").write_text(
        "---\nmanaged: generated\ndescription: d\nsource_sha: abc1234\n---\n\n"
        "- Unsourced by a machine\n"
    )
    out = tmp_path / "out"
    out.mkdir()
    code = review.main(
        [
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--docs-dir",
            "docs",
            "--vale-config",
            str(config_for(tmp_path)),
        ]
    )
    assert code == 0, "a style finding reports without failing the run"
    prose = [
        f for f in json.loads((out / "review.json").read_text())["findings"] if f["kind"] == "prose"
    ]
    assert {f["doc"] for f in prose} == {"docs/made.md"}

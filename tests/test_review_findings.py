"""Findings that cannot apply to the kind of file they fired on.

An update's `.edit.md` draft is a copy of already-published Markdown, carrying
no frontmatter by design: the untouched copy beside it must stay
byte-identical, and a frontmatter block would appear at the top of every diff.
A `new/` page is the opposite case, generated whole with real frontmatter, so
an empty description there is a genuine finding.

Evidence for an update is a published documentation URL, not a path in this
repository, so it cannot be checked against the working tree the way a
repo-relative evidence line can.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_REVIEW = REPO_ROOT / "skills" / "docs-review" / "scripts"
if str(_REVIEW) not in sys.path:
    sys.path.insert(0, str(_REVIEW))

import review  # noqa: E402

# --------------------------------------------------- frontmatter, update drafts


def test_is_update_draft_recognises_the_edit_md_suffix():
    assert review.is_update_draft("docs/cs/updates/guide.edit.md") is True


def test_is_update_draft_is_false_for_a_new_page():
    assert review.is_update_draft("docs/cs/new/guide.md") is False


def test_description_empty_is_skipped_for_an_update_draft():
    """FIX 3(a): an .edit.md carries no frontmatter by design; the check
    cannot apply to a file that has none."""
    findings = review.check_frontmatter(
        "docs/cs/updates/guide.edit.md",
        {},
        in_changeset=True,
        is_update_draft=True,
    )
    assert findings == []


def test_description_empty_still_fires_for_a_new_page_with_none():
    """The check the skip replaces still fires where it genuinely applies."""
    findings = review.check_frontmatter(
        "docs/cs/new/guide.md",
        {"managed": "generated", "source_sha": "abc1234"},
        in_changeset=True,
        is_update_draft=False,
    )
    assert any(
        f["kind"] == "bad-frontmatter" and "description is empty" in f["detail"] for f in findings
    )


def test_description_empty_still_fires_for_an_ordinary_page_outside_a_changeset():
    findings = review.check_frontmatter(
        "docs/guide.md",
        {"managed": "generated", "source_sha": "abc1234"},
        in_changeset=False,
        is_update_draft=False,
    )
    assert any(
        f["kind"] == "bad-frontmatter" and "description is empty" in f["detail"] for f in findings
    )


def test_a_malformed_managed_field_is_not_swallowed_by_the_update_draft_skip():
    """The skip is narrow: it is for a file with no frontmatter at all, not a
    blanket exemption for anything under updates/. A draft that somehow does
    carry a bad managed field is not an update draft as the check defines it,
    so the check still catches it."""
    findings = review.check_frontmatter(
        "docs/cs/updates/guide.edit.md",
        {"managed": "not-a-real-value"},
        in_changeset=True,
        is_update_draft=False,
    )
    assert any(f["kind"] == "bad-frontmatter" and "managed is" in f["detail"] for f in findings)


# ------------------------------------------------------- evidence, URL entries


def test_a_url_evidence_entry_is_not_flagged_as_a_missing_file(tmp_path):
    """FIX 3(b): evidence for an update is a published doc URL, not a
    repo-relative path, and cannot be checked against the working tree."""
    report = {"evidence": ["https://docs.example/html/deploy#section-8-3-3"]}
    findings = review.check_evidence("docs/cs/updates/guide.edit.md", {}, tmp_path, report)
    assert findings == []


def test_an_http_evidence_entry_is_also_not_flagged(tmp_path):
    report = {"evidence": ["http://docs.example/html/deploy"]}
    findings = review.check_evidence("docs/cs/updates/guide.edit.md", {}, tmp_path, report)
    assert findings == []


def test_a_repo_relative_evidence_entry_that_exists_is_not_flagged(tmp_path):
    (tmp_path / "main.py").write_text("x = 1\n")
    report = {"evidence": ["main.py:1"]}
    findings = review.check_evidence("docs/cs/updates/guide.edit.md", {}, tmp_path, report)
    assert findings == []


def test_a_half_written_artifact_is_reported_rather_than_raised(tmp_path, capsys):
    """An interrupted earlier step must not end the review in a traceback."""
    (tmp_path / "registry.json").write_text('{"modules": {"pkg/queue"')
    assert review.load(tmp_path / "registry.json", {}) == {}
    assert "is unreadable" in capsys.readouterr().err


def test_a_repo_relative_evidence_entry_that_is_missing_still_fires(tmp_path):
    """The check the URL carve-out replaces still fires where it applies."""
    report = {"evidence": ["src/gone.py:12"]}
    findings = review.check_evidence("docs/cs/updates/guide.edit.md", {}, tmp_path, report)
    assert len(findings) == 1
    assert findings[0]["kind"] == "bad-evidence"
    assert "src/gone.py:12" in findings[0]["detail"]


# --------------------------------------------------------------- end to end


def test_main_does_not_warn_about_an_empty_description_on_an_update_draft(tmp_path, capsys):
    repo = tmp_path / "repo"
    changeset = repo / "docs" / "changeset-2026-09-14-RHOAIENG-82726"
    updates = changeset / "updates"
    updates.mkdir(parents=True)
    (updates / "guide.edit.md").write_text("Published prose, no frontmatter at all.\n")

    out = tmp_path / ".docs-gen"
    out.mkdir()
    draft_rel = str((updates / "guide.edit.md").relative_to(repo))
    write_report = {
        "results": [{"path": draft_rel, "status": "written", "kind": "update"}],
    }
    (out / "write-report.json").write_text(json.dumps(write_report))

    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs"])
    report = json.loads((out / "review.json").read_text())
    assert not any(
        f["kind"] == "bad-frontmatter" and "description" in f["detail"] for f in report["findings"]
    )


def test_main_still_warns_about_an_empty_description_on_a_new_page(tmp_path):
    repo = tmp_path / "repo"
    changeset = repo / "docs" / "changeset-2026-09-14-RHOAIENG-82726"
    new_dir = changeset / "new"
    new_dir.mkdir(parents=True)
    (new_dir / "guide.md").write_text(
        "---\nmanaged: generated\nsource_sha: abc1234\n---\n\n# Guide\n\nBody.\n"
    )

    out = tmp_path / ".docs-gen"
    out.mkdir()
    draft_rel = str((new_dir / "guide.md").relative_to(repo))
    write_report = {
        "results": [{"path": draft_rel, "status": "written", "kind": "new"}],
    }
    (out / "write-report.json").write_text(json.dumps(write_report))

    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs"])
    report = json.loads((out / "review.json").read_text())
    assert any(
        f["kind"] == "bad-frontmatter" and "description" in f["detail"] for f in report["findings"]
    )


# ------------------------------------------------------- grounding, false hits


def test_a_backticked_file_name_is_not_taken_for_a_symbol():
    """`README.md` satisfies the identifier shape and is a file name."""
    body = "See `README.md`, `build.py`, `lib/api_surface.py` and `docs-gen.yaml`.\n"
    assert review.prose_identifiers(body) == set()


def test_a_dotted_symbol_is_still_collected():
    assert review.prose_identifiers("Call `client.reconnect` to retry.") == {"client.reconnect"}


def test_a_token_whose_tail_is_not_a_file_suffix_survives():
    assert review.prose_identifiers("Use `config.timeout` here.") == {"config.timeout"}


def test_a_bare_ungrounded_word_reports_as_a_warning():
    surface = {"modules": {"a/b": {"symbols": {"class:Client": {}}}}}
    findings = review.check_grounding("d.md", {}, "Call `reconnect` now.", surface, set())
    assert [f["severity"] for f in findings] == ["warning"]


def test_a_qualified_ungrounded_name_reports_as_an_error():
    surface = {"modules": {"a/b": {"symbols": {"class:Client": {}}}}}
    findings = review.check_grounding("d.md", {}, "Call `client.reconnect` now.", surface, set())
    assert [f["severity"] for f in findings] == ["error"]


def test_a_grounding_error_is_advisory_and_does_not_block():
    assert "ungrounded-identifier" in review.ADVISORY_KINDS

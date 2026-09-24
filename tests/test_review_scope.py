"""What a run's review actually looks at.

A real run against RHOAIENG-82726 produced one correct draft and then judged
every markdown file under `docs/`: leftovers from a different run,
the tool's own internal index, and the untouched published copy a changeset
keeps beside its draft. None of those are this run's output, and grounding
that run's claims against a stale, unrelated `api-surface.json` turned a
clean draft into 51 errors.
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


def write_report(out_dir, results):
    report = {
        "schema": "docs-skills/write/1",
        "written": [r for r in results if r.get("status") == "written"],
        "unchanged": [r for r in results if r.get("status") == "unchanged"],
        "refused": [],
        "failed": [],
        "deferred": [],
        "results": results,
    }
    (out_dir / "write-report.json").write_text(json.dumps(report, indent=2))
    return report


def changeset_fixture(repo, topic="kv-cache-tiering", date="2026-09-14"):
    """A changeset shaped exactly like a real update run's output, plus the
    leftovers a real run also found sitting in `docs/`."""
    name = f"changeset-{date}-{topic}"
    changeset = repo / "docs" / name
    updates = changeset / "updates"
    updates.mkdir(parents=True)

    published = "Chapter 2\n---------\n\nSet `kubeflowsparkoperator` to Managed.\n"
    draft = "Chapter 2\n---------\n\nSet `sparkoperator` to Managed.\n"
    (updates / "guide.md").write_text(published)
    (updates / "guide.edit.md").write_text(draft)
    (updates / "guide.diff").write_text("--- a\n+++ b\n")
    (changeset / "index.md").write_text(
        f"---\ntitle: Changeset\nmanaged: generated\n---\n\n# Changeset\n\nTopic: {topic}\n"
    )

    # A different run, days earlier, left this beside it.
    (repo / "docs" / "unrelated-leftover.md").write_text(
        "---\ntitle: Unrelated\nmanaged: generated\ndescription: d\n"
        "source_sha: abc123\n---\n\n# Unrelated\n\n`some_unrelated_symbol` is invented.\n"
    )

    draft_rel = str((updates / "guide.edit.md").relative_to(repo))
    result = {
        "deliverable": "activate.md",
        "doc_type": "procedure",
        "kind": "update",
        "guide_url": "https://docs.example/guide",
        "section": "2",
        "path": draft_rel,
        "status": "written",
        "summary": "Corrected the component key",
    }
    return changeset, draft_rel, result


def test_review_scopes_to_what_the_write_report_names(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    out = tmp_path / ".docs-gen"
    out.mkdir()

    _, draft_rel, result = changeset_fixture(repo)
    write_report(out, [result])

    code = review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs"])
    report = json.loads((out / "review.json").read_text())

    assert report["documents"] == 1
    docs_seen = {f["doc"] for f in report["findings"]}
    assert docs_seen <= {draft_rel}
    assert not any("unrelated-leftover.md" in d for d in docs_seen)
    assert not any(d.endswith("guide.md") for d in docs_seen)
    assert not any(d.endswith("index.md") for d in docs_seen)
    assert not any(d.endswith(".diff") for d in docs_seen)
    assert code in (0, 3)


def test_no_write_report_falls_back_and_says_so_in_the_log(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "plain.md").write_text("# Plain\n\nHand-written.\n")

    out = tmp_path / ".docs-gen"
    out.mkdir()

    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs"])
    err = capsys.readouterr().err
    assert "write-report" in err.lower()

    report = json.loads((out / "review.json").read_text())
    assert report["documents"] == 1


def test_a_run_with_no_changeset_behaves_sensibly(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    out = tmp_path / ".docs-gen"
    out.mkdir()
    code = review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs"])
    assert code == 1


def test_index_md_is_never_reviewed_even_without_a_write_report(tmp_path):
    """Problem 1's fix normally keeps index.md out by only reading
    write-report paths, but the fallback path scans everything -- confirm
    index.md is still excluded there."""
    repo = tmp_path / "repo"
    changeset, _, _ = changeset_fixture(repo)
    out = tmp_path / ".docs-gen"
    out.mkdir()

    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs"])
    report = json.loads((out / "review.json").read_text())
    docs_seen = {f["doc"] for f in report["findings"]}
    assert not any(d.endswith("index.md") for d in docs_seen)


# ------------------------------------------------------------------ grounding


def test_grounding_still_reports_an_invented_symbol_with_a_matching_surface(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    out = tmp_path / ".docs-gen"
    out.mkdir()

    _, draft_rel, result = changeset_fixture(repo)
    write_report(out, [result])

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
    report = json.loads((out / "review.json").read_text())
    assert any(
        f["kind"] == "ungrounded-identifier" and f["doc"] == draft_rel for f in report["findings"]
    )
    # Textual matching reports and does not gate. `--strict` is the gate.
    assert code == 0
    assert (
        review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--strict"]) == 3
    )


# --------------------------------------------------------- unmarked drafts


def test_an_unmarked_changeset_draft_is_not_flagged_unonboarded():
    findings = review.check_frontmatter(
        "docs/changeset-2026-09-14-X/updates/guide.edit.md", {}, in_changeset=True
    )
    assert not any(f["kind"] == "unonboarded" for f in findings)


def test_an_unmarked_hand_written_page_is_still_flagged_unonboarded():
    findings = review.check_frontmatter("docs/plain.md", {}, in_changeset=False)
    assert any(f["kind"] == "unonboarded" for f in findings)


def test_page_is_manual_treats_an_unmarked_changeset_draft_as_not_manual():
    page = review.Page(
        Path("guide.edit.md"),
        "docs/changeset-2026-09-14-X/updates/guide.edit.md",
        "text",
        {},
        "body",
    )
    assert page.is_manual is False


def test_page_is_manual_still_honours_an_explicit_manual_marker_in_a_changeset():
    page = review.Page(
        Path("guide.edit.md"),
        "docs/changeset-2026-09-14-X/updates/guide.edit.md",
        "text",
        {"managed": "manual"},
        "body",
    )
    assert page.is_manual is True


def test_page_is_manual_still_treats_an_unmarked_non_changeset_file_as_manual():
    page = review.Page(Path("plain.md"), "docs/plain.md", "text", {}, "body")
    assert page.is_manual is True

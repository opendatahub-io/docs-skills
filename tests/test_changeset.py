"""The changeset a run produces.

New and updated documents land side by side under one directory, and the index
is the surface a reviewer opens first.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lib.md import changeset  # noqa: E402

REPORT = {
    "results": [
        {
            "deliverable": "configure-kv-cache-tiering.md",
            "kind": "new",
            "status": "written",
            "path": "docs/changeset-x/new/configure-kv-cache-tiering.md",
        },
        {
            "deliverable": "deploy.md",
            "kind": "update",
            "status": "written",
            "path": "docs/guides/deploy.md",
            "summary": "Added tiering",
            "gaps": ["Which tiers are supported"],
        },
        {
            "deliverable": "stale.md",
            "kind": "update",
            "status": "refused",
            "reason": "the target does not exist: docs/guides/stale.md",
        },
    ]
}


def test_the_directory_is_keyed_by_date_and_ticket():
    assert changeset.directory_for("docs", "RHOAIENG-71437", "", "2026-09-12") == (
        "docs/changeset-2026-09-12-RHOAIENG-71437"
    )


def test_a_run_with_no_ticket_falls_back_to_a_topic_slug():
    got = changeset.directory_for("docs", "", "Hierarchical KV Cache Tiering", "2026-09-12")
    assert got == "docs/changeset-2026-09-12-hierarchical-kv-cache-tiering"


def test_a_rerun_the_next_day_reuses_yesterdays_directory(tmp_path):
    """A re-run must land on the same path: the ownership contract and the
    churn floor both depend on seeing the file a previous run wrote, and a
    human's `managed: manual` edit in yesterday's draft must not be silently
    bypassed by today's date-keyed path."""
    (tmp_path / "docs" / "changeset-2026-09-12-RHOAIENG-71437").mkdir(parents=True)
    got = changeset.directory_for("docs", "RHOAIENG-71437", "", "2026-09-13", base=tmp_path)
    assert got == "docs/changeset-2026-09-12-RHOAIENG-71437"


def test_a_first_run_creates_todays_dated_directory(tmp_path):
    """No existing changeset for this ticket: a new, dated directory is made,
    same as when `base` is not given at all."""
    (tmp_path / "docs").mkdir(parents=True)
    got = changeset.directory_for("docs", "RHOAIENG-71437", "", "2026-09-13", base=tmp_path)
    assert got == "docs/changeset-2026-09-13-RHOAIENG-71437"


def test_the_index_lists_both_kinds():
    text = changeset.index(REPORT)
    assert "configure-kv-cache-tiering.md" in text
    assert "docs/guides/deploy.md" in text


def test_a_refusal_is_visible_with_its_reason():
    """A deliverable that was not written must be visible rather than absent."""
    text = changeset.index(REPORT)
    assert "stale.md" in text
    assert "the target does not exist" in text


def test_the_gaps_are_carried_into_the_index():
    assert "Which tiers are supported" in changeset.index(REPORT)


def test_the_index_is_typed_and_marked_generated():
    text = changeset.index(REPORT)
    assert text.startswith("---\n")
    assert "managed: generated" in text


RESEARCH = {"gaps": ["Which registries are supported"]}


def test_no_gaps_at_all_still_renders_the_closed_bullet():
    """An empty section reads as a section nobody filled in."""
    text = changeset.index({"results": [{"deliverable": "a.md", "status": "written"}]})
    assert "The run closed every question it raised" in text


def test_a_writer_s_gap_is_carried_into_the_index():
    """A gap is what a page wanted and the code did not answer, so it comes
    from the writers rather than from a research pass."""
    assert "Which tiers are supported?" in changeset.index(REPORT)


# ----------------------------------------------------------- pruning orphans


def make_changeset(tmp_path):
    """A repo with an existing changeset's `new/` and `updates/` directories."""
    repo = tmp_path / "repo"
    cs = repo / "docs" / "changeset-x"
    (cs / "new").mkdir(parents=True)
    (cs / "updates").mkdir(parents=True)
    return repo, cs


# The two tests below are written and run to green before `prune` exists,
# because they are the two that stop pruning from becoming a file-deleting
# bug: one proves an explicit `managed: manual` sibling set is never touched,
# the other proves the blast radius stops at the changeset directory.


def test_nothing_outside_the_changeset_directory_is_ever_touched(tmp_path):
    """Only files directly inside `<changeset>/new` are ever candidates. A
    sibling changeset from a different run, and anything else in the tree,
    must survive untouched."""
    repo, cs = make_changeset(tmp_path)
    sibling = repo / "docs" / "changeset-y"
    (sibling / "new").mkdir(parents=True)
    (sibling / "new" / "keep.md").write_text("keep me")
    (cs / "new" / "stale.md").write_text("---\nmanaged: generated\n---\n\nStale.\n")

    changeset.prune(repo, cs, [])

    assert (sibling / "new" / "keep.md").read_text() == "keep me"
    assert not (cs / "new" / "stale.md").exists()


def test_a_dropped_new_deliverable_is_removed_and_recorded(tmp_path):
    """A second run whose plan no longer contains a deliverable removes its
    file from `new/` and the index lists it under Removed."""
    repo, cs = make_changeset(tmp_path)
    stale = cs / "new" / "old-page.md"
    stale.write_text("---\nmanaged: generated\n---\n\nOld.\n")

    removals = changeset.prune(repo, cs, [])

    assert not stale.exists()
    assert len(removals) == 1
    assert removals[0]["status"] == "removed"
    assert removals[0]["path"].endswith("old-page.md")
    assert "no longer in the plan" in removals[0]["reason"]


def test_files_this_run_produced_are_untouched(tmp_path):
    repo, cs = make_changeset(tmp_path)
    kept_new = cs / "new" / "keep.md"
    kept_new.write_text("---\nmanaged: generated\n---\n\nKeep.\n")
    updates = cs / "updates"
    (updates / "deploy.md").write_text("guide copy")
    (updates / "deploy.edit.md").write_text("edited copy")
    (updates / "deploy.diff").write_text("diff")

    results = [
        {"deliverable": "keep.md", "status": "written", "path": str(kept_new.relative_to(repo))},
        {
            "deliverable": "deploy.md",
            "kind": "update",
            "status": "written",
            "path": str((updates / "deploy.edit.md").relative_to(repo)),
        },
    ]
    removals = changeset.prune(repo, cs, results)

    assert kept_new.exists()
    assert (updates / "deploy.md").exists()
    assert (updates / "deploy.edit.md").exists()
    assert (updates / "deploy.diff").exists()
    assert removals == []


def test_index_and_a_root_level_human_file_are_never_touched(tmp_path):
    """`index.md` is never a candidate, and neither is anything a human
    dropped directly in the changeset directory rather than in `new/` or
    `updates/`."""
    repo, cs = make_changeset(tmp_path)
    (cs / "index.md").write_text("existing index")
    (cs / "notes.md").write_text("human notes")

    changeset.prune(repo, cs, [])

    assert (cs / "index.md").read_text() == "existing index"
    assert (cs / "notes.md").read_text() == "human notes"


def test_a_refused_deliverable_that_never_wrote_a_file_has_nothing_to_prune(tmp_path):
    """A deliverable refused before anything was written produced nothing, so
    it neither protects a file nor causes one to be removed."""
    repo, cs = make_changeset(tmp_path)
    results = [{"deliverable": "gone.md", "status": "refused", "reason": "no cached guide"}]
    removals = changeset.prune(repo, cs, results)
    assert removals == []


def test_a_first_run_with_no_prior_artifacts_removes_nothing(tmp_path):
    """`new/` and `updates/` do not exist yet on the very first run."""
    repo = tmp_path / "repo"
    cs = repo / "docs" / "changeset-x"
    cs.mkdir(parents=True)
    removals = changeset.prune(repo, cs, [])
    assert removals == []


def test_an_orphan_with_malformed_frontmatter_survives_pruning(tmp_path):
    """On the destructive path an indeterminate ownership answer means keep.
    A human whose hand-edited draft has broken frontmatter is exactly the
    person who must not lose it: an exception must never decide a deletion."""
    repo, cs = make_changeset(tmp_path)
    orphan = cs / "new" / "b.md"
    orphan.write_text("---\n- not a mapping\n---\n\nbody\n")

    removals = changeset.prune(repo, cs, [])

    assert orphan.exists(), "an unreadable ownership verdict must not delete the file"
    assert len(removals) == 1
    assert removals[0]["status"] == "kept"
    assert "frontmatter" in removals[0]["reason"].lower()


def test_the_index_lists_what_was_removed():
    removals = [
        {
            "path": "docs/changeset-x/new/old-page.md",
            "status": "removed",
            "reason": "no longer in the plan",
        },
    ]
    text = changeset.index(REPORT, removals=removals)
    assert "old-page.md" in text
    assert "no longer in the plan" in text
    assert "(removed)" in text


def test_the_index_distinguishes_kept_from_removed():
    removals = [
        {
            "path": "docs/changeset-x/updates/deploy.edit.md",
            "status": "kept",
            "reason": "managed: manual",
        },
    ]
    text = changeset.index(REPORT, removals=removals)
    assert "(kept)" in text
    assert "managed: manual" in text


def test_the_index_says_nothing_was_removed_rather_than_an_empty_section():
    text = changeset.index(REPORT, removals=[])
    assert "## Removed" in text
    lowered = text.lower()
    assert "nothing" in lowered


def test_unresolved_prose_is_named_in_the_index():
    """A page kept in spite of prose that would not clear is in the documents
    table like any other. This is where a reviewer is told which rules it is
    still failing, so shipping it is a decision someone makes rather than one
    nobody was told about."""
    report = {
        "results": [
            {
                "deliverable": "supported-accelerators.md",
                "kind": "new",
                "path": "docs/new/supported-accelerators.md",
                "status": "written",
                "reason": "new file",
                "prose": "dirty",
                "prose_unresolved": ["Direct.Length line 12: the sentence is too long"],
            }
        ]
    }
    text = changeset.index(report)

    assert "## Unresolved prose" in text
    assert "Direct.Length line 12" in text
    assert "supported-accelerators.md" in text
    section = text.split("## Unresolved prose", 1)[1].split("##", 1)[0]
    bullets = [line for line in section.splitlines() if line.startswith("- ")]
    assert bullets and all("[src:" in line for line in bullets), "the index lints under DocsNotes"


def test_a_clean_run_has_no_unresolved_prose_section():
    report = {
        "results": [
            {
                "deliverable": "a.md",
                "kind": "new",
                "path": "docs/new/a.md",
                "status": "written",
                "reason": "new file",
                "prose": "clean",
            }
        ]
    }
    assert "Unresolved prose" not in changeset.index(report)

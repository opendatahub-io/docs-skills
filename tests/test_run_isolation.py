"""One directory per run, under the artifact root.

Every run used to write into `.docs-gen` itself. Measured in a scratch
repository: one directory held `requirements.json` from INFERENG-10745 beside
`placement.json`, `plan.json` and `review.json` from INFERENG-10737 and an
`api-surface.json` from a third run, with nothing in any of them saying which
run had written it. A step that stopped early left the previous ticket's
answer in place for the next one to read as its own.

What a run derives goes in its own directory. What a run downloads, the clones
and the Vale packages, stays in the root and is shared, because re-fetching
either per ticket spends minutes on bytes that do not differ.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD = REPO_ROOT / "skills" / "docs" / "scripts"
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
_SOURCES = REPO_ROOT / "skills" / "docs-sources" / "scripts"
for path in (_ENGINE, _BUILD, _SOURCES):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build  # noqa: E402
from lib.md import changeset as changeset_lib  # noqa: E402
from lib.pipeline import workspace  # noqa: E402
from lib.run import step  # noqa: E402

CONFIG = {"product": "RHOAI", "version": "2.19"}


def _args(**over):
    base = dict(
        # A ticket run still carries a topic: `build` derives one from the
        # requirements it reads, which a faked `run` never writes.
        topic="hierarchical KV cache tiering",
        ticket="INFERENG-10745",
        no_sources=False,
        version=None,
        max_repos=3,
        dry_run=True,
        no_review=True,
        llm_cmd=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def record_calls(monkeypatch):
    calls = []

    def fake_run(argv, label, allowed=(0,)):
        calls.append([str(a) for a in argv])
        return 0

    monkeypatch.setattr(build, "run", fake_run)
    return calls


def out_values(calls, name):
    """Every `--out` one step was given, by script name."""
    found = []
    for argv in calls:
        if Path(argv[0]).name != name or "--out" not in argv:
            continue
        found.append(argv[argv.index("--out") + 1])
    return found

def test_topic_mode_is_keyed_by_its_slug(tmp_path):
    """A run with no ticket still needs a name of its own, and it is the same
    name its changeset under `docs/` carries."""
    where = build.run_directory(tmp_path, _args(ticket=None, topic="Disconnected mirroring"))
    assert where.name == "disconnected-mirroring"
    assert where.parent == Path(tmp_path)


def test_every_step_is_pointed_at_the_run_directory(tmp_path, monkeypatch):
    calls = record_calls(monkeypatch)
    root = tmp_path / "out"
    root.mkdir()
    args = _args()

    build.build(tmp_path, root, "docs", CONFIG, args, None)

    where = str(build.run_directory(root, args))
    seen = {Path(argv[0]).name for argv in calls if "--out" in argv}
    assert {"analyze.py", "plan.py"} <= seen
    for name in seen:
        assert out_values(calls, name) == [where], f"{name} was not given the run directory"


def test_the_reasoning_trail_lands_in_the_run_directory(tmp_path, monkeypatch):
    """Every step appends to one file, so the trail reads in run order."""
    monkeypatch.delenv(step.TRAIL_ENV, raising=False)
    record_calls(monkeypatch)
    root = tmp_path / "out"
    root.mkdir()
    args = _args()

    build.build(tmp_path, root, "docs", CONFIG, args, None)

    where = build.run_directory(root, args)
    assert os.environ[step.TRAIL_ENV] == str(where / "reasoning.jsonl")


def test_a_caller_naming_its_own_trail_keeps_it(tmp_path, monkeypatch):
    monkeypatch.setenv(step.TRAIL_ENV, str(tmp_path / "mine.jsonl"))
    record_calls(monkeypatch)
    root = tmp_path / "out"
    root.mkdir()

    build.build(tmp_path, root, "docs", CONFIG, _args(), None)

    assert os.environ[step.TRAIL_ENV] == str(tmp_path / "mine.jsonl")

def test_the_vale_workspace_is_per_run_and_its_packages_are_not(tmp_path, monkeypatch):
    """`--sync-styles` downloads the packages once and the repository's own
    `.vale.ini` names that one path, so a run composes against the root while
    building its own workspace below it."""
    seen = {}

    def fake_build(repo, out_dir, config, package_root, packages_dir=None):
        seen["out_dir"] = Path(out_dir)
        seen["packages_dir"] = Path(packages_dir)
        return None, ""

    record_calls(monkeypatch)
    monkeypatch.setattr(workspace, "build", fake_build)
    root = tmp_path / "out"
    root.mkdir()
    args = _args()

    build.build(tmp_path, root, "docs", CONFIG, args, None)

    assert seen["out_dir"] == build.run_directory(root, args)
    assert seen["packages_dir"] == root / workspace.VALE_PACKAGES_DIR

# --------------------------------------------------- a re-run starts from nothing


def test_a_rerun_clears_what_the_last_run_left(tmp_path, monkeypatch):
    """A run that stopped early kept its predecessor's `placement.json` and
    `plan.json`, the steps after it read those as their own, and the artifacts
    then described a run that had not happened."""
    record_calls(monkeypatch)
    root = tmp_path / "out"
    root.mkdir()
    args = _args()
    stale = build.run_directory(root, args)
    (stale / "guides").mkdir(parents=True)
    (stale / "placement.json").write_text('{"targets": ["from the last run"]}')
    (stale / "guides" / "cached.md").write_text("# Stale")

    build.build(tmp_path, root, "docs", CONFIG, args, None)

    assert stale.is_dir(), "the run still needs its directory"
    assert not (stale / "placement.json").exists()
    assert not (stale / "guides").exists()


def test_the_shared_caches_survive_a_rerun(tmp_path):
    """Clearing the run directory must not cost a re-clone or a re-sync."""
    root = tmp_path / "out"
    (root / "checkouts" / "org-repo").mkdir(parents=True)
    (root / "vale-packages" / "RedHat").mkdir(parents=True)
    (root / "checkouts" / "org-repo" / "README").write_text("cloned once")
    where = build.run_directory(root, _args())
    where.mkdir()
    (where / "plan.json").write_text("{}")

    build.clear_run_directory(root, where)

    assert (root / "checkouts" / "org-repo" / "README").is_file()
    assert (root / "vale-packages" / "RedHat").is_dir()
    assert not where.exists()

def test_clearing_a_directory_that_is_not_there_is_fine(tmp_path):
    root = tmp_path / "out"
    root.mkdir()
    build.clear_run_directory(root, root / "NEVER-RUN")


def test_the_artifact_root_itself_is_never_cleared(tmp_path):
    """One check that the wipe is wiping what it thinks it is."""
    root = tmp_path / "out"
    root.mkdir()
    with pytest.raises(ValueError):
        build.clear_run_directory(root, root)
    with pytest.raises(ValueError):
        build.clear_run_directory(root, tmp_path / "elsewhere")
    assert root.is_dir()


# ------------------------------------------------- and so does the changeset


def draft(path, managed="generated", body="# Draft\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nmanaged: {managed}\n---\n\n{body}")
    return path


def changeset_for(repo, name, date="2026-09-01"):
    return Path(repo) / "docs" / f"changeset-{date}-{name}"


def test_a_rerun_clears_the_drafts_the_last_run_wrote(tmp_path):
    where = changeset_for(tmp_path, "TICKET-1")
    draft(where / "new" / "old.md")
    draft(where / "updates" / "guide.edit.md")
    draft(where / "index.md")

    changeset_lib.wipe(tmp_path, "docs", "TICKET-1")

    assert not where.exists(), "nothing was left, so the directory goes too"


def test_a_manual_draft_is_kept_and_keeps_its_directory(tmp_path):
    """The tool promises a draft marked `managed: manual` is left alone, and a
    wipe that took it would be the one thing that broke that promise."""
    where = changeset_for(tmp_path, "TICKET-1")
    draft(where / "new" / "generated.md")
    mine = draft(where / "new" / "mine.md", managed="manual", body="# My own work\n")

    records = changeset_lib.wipe(tmp_path, "docs", "TICKET-1")

    assert mine.is_file()
    assert "My own work" in mine.read_text()
    assert not (where / "new" / "generated.md").exists()
    assert [r["status"] for r in records].count("kept") == 1


def test_a_draft_that_cannot_be_read_is_kept(tmp_path):
    """Broken frontmatter is a reason to leave a file alone, not to delete it."""
    where = changeset_for(tmp_path, "TICKET-1")
    broken = where / "new" / "broken.md"
    broken.parent.mkdir(parents=True)
    broken.write_text("---\ntitle: [unclosed\n---\n\n# Broken\n")

    changeset_lib.wipe(tmp_path, "docs", "TICKET-1")

    assert broken.is_file()


def test_every_dated_directory_for_the_subject_goes(tmp_path):
    """`directory_for` reuses a directory whatever date it carries, so a run
    that spanned two days left two of them."""
    first = changeset_for(tmp_path, "TICKET-1", date="2026-09-01")
    second = changeset_for(tmp_path, "TICKET-1", date="2026-09-15")
    draft(first / "new" / "a.md")
    draft(second / "new" / "b.md")

    changeset_lib.wipe(tmp_path, "docs", "TICKET-1")

    assert not first.exists()
    assert not second.exists()


def test_another_subjects_changeset_is_untouched(tmp_path):
    mine = changeset_for(tmp_path, "TICKET-1")
    theirs = changeset_for(tmp_path, "TICKET-2")
    draft(mine / "new" / "a.md")
    kept = draft(theirs / "new" / "b.md")

    changeset_lib.wipe(tmp_path, "docs", "TICKET-1")

    assert not mine.exists()
    assert kept.is_file()


def test_a_subject_with_no_changeset_yet_is_fine(tmp_path):
    (tmp_path / "docs").mkdir()
    assert changeset_lib.wipe(tmp_path, "docs", "TICKET-1") == []
    assert changeset_lib.wipe(tmp_path, "docs", "") == []


def test_both_clears_run_before_the_first_step(tmp_path, monkeypatch):
    """A clear that ran after a step would take that step's own output."""
    order = []
    root = tmp_path / "out"
    root.mkdir()
    args = _args()
    stale = build.run_directory(root, args)
    stale.mkdir(parents=True)
    (stale / "plan.json").write_text("{}")
    draft(changeset_for(tmp_path, "INFERENG-10745") / "new" / "old.md")

    def fake_run(argv, label, allowed=(0,)):
        order.append(Path(str(argv[0])).name)
        return 0

    monkeypatch.setattr(build, "run", fake_run)
    monkeypatch.setattr(
        build, "clear_run_directory", lambda root, where: order.append("clear-artifacts")
    )
    monkeypatch.setattr(
        build, "clear_changesets", lambda repo, docs_dir, args: order.append("clear-changeset")
    )

    build.build(tmp_path, root, "docs", CONFIG, args, None)

    assert order[:2] == ["clear-artifacts", "clear-changeset"]
    assert "analyze.py" in order

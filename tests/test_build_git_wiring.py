"""build.py must analyse the ticket's own repositories, not wherever it runs.

git_context.py computes a git-context.json for the repository being read
out and throws it away. Meanwhile the old wiring ran `git_context.py` and
`digest.py` against `--repo`, which in topic mode is wherever `build.py` was
invoked -- not the product code a ticket names. This file covers the fix:
digesting the clones' own contexts when they exist, falling back to `--repo`
history only when they do not, and turning the union of their commits into a
`changes.json` that `plan.py` receives.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD = REPO_ROOT / "skills" / "docs" / "scripts"
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
for path in (_ENGINE, _BUILD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build  # noqa: E402


def _args(**over):
    base = dict(
        topic="hierarchical KV cache tiering",
        ticket=None,
        no_sources=False,
        version=None,
        max_repos=3,
        dry_run=True,
        no_review=True,
        llm_cmd=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _config():
    return {"product": "RHOAI", "version": "2.19"}


def run_dir(out_dir, args, monkeypatch):
    """Where `build` writes one run's artifacts, which a test seeds into.

    Each run gets its own directory under the artifact root, and `build`
    empties it before the chain starts so that a re-run cannot read what the
    last one left. These tests fake `run`, so nothing writes the files a real
    step would; the seeded ones stand in for that, and the clear is turned off
    rather than racing it.
    """
    monkeypatch.setattr(build, "clear_run_directory", lambda root, where: None)
    path = build.run_directory(out_dir, args)
    path.mkdir(parents=True, exist_ok=True)
    return path


def fake_run_stopping_at(*labels_containing):
    """A `build.run` fake that records every call and stops the chain once an
    argv containing one of `labels_containing` is reached.

    Which code stops the chain depends on the step. Research answering 1 means
    it found nothing published, which the build carries on past so that
    placement can still say where the subject belongs; only 2 ends the run
    there. Every other step here still stops on 1.
    """
    calls = []

    def fake_run(argv, label, allowed=(0,)):
        argv = [str(a) for a in argv]
        calls.append(argv)
        if any(marker in argv[0] for marker in labels_containing):
            return 2 if "analyze.py" in argv[0] else 1
        return 0

    return calls, fake_run


def commit(**over):
    base = {
        "sha": "a" * 40,
        "short": "aaaaaaa",
        "subject": "unrelated change",
        "body": "",
        "scope": None,
        "type": "chore",
        "breaking": False,
        "pr": None,
        "date": "2026-01-01T00:00:00+00:00",
        "files": [],
    }
    base.update(over)
    return base


def context_json(*commits, **over):
    payload = {
        "schema": "git-context/1",
        "head": "a" * 40,
        "branch": "main",
        "range": {"range": "-n200", "basis": "commit_count_fallback", "base": None},
        "summary": {"commit_count": len(commits)},
        "modules": {},
        "hotspots": [],
        "commits": list(commits),
    }
    payload.update(over)
    return payload


def seed_context(out_dir, *commits):
    """The run's own git-context.json, as the history step would have written it.

    `build.run` is stubbed in these tests, so the real step never runs and this
    stands in for what it produces.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "git-context.json").write_text(json.dumps(context_json(*commits)))


def test_no_ticket_falls_back_to_repo_history(tmp_path, monkeypatch):
    """Nothing clones, so the invoking repository is the only
    source of a git context, and it must still be the invoking directory."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls, fake_run = fake_run_stopping_at("analyze.py")
    monkeypatch.setattr(build, "run", fake_run)
    monkeypatch.setattr(build, "has_history", lambda repo: True)

    build.build(tmp_path, out_dir, "docs", _config(), _args(ticket=None), None)

    context_calls = [c for c in calls if "git_context.py" in c[0]]
    assert len(context_calls) == 1
    assert "--full" in context_calls[0]
    assert "--max-count" in context_calls[0]
    idx = context_calls[0].index("--max-count")
    assert context_calls[0][idx + 1] == str(build.git_context.MAX_COMMITS)


def test_the_configured_issue_prefixes_reach_the_history_read(tmp_path, monkeypatch):
    """`issue_prefixes` was a documented .docs-gen.yaml key that no caller ever
    passed, so extract_issues only ever read trailers and every key written in
    a commit body was missed."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls, fake_run = fake_run_stopping_at("analyze.py")
    monkeypatch.setattr(build, "run", fake_run)
    monkeypatch.setattr(build, "has_history", lambda repo: True)

    config = dict(_config(), issue_prefixes=["RHOAIENG", "PROJ"])
    build.build(tmp_path, out_dir, "docs", config, _args(ticket=None), None)

    argv = next(c for c in calls if "git_context.py" in c[0])
    assert argv[argv.index("--issue-prefix") + 1 : argv.index("--issue-prefix") + 3] == [
        "RHOAIENG",
        "PROJ",
    ]
    assert argv[argv.index("--excludes") + 1].endswith("path_filters.txt")


def test_no_configured_prefixes_passes_no_flag(tmp_path, monkeypatch):
    """An empty `--issue-prefix` would turn the bare-key scan on with nothing
    to scan for."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls, fake_run = fake_run_stopping_at("analyze.py")
    monkeypatch.setattr(build, "run", fake_run)
    monkeypatch.setattr(build, "has_history", lambda repo: True)

    build.build(tmp_path, out_dir, "docs", _config(), _args(ticket=None), None)

    argv = next(c for c in calls if "git_context.py" in c[0])
    assert "--issue-prefix" not in argv


def test_no_history_and_no_clones_leaves_context_untouched(tmp_path, monkeypatch):
    """Both a run with no cloned repositories and a run in a directory with
    no git history at all must keep working: the analysis is evidence, never
    a requirement."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls, fake_run = fake_run_stopping_at("analyze.py")
    monkeypatch.setattr(build, "run", fake_run)
    monkeypatch.setattr(build, "has_history", lambda repo: False)

    code = build.build(tmp_path, out_dir, "docs", _config(), _args(ticket=None), None)

    assert not [c for c in calls if "git_context.py" in c[0]]
    assert not [c for c in calls if "digest.py" in c[0]]
    assert not (out_dir / "changes.json").exists()
    analyze_calls = [c for c in calls if "analyze.py" in c[0]]
    assert "--context" not in analyze_calls[0]
    assert code == 3


def test_selected_commits_reach_plan_as_changes(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    args = _args(ticket=None, topic="hierarchical KV cache tiering")
    where = run_dir(out_dir, args, monkeypatch)
    seed_context(
        where,
        commit(subject="add hierarchical KV cache tiering", short="rel1"),
        commit(subject="bump a dependency", short="irrelevant"),
    )
    monkeypatch.setattr(build, "has_history", lambda repo: True)
    calls, fake_run = fake_run_stopping_at("plan.py")
    monkeypatch.setattr(build, "run", fake_run)

    build.build(tmp_path, out_dir, "docs", _config(), args, None)

    changes_file = where / "changes.json"
    assert changes_file.is_file()
    data = json.loads(changes_file.read_text())
    shas = [c["sha"] for c in data["commits"]]
    assert "rel1" in shas
    assert "irrelevant" not in shas

    plan_calls = [c for c in calls if "plan.py" in c[0]]
    assert len(plan_calls) == 1
    assert "--changes" in plan_calls[0]
    idx = plan_calls[0].index("--changes")
    assert plan_calls[0][idx + 1] == str(changes_file)


def test_selected_commits_reach_write_as_changes(tmp_path, monkeypatch):
    """The writer needs the same evidence the planner does: what a commit
    actually changed, not only what is already published."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    args = _args(ticket=None, topic="hierarchical KV cache tiering", dry_run=False)
    where = run_dir(out_dir, args, monkeypatch)
    seed_context(
        where,
        commit(subject="add hierarchical KV cache tiering", short="rel1"),
        commit(subject="bump a dependency", short="irrelevant"),
    )
    monkeypatch.setattr(build, "has_history", lambda repo: True)
    calls, fake_run = fake_run_stopping_at("write.py")
    monkeypatch.setattr(build, "run", fake_run)

    build.build(tmp_path, out_dir, "docs", _config(), args, None)

    changes_file = where / "changes.json"
    assert changes_file.is_file()

    write_calls = [c for c in calls if "write.py" in c[0]]
    assert len(write_calls) == 1
    assert "--changes" in write_calls[0]
    idx = write_calls[0].index("--changes")
    assert write_calls[0][idx + 1] == str(changes_file)


def test_no_relevant_commits_means_no_changes_file_and_no_flag(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    args = _args(ticket=None, topic="hierarchical KV cache tiering")
    where = run_dir(out_dir, args, monkeypatch)
    seed_context(where, commit(subject="bump a dependency"))
    monkeypatch.setattr(build, "has_history", lambda repo: True)
    calls, fake_run = fake_run_stopping_at("plan.py")
    monkeypatch.setattr(build, "run", fake_run)

    build.build(tmp_path, out_dir, "docs", _config(), args, None)

    assert not (where / "changes.json").exists()
    plan_calls = [c for c in calls if "plan.py" in c[0]]
    assert "--changes" not in plan_calls[0]


def test_no_relevant_commits_means_write_gets_no_flag_either(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    seed_context(out_dir, commit(subject="bump a dependency"))
    calls, fake_run = fake_run_stopping_at("write.py")
    monkeypatch.setattr(build, "run", fake_run)

    build.build(
        tmp_path,
        out_dir,
        "docs",
        _config(),
        _args(ticket="AIPCC-1", topic="hierarchical KV cache tiering", dry_run=False),
        None,
    )

    assert not (out_dir / "changes.json").exists()
    write_calls = [c for c in calls if "write.py" in c[0]]
    assert len(write_calls) == 1
    assert "--changes" not in write_calls[0]

def test_a_ticket_with_no_summary_falls_back_to_topic_only(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    seed_context(out_dir, commit(subject="unrelated"))
    calls, fake_run = fake_run_stopping_at("write.py")
    monkeypatch.setattr(build, "run", fake_run)

    build.build(
        tmp_path,
        out_dir,
        "docs",
        _config(),
        _args(ticket=None, topic="hierarchical KV cache tiering", dry_run=False),
        None,
    )

    write_calls = [c for c in calls if "write.py" in c[0]]
    assert "--topic" in write_calls[0]
    assert "--topic" in write_calls[0]

"""The commit range a context artifact reads must stay bounded.

Measured: 102 untagged commits produced a 212,391-byte git-context.json, and
only the untagged fallback range was ever capped. A repository that tags
rarely, or a caller that passes `--full`, has no ceiling at all today.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lib.git import git_context  # noqa: E402

GIT_CONTEXT_PY = _ENGINE / "lib" / "git" / "git_context.py"


def git_repo(tmp_path, count=5):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for i in range(count):
        (repo / "f.txt").write_text(str(i))
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.email=t@e",
                "-c",
                "user.name=t",
                "commit",
                "-qm",
                f"commit {i}",
            ],
            check=True,
        )
    return repo


def test_max_commits_is_a_defensible_positive_constant():
    """A repository that never tags must still get a ceiling somewhere."""
    assert isinstance(git_context.MAX_COMMITS, int)
    assert 100 <= git_context.MAX_COMMITS <= 1000


def test_read_commits_max_count_wins_over_a_wider_explicit_range(tmp_path):
    repo = git_repo(tmp_path, count=5)
    # 5 commits exist (c0..c4); HEAD~3..HEAD is exclusive of its base and
    # reaches 3 of them (c2, c3, c4) without walking past the root.
    commits = git_context.read_commits(repo, "HEAD~3..HEAD", max_count=1)
    assert len(commits) == 1


def test_read_commits_max_count_wins_over_the_untagged_fallback_range(tmp_path):
    """The fallback range is itself an `-nNNN` flag. A caller's own cap must
    still win, not lose to whichever `-n` git saw first."""
    repo = git_repo(tmp_path, count=5)
    resolved = git_context.default_range(repo, fallback_count=200)
    assert resolved["range"].startswith("-n")
    commits = git_context.read_commits(repo, resolved["range"], max_count=2)
    assert len(commits) == 2


def test_cmd_context_logs_when_the_cap_truncates_the_range(tmp_path):
    repo = git_repo(tmp_path, count=5)
    out = tmp_path / "git-context.json"
    done = subprocess.run(
        [
            sys.executable,
            str(GIT_CONTEXT_PY),
            "context",
            "--repo",
            str(repo),
            "--range",
            "HEAD~3..HEAD",
            "--max-count",
            "1",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0
    payload = json.loads(out.read_text())
    assert len(payload["commits"]) == 1
    assert "capped" in done.stderr.lower() or "exceeds" in done.stderr.lower()


def test_cmd_context_is_silent_when_the_cap_does_not_truncate(tmp_path):
    repo = git_repo(tmp_path, count=5)
    out = tmp_path / "git-context.json"
    done = subprocess.run(
        [
            sys.executable,
            str(GIT_CONTEXT_PY),
            "context",
            "--repo",
            str(repo),
            "--range",
            "HEAD~3..HEAD",
            "--max-count",
            "50",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0
    payload = json.loads(out.read_text())
    assert len(payload["commits"]) == 3
    assert done.stderr.strip() == ""


def test_full_includes_per_commit_files(tmp_path):
    """The join `commit_select` needs: which files a commit touched."""
    repo = git_repo(tmp_path, count=2)
    out = tmp_path / "git-context.json"
    done = subprocess.run(
        [
            sys.executable,
            str(GIT_CONTEXT_PY),
            "context",
            "--repo",
            str(repo),
            "--full",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0
    payload = json.loads(out.read_text())
    assert "files" in payload["commits"][0]


def test_without_full_files_are_stripped_from_commits(tmp_path):
    repo = git_repo(tmp_path, count=2)
    out = tmp_path / "git-context.json"
    subprocess.run(
        [sys.executable, str(GIT_CONTEXT_PY), "context", "--repo", str(repo), "--out", str(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(out.read_text())
    assert "files" not in payload["commits"][0]


def test_a_repository_with_no_history_at_all_still_exits_cleanly(tmp_path):
    """The git analysis is evidence, never a requirement."""
    repo = tmp_path / "empty"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    out = tmp_path / "git-context.json"
    done = subprocess.run(
        [sys.executable, str(GIT_CONTEXT_PY), "context", "--repo", str(repo), "--out", str(out)],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 1


def test_fetched_reports_the_exit_status(tmp_path):
    repo = git_repo(tmp_path, count=1)
    assert git_context.fetched(repo, "refs/heads/nope") is False


def test_churn_refuses_an_unresolvable_range(tmp_path):
    """cmd_commits and cmd_changes both stop here. cmd_churn passed None into
    read_commits, which drops the range and the max-count and logs the whole
    repository, then emitted hotspots for all of it."""
    repo = git_repo(tmp_path, count=3)
    out = tmp_path / "o.json"
    done = subprocess.run(
        [
            sys.executable,
            str(GIT_CONTEXT_PY),
            "churn",
            "--repo",
            str(repo),
            "--since-sha",
            "0" * 40,
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 1
    assert json.loads(done.stdout)["range"] is None
    assert not out.exists(), "an unresolved range must not write a whole-history ranking"

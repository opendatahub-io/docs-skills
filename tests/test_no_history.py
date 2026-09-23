"""docs: a directory with no git history still gets documented.

`has_history` is the guard. Without it the run tracebacks out of git_context
before reaching the analyzer, which is the step that needs no history at all:
a repository that has never been committed still has modules and a public API,
and those are what a page rests on.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_BUILD = Path(__file__).resolve().parent.parent / "skills" / "docs" / "scripts" / "build.py"


def _sources(root):
    pkg = root / "pkg" / "queue"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "queue.py").write_text(
        'def push(item):\n    """Add an item to the queue."""\n    return item\n'
    )
    return root


def _run(repo):
    return subprocess.run(
        [
            sys.executable,
            str(_BUILD),
            "--repo",
            str(repo),
            "--topic",
            "queues",
            "--dry-run",
            "--llm-cmd",
            "false",
        ],
        capture_output=True,
        text=True,
    )


def test_a_directory_with_no_git_repository_reaches_the_analyzer(tmp_path):
    done = _run(_sources(tmp_path / "repo"))
    assert "Traceback" not in done.stderr, done.stderr
    assert done.returncode in (0, 1, 3), done.stderr
    assert "docs-repo-analyze" in done.stderr or "analyzing" in done.stderr


def test_a_git_repository_with_no_commits_reaches_the_analyzer(tmp_path):
    repo = _sources(tmp_path / "repo")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    done = _run(repo)
    assert "Traceback" not in done.stderr, done.stderr
    assert done.returncode in (0, 1, 3), done.stderr


def test_the_run_says_it_has_no_history_rather_than_failing(tmp_path):
    done = _run(_sources(tmp_path / "repo"))
    assert "no repository context" in done.stderr or "history" in done.stderr.lower()

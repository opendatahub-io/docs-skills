"""End-to-end: history, fingerprints, relevance, writing, review, changelog.

Runs against a synthetic repository with a known history, so every verdict has
one right answer. No model is involved: the writer's llm-cmd is a script that
returns a fixed document, which is what makes the ownership guards testable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

LIB = _ROOT / "lib"
SKILLS = _ROOT / "skills"
FIXTURE = Path(__file__).parent / "fixtures" / "make_python_fixture.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is required for the pipeline tests"
)


def run(*argv, cwd=None, check=True):
    completed = subprocess.run(
        [sys.executable, *[str(a) for a in argv]],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if check and completed.returncode != 0:
        raise AssertionError(f"{argv[0]} exited {completed.returncode}\n{completed.stderr[-3000:]}")
    return completed


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / "fixture"
    subprocess.run(["bash", str(FIXTURE), str(target)], check=True, capture_output=True)
    return target


@pytest.fixture
def artifacts(repo, tmp_path):
    """The deterministic half of the chain, run once for the whole module."""
    out = tmp_path / "artifacts"
    out.mkdir()
    registry = repo / "registry.json"

    run(
        LIB / "git" / "api_surface.py",
        "snapshot",
        "--repo",
        repo,
        "--registry",
        registry,
        "--at",
        "v0.1.0",
        "--out",
        out / "before.json",
    )
    run(
        LIB / "git" / "api_surface.py",
        "snapshot",
        "--repo",
        repo,
        "--registry",
        registry,
        "--out",
        out / "api-surface.json",
    )
    run(
        LIB / "git" / "api_surface.py",
        "diff",
        "--before",
        out / "before.json",
        "--after",
        out / "api-surface.json",
        "--out",
        out / "api-diff.json",
    )
    run(
        LIB / "git" / "git_context.py",
        "context",
        "--repo",
        repo,
        "--registry",
        registry,
        "--excludes",
        _ROOT / "config" / "path_filters.txt",
        "--out",
        out / "git-context.json",
    )
    run(
        LIB / "git" / "api_surface.py",
        "relevance",
        "--git-context",
        out / "git-context.json",
        "--api-diff",
        out / "api-diff.json",
        "--out",
        out / "relevance.json",
    )
    return out


def load(path):
    return json.loads(Path(path).read_text())


# ------------------------------------------------------------------ relevance


def test_range_falls_back_to_the_last_tag(artifacts):
    assert load(artifacts / "git-context.json")["range"]["basis"] == "since_last_tag"


def test_a_signature_change_rebuilds_its_module(artifacts):
    modules = load(artifacts / "relevance.json")["modules"]
    assert modules["core"]["verdict"] == "rebuild"
    assert modules["core"]["breaking"] is True


def test_a_reformat_is_invisible_to_the_fingerprint(artifacts):
    """Whitespace normalization is what makes a reformat cost nothing."""
    assert load(artifacts / "relevance.json")["modules"]["util"]["verdict"] == "skip"


def test_a_prose_only_change_skips(artifacts):
    assert load(artifacts / "relevance.json")["modules"]["docs"]["verdict"] == "skip"


def test_nothing_is_escalated_for_human_review(artifacts):
    assert load(artifacts / "relevance.json")["review"] == []


def test_a_new_public_symbol_appears_in_the_diff(artifacts):
    added = load(artifacts / "api-diff.json")["modules"]["core"]["added"]
    assert any("disconnect" in entry for entry in added)


def test_private_symbols_never_reach_the_surface(artifacts):
    symbols = load(artifacts / "api-surface.json")["modules"]["core"]["symbols"]
    assert not any("_private" in key for key in symbols)


def test_trailers_survive_a_breaking_change_block(artifacts):
    """Git rejects a trailer block holding a key with a space, so `Fixes:`
    would otherwise be lost as collateral alongside `BREAKING CHANGE:`."""
    assert "ABC-1" in load(artifacts / "git-context.json")["summary"]["issues"]


def test_the_breaking_change_is_recorded(artifacts):
    assert load(artifacts / "git-context.json")["summary"]["breaking_changes"]


# ------------------------------------------------------------------ changelog


def test_changelog_is_written_without_a_model(repo, artifacts):
    result = run(
        SKILLS / "changelog" / "scripts" / "changelog.py",
        "--context",
        artifacts / "git-context.json",
        "--repo",
        repo,
        "--version",
        "v0.2.0",
    )
    assert "deterministic" in result.stderr
    text = (repo / "CHANGELOG.md").read_text()
    assert "## v0.2.0" in text
    assert "### Breaking changes" in text
    assert "retime connect and add disconnect" in text


def test_changelog_is_idempotent(repo, artifacts):
    argv = (
        SKILLS / "changelog" / "scripts" / "changelog.py",
        "--context",
        artifacts / "git-context.json",
        "--repo",
        repo,
        "--version",
        "v0.2.0",
    )
    run(*argv)
    once = (repo / "CHANGELOG.md").read_text()
    run(*argv)
    assert (repo / "CHANGELOG.md").read_text() == once


def test_changelog_keeps_a_hand_written_preamble(repo, artifacts):
    argv = (
        SKILLS / "changelog" / "scripts" / "changelog.py",
        "--context",
        artifacts / "git-context.json",
        "--repo",
        repo,
    )
    run(*argv)
    text = (repo / "CHANGELOG.md").read_text()
    (repo / "CHANGELOG.md").write_text(
        text.replace("# Changelog\n", "# Changelog\n\nRead the upgrade guide first.\n")
    )
    run(*argv)
    assert "Read the upgrade guide first." in (repo / "CHANGELOG.md").read_text()


# ----------------------------------------------------------------- the writer


WRITER_REPLY = {
    "path": "docs/core.md",
    "frontmatter": {
        "title": "Core",
        "description": "Opening and closing connections.",
        "type": "concept",
    },
    "sections": [
        {
            "id": "purpose",
            "heading": "What it does",
            "body": "Call `connect` to open a connection and `disconnect` to close it.",
            "symbols": ["connect", "disconnect"],
        },
        {
            "id": "api",
            "heading": "Entry points",
            "body": "`Client` wraps a host. Its `send` method echoes the payload.",
            "symbols": ["Client", "send"],
        },
    ],
    "evidence": ["core/api.py:1"],
    "gaps": [],
}


@pytest.fixture
def fake_llm(tmp_path):
    """A stand-in writer that always returns the same document.

    Determinism is the point: it lets the ownership and churn-floor guards be
    tested without the run depending on a model being available.
    """
    script = tmp_path / "fake_llm.py"
    script.write_text(f"import sys, json\nsys.stdin.read()\nprint(json.dumps({WRITER_REPLY!r}))\n")
    return f"{sys.executable} {script}"


@pytest.fixture
def written(repo, artifacts, fake_llm):
    """A registry plus one generated document, ready for the ownership tests."""
    run(
        SKILLS / "repo-analyze" / "scripts" / "analyze.py",
        "--repo",
        repo,
        "--out",
        artifacts,
    )
    run(
        SKILLS / "docs-write" / "scripts" / "write.py",
        "--repo",
        repo,
        "--out",
        artifacts,
        "--docs-dir",
        "docs",
        "--modules",
        "core",
        "--llm-cmd",
        fake_llm,
    )
    return repo / "docs" / "core.md"


def test_a_new_document_is_created_and_stamped(written):
    assert written.exists()
    text = written.read_text()
    assert "managed: generated" in text
    assert "source_modules:" in text
    assert "generator: docs-skills" in text


def test_a_second_run_with_no_source_change_writes_nothing(repo, artifacts, fake_llm, written):
    """The idempotency requirement. A rerun must produce an empty diff."""
    before = written.read_text()
    run(
        SKILLS / "docs-write" / "scripts" / "write.py",
        "--repo",
        repo,
        "--out",
        artifacts,
        "--docs-dir",
        "docs",
        "--modules",
        "core",
        "--llm-cmd",
        fake_llm,
        check=False,
    )
    assert written.read_text() == before
    report = load(artifacts / "write-report.json")
    assert report["written"] == []
    assert report["unchanged"]


def test_a_manual_document_is_never_written(repo, artifacts, fake_llm, written):
    """The guarantee the whole design rests on."""
    written.write_text("---\ntitle: Core\nmanaged: manual\n---\n# Core\n\nA human wrote this.\n")
    original = written.read_text()
    run(
        SKILLS / "docs-write" / "scripts" / "write.py",
        "--repo",
        repo,
        "--out",
        artifacts,
        "--docs-dir",
        "docs",
        "--modules",
        "core",
        "--llm-cmd",
        fake_llm,
        check=False,
    )
    assert written.read_text() == original
    refused = load(artifacts / "write-report.json")["refused"]
    assert any("manual" in record["reason"] for record in refused)


def test_an_assisted_document_keeps_everything_outside_its_fences(
    repo, artifacts, fake_llm, written
):
    written.write_text(
        "---\ntitle: Core\nmanaged: assisted\n---\n"
        "# Core\n\n"
        "A paragraph a human owns and expects to survive.\n\n"
        "<!-- docs-gen:begin section=api source=core sha=0000000 -->\n"
        "stale generated text\n"
        "<!-- docs-gen:end -->\n\n"
        "Closing prose the human also owns.\n"
    )
    run(
        SKILLS / "docs-write" / "scripts" / "write.py",
        "--repo",
        repo,
        "--out",
        artifacts,
        "--docs-dir",
        "docs",
        "--modules",
        "core",
        "--llm-cmd",
        fake_llm,
        check=False,
    )
    after = written.read_text()
    assert "A paragraph a human owns and expects to survive." in after
    assert "Closing prose the human also owns." in after
    assert "stale generated text" not in after
    assert "`Client` wraps a host." in after
    # The `purpose` section has no fence to land in, so it is dropped rather
    # than appended somewhere a human did not ask for it.
    assert "Call `connect` to open a connection" not in after


# ------------------------------------------------------------------ the review


def test_review_catches_an_identifier_that_does_not_exist(repo, artifacts, written):
    written.write_text(
        written.read_text().replace(
            "`Client` wraps a host.", "`Client` wraps a host. Call `reconnect` to retry."
        )
    )
    result = run(
        SKILLS / "docs-review" / "scripts" / "review.py",
        "--repo",
        repo,
        "--out",
        artifacts,
        "--docs-dir",
        "docs",
        check=False,
    )
    assert result.returncode == 3
    findings = load(artifacts / "review.json")["findings"]
    assert any(
        f["kind"] == "ungrounded-identifier" and f.get("symbol") == "reconnect" for f in findings
    )


def test_review_accepts_a_grounded_document(repo, artifacts, written):
    result = run(
        SKILLS / "docs-review" / "scripts" / "review.py",
        "--repo",
        repo,
        "--out",
        artifacts,
        "--docs-dir",
        "docs",
        check=False,
    )
    errors = [f for f in load(artifacts / "review.json")["findings"] if f["severity"] == "error"]
    assert errors == [], errors
    assert result.returncode == 0


def test_review_flags_a_stale_hand_written_page(repo, artifacts, written):
    """A manual page whose subject moved becomes a finding, never a rewrite."""
    (repo / "docs" / "handbook.md").write_text(
        "---\ntitle: Handbook\ndescription: How we run this\nmanaged: manual\n"
        "source_modules:\n  - core\n---\n# Handbook\n\nHand-written.\n"
    )
    run(
        SKILLS / "docs-review" / "scripts" / "review.py",
        "--repo",
        repo,
        "--out",
        artifacts,
        "--docs-dir",
        "docs",
        check=False,
    )
    findings = load(artifacts / "review.json")["findings"]
    assert any(f["kind"] == "stale-manual" for f in findings)


def test_review_ignores_identifiers_inside_code_blocks(repo, artifacts, written):
    """An example names the caller's own variables. Flagging those is noise."""
    written.write_text(
        written.read_text() + "\n```python\nmy_local_handle = connect('example.com')\n```\n"
    )
    run(
        SKILLS / "docs-review" / "scripts" / "review.py",
        "--repo",
        repo,
        "--out",
        artifacts,
        "--docs-dir",
        "docs",
        check=False,
    )
    findings = load(artifacts / "review.json")["findings"]
    assert not any(f.get("symbol") == "my_local_handle" for f in findings)


# -------------------------------------------------------------------- the sync


def test_sync_dry_run_names_the_modules_it_would_write(repo, tmp_path):
    result = run(
        SKILLS / "docs-sync" / "scripts" / "sync.py",
        "--repo",
        repo,
        "--out",
        tmp_path / "sync-out",
        "--bootstrap",
        "--dry-run",
        check=False,
    )
    assert result.returncode == 0
    assert "core" in result.stderr


def test_sync_loop_guard_stops_on_a_docs_only_commit(repo, tmp_path):
    """A docs pull request merges, becomes a push, and must not retrigger."""
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "note.md").write_text("# note\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "f@e.com"}
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "docs: sync"], check=True, env=env)
    result = run(
        SKILLS / "docs-sync" / "scripts" / "sync.py",
        "--repo",
        repo,
        "--out",
        tmp_path / "sync-out",
        check=False,
    )
    assert result.returncode == 1
    assert "every changed path is one this tool writes" in result.stderr


def test_sync_loop_guard_stops_on_a_committed_artifact_change(repo, tmp_path):
    """`.docs-gen/` is committed, so a docs merge touches it on the way back."""
    (repo / ".docs-gen").mkdir(exist_ok=True)
    (repo / ".docs-gen" / "registry.json").write_text("{}\n")
    (repo / ".docs-state.json").write_text("{}\n")
    env = {**os.environ, "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "f@e.com"}
    subprocess.run(["git", "-C", str(repo), "add", "-Af"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "docs: artifacts"],
        check=True,
        env=env,
    )
    result = run(
        SKILLS / "docs-sync" / "scripts" / "sync.py",
        "--repo",
        repo,
        "--out",
        tmp_path / "sync-out",
        check=False,
    )
    assert result.returncode == 1


def test_sync_loop_guard_stops_on_the_bot_identity(repo, tmp_path):
    (repo / ".docs-gen.yaml").write_text("generate:\n  bot_author: docs-bot@example.com\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "docs-bot",
        "GIT_AUTHOR_EMAIL": "docs-bot@example.com",
        "GIT_COMMITTER_NAME": "docs-bot",
        "GIT_COMMITTER_EMAIL": "docs-bot@example.com",
    }
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "chore: bot touched src"],
        check=True,
        env=env,
    )
    result = run(
        SKILLS / "docs-sync" / "scripts" / "sync.py",
        "--repo",
        repo,
        "--out",
        tmp_path / "sync-out",
        check=False,
    )
    assert result.returncode == 1
    assert "bot identity" in result.stderr


# ----------------------------------------------------------------- the registry


def test_registry_hash_is_stable_across_runs(repo, tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    for out in (first, second):
        run(SKILLS / "repo-analyze" / "scripts" / "analyze.py", "--repo", repo, "--out", out)
    assert (
        load(first / "registry.json")["registry_hash"]
        == (load(second / "registry.json")["registry_hash"])
    )


def test_analyze_skips_when_the_registry_hash_matches(repo, tmp_path):
    out = tmp_path / "cached"
    run(SKILLS / "repo-analyze" / "scripts" / "analyze.py", "--repo", repo, "--out", out)
    again = run(
        SKILLS / "repo-analyze" / "scripts" / "analyze.py",
        "--repo",
        repo,
        "--out",
        out,
        "--skip-cached",
        check=False,
    )
    assert again.returncode == 1
    assert "unchanged" in again.stderr

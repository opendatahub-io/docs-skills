"""The git-context digest.

The artifact these tests exercise exists to be read by a model, so the
assertions are about size and citability rather than exact wording.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_ENGINE = Path(__file__).resolve().parent.parent / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lib.git import digest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def context(**overrides):
    """A git-context payload shaped like the real one, at realistic scale."""
    payload = {
        "schema": "git-context/1",
        "head": "74748a1f3c2b9e0d5a6f7c8b9a0d1e2f3a4b5c6d",
        "branch": "main",
        "range": {"range": "-n200", "basis": "commit_count_fallback", "base": None},
        "summary": {
            "commit_count": 200,
            "conventional_ratio": 0.845,
            "types": {"fix": 93, "feat": 42, "docs": 14, "refactor": 8},
            "authors": {"A Writer": 151, "Another Writer": 49},
            "pull_requests": [1, 6, 13, 42],
            "issues": [],
            "breaking_changes": [],
        },
        "modules": {},
        "hotspots": [
            {"path": f"src/module_{i}.py", "churn": 100 - i, "commits": 30 - i, "module": None}
            for i in range(30)
        ],
    }
    payload.update(overrides)
    return payload


def bullets(text):
    return [line for line in text.splitlines() if line.startswith("- ")]


def test_every_bullet_carries_a_source():
    """DocsNotes.CitationRequired fails any bullet without one, so none may ship."""
    for line in bullets(digest.render(context())):
        assert "[src:" in line or "https://" in line, line


def test_stays_far_under_the_word_budget():
    text = digest.render(context())
    assert len(text.split()) < 600


def test_hotspots_are_capped():
    text = digest.render(context(), hotspots=5)
    assert len([b for b in bullets(text) if "churn" in b]) == 5


def test_no_registry_is_stated_rather_than_left_blank():
    """An empty Modules section reads as a bug. An explicit line reads as a fact."""
    text = digest.render(context())
    assert "no module registry" in text.lower()


def test_modules_are_ranked_by_churn():
    payload = context(
        modules={
            "small": {"files": ["a.py"], "adds": 1, "dels": 1, "commits": ["s1"]},
            "large": {"files": ["b.py"], "adds": 900, "dels": 100, "commits": ["s1", "s2"]},
        }
    )
    text = digest.render(payload)
    assert text.index("large:") < text.index("small:")


def test_frontmatter_types_the_document():
    text = digest.render(context())
    assert text.startswith("---\n")
    assert "type: reference" in text
    assert "managed: generated" in text


def test_empty_context_still_renders():
    """A repository with no reachable range must not crash the pipeline."""
    text = digest.render({})
    assert text.startswith("---\n")
    assert bullets(text)


def test_cli_writes_the_file(tmp_path):
    source = tmp_path / "git-context.json"
    source.write_text(json.dumps(context()))
    target = tmp_path / "git-context.md"
    assert digest.main(["--context", str(source), "--out", str(target)]) == 0
    assert "[src:" in target.read_text()


@pytest.mark.skipif(shutil.which("vale") is None, reason="vale is not installed")
def test_digest_lints_clean_under_orcnotes(tmp_path):
    """The whole point: this artifact passes the voice it is written for."""
    config = tmp_path / "config.ini"
    config.write_text(
        f"StylesPath = {REPO_ROOT / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n"
        "[*.md]\nBasedOnStyles = DocsNotes\n"
    )
    target = tmp_path / "git-context.md"
    target.write_text(digest.render(context()))
    done = subprocess.run(
        ["vale", "--config", str(config), "--output=JSON", str(target)],
        capture_output=True,
        text=True,
    )
    assert done.stdout.strip() == "{}", done.stdout


def test_render_many_labels_each_repository_in_order():
    text = digest.render_many(
        [("repo-one", context(hotspots=[])), ("repo-two", context(hotspots=[]))]
    )
    assert text.index("# repo-one") < text.index("# repo-two")


def test_render_many_carries_one_frontmatter_only():
    text = digest.render_many([("repo-one", context()), ("repo-two", context())])
    assert text.count("managed: generated") == 1


def test_render_many_shares_the_single_repository_budget():
    """Two repositories must not simply double the single-repository output."""
    solo = digest.render(context(), hotspots=6)
    solo_churn = len([b for b in bullets(solo) if "churn" in b])
    combined = digest.render_many([("a", context()), ("b", context())], hotspots=6)
    combined_churn = len([b for b in bullets(combined) if "churn" in b])
    assert combined_churn <= solo_churn


def test_render_many_with_no_repositories_still_renders():
    text = digest.render_many([])
    assert text.startswith("---\n")


def test_cli_merges_several_labelled_contexts(tmp_path):
    one = tmp_path / "one.json"
    two = tmp_path / "two.json"
    one.write_text(json.dumps(context()))
    two.write_text(json.dumps(context()))
    target = tmp_path / "git-context.md"
    code = digest.main(
        [
            "--context",
            str(one),
            "--label",
            "repo-one",
            "--context",
            str(two),
            "--label",
            "repo-two",
            "--out",
            str(target),
        ]
    )
    assert code == 0
    text = target.read_text()
    assert "# repo-one" in text and "# repo-two" in text


def test_cli_rejects_a_context_and_label_count_mismatch(tmp_path):
    one = tmp_path / "one.json"
    one.write_text(json.dumps(context()))
    two = tmp_path / "two.json"
    two.write_text(json.dumps(context()))
    target = tmp_path / "git-context.md"
    code = digest.main(
        [
            "--context",
            str(one),
            "--context",
            str(two),
            "--label",
            "repo-one",
            "--out",
            str(target),
        ]
    )
    assert code == 2


def test_cli_rejects_several_contexts_with_no_labels(tmp_path):
    one = tmp_path / "one.json"
    one.write_text(json.dumps(context()))
    two = tmp_path / "two.json"
    two.write_text(json.dumps(context()))
    target = tmp_path / "git-context.md"
    code = digest.main(["--context", str(one), "--context", str(two), "--out", str(target)])
    assert code == 2

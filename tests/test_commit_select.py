"""Selecting which commits matter to a documentation subject.

The ticket key is not a usable selector: measured on this repository, 102
untagged commits yielded an empty `summary.issues`. Commits are scored against
the subject the same deterministic way `excerpt.relevant()` scores a page's
sections and `write.py`'s `code_context()` scores API symbols, before any
model call, then capped at a count rather than a byte budget because commit
records are short and uniform.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lib.git import commit_select  # noqa: E402


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


def test_a_subject_hit_outranks_a_miss():
    hit = commit(subject="add hierarchical KV cache tiering", short="hit")
    miss = commit(subject="bump a dependency", short="miss")
    ranked = commit_select.select_commits([miss, hit], "KV cache tiering")
    assert ranked[0]["short"] == "hit"


def test_a_subject_hit_outranks_a_body_only_hit():
    """The subject line is weighted highest."""
    subject_hit = commit(subject="add KV cache tiering", body="", short="subj")
    body_hit = commit(subject="unrelated change", body="touches KV cache tiering", short="body")
    ranked = commit_select.select_commits([body_hit, subject_hit], "KV cache tiering")
    assert ranked[0]["short"] == "subj"


def test_a_scope_hit_outranks_a_body_only_hit():
    """Scope is usually a module name and outweighs a passing body mention."""
    scope_hit = commit(subject="update config", scope="tiering", body="", short="scope")
    body_hit = commit(subject="update config", body="mentions tiering in passing", short="body")
    ranked = commit_select.select_commits([body_hit, scope_hit], "tiering")
    assert ranked[0]["short"] == "scope"


def test_a_path_hit_contributes_to_the_score():
    path_hit = commit(
        subject="update code", files=[{"path": "src/tiering/engine.py"}], short="path"
    )
    miss = commit(subject="update code", files=[{"path": "src/unrelated/engine.py"}], short="miss")
    ranked = commit_select.select_commits([miss, path_hit], "tiering")
    assert ranked[0]["short"] == "path"


def test_breaking_outranks_an_equally_scoring_non_breaking_commit():
    """A breaking change is a documentation requirement on its own."""
    plain = commit(subject="add tiering support", breaking=False, short="plain")
    breaking = commit(subject="add tiering support", breaking=True, short="breaking")
    ranked = commit_select.select_commits([plain, breaking], "tiering")
    assert ranked[0]["short"] == "breaking"


def test_breaking_does_not_outrank_a_higher_scoring_commit():
    """The tie-break applies only when scores are equal."""
    strong = commit(subject="tiering tiering tiering", breaking=False, short="strong")
    weak_breaking = commit(subject="unrelated", breaking=True, short="weak")
    ranked = commit_select.select_commits([weak_breaking, strong], "tiering")
    assert ranked[0]["short"] == "strong"


def test_a_zero_scoring_commit_is_excluded_when_the_subject_has_terms():
    unrelated = commit(subject="bump a dependency")
    ranked = commit_select.select_commits([unrelated], "KV cache tiering")
    assert ranked == []


def test_selection_is_capped_at_the_limit():
    commits = [commit(subject=f"tiering change {i}", short=f"c{i:06d}") for i in range(50)]
    ranked = commit_select.select_commits(commits, "tiering", limit=10)
    assert len(ranked) == 10


def test_an_empty_subject_keeps_original_order_up_to_the_limit():
    """With no subject there is nothing to score against, so recency (the
    order `git log` already returns) stands in rather than an empty result."""
    commits = [commit(short=f"c{i}") for i in range(5)]
    ranked = commit_select.select_commits(commits, "", limit=3)
    assert [c["short"] for c in ranked] == ["c0", "c1", "c2"]


def test_a_commit_missing_optional_fields_does_not_crash():
    bare = {"subject": "tiering support", "short": "z1"}
    ranked = commit_select.select_commits([bare], "tiering")
    assert ranked[0]["short"] == "z1"


def test_no_commits_returns_an_empty_list():
    assert commit_select.select_commits([], "tiering") == []


def test_default_limit_is_within_the_surveyed_range():
    """The survey suggests roughly 20 to 40, matching digest.py's hotspot scale."""
    assert 20 <= commit_select.DEFAULT_LIMIT <= 40


# ------------------------------------------------ substring scoring (RHOAIENG-82726)
#
# A commit message is prose that names identifiers: its scope and its file
# paths are pure identifiers, and compounds are the norm there the way they
# are in `write.py`'s `code_context()`, not the way they are in published
# prose. Set intersection -- correct for `excerpt.score()`, which scores
# published prose where words stand alone -- silently drops the commit that
# performs the exact rename a ticket is about, because "kubeflow" is not a
# whole-token match inside "kubeflowsparkoperator" and "component" is not
# "components".

SUBJECT_TERMS = "kubeflow spark operator component key"

RENAME_COMMIT = commit(
    subject="fix: rename kubeflowsparkoperator to sparkoperator",
    scope="sparkoperator",
    files=[{"path": "api/components/v1alpha1/sparkoperator_types.go"}],
    short="a1",
)


def test_the_rename_commit_scores_above_zero():
    """Reproduces the ticket's own shape: this is the commit a writer most
    needs, and set intersection scored it zero."""
    assert commit_select.score(RENAME_COMMIT, commit_select._words(SUBJECT_TERMS)) > 0


def test_the_rename_commit_is_selected_for_its_subject():
    ranked = commit_select.select_commits([RENAME_COMMIT], SUBJECT_TERMS)
    assert ranked and ranked[0]["short"] == "a1"


def test_ranking_puts_the_rename_and_breaking_commits_above_an_unrelated_bump():
    breaking = commit(
        subject="rename the KubeflowSparkOperator component key",
        breaking=True,
        short="breaking",
    )
    bump = commit(subject="chore: bump dependencies", short="bump")
    ranked = commit_select.select_commits([bump, RENAME_COMMIT, breaking], SUBJECT_TERMS)
    shorts = [c["short"] for c in ranked]
    assert "bump" not in shorts
    assert set(shorts) == {"a1", "breaking"}


def test_a_partial_word_match_is_credited():
    """`spark` matches `sparkoperator` and `component` matches `components`,
    the same substring containment `code_context()` already uses."""
    wanted = commit_select._words("spark component")
    hit = commit(subject="rename sparkoperator", scope="components", short="hit")
    assert commit_select.score(hit, wanted) > 0


# ---------------------------------------------------------------- term rarity

# Forty commits that all carry `doc`, several times each, and one that carries
# `placed` once. Raw hit counts put the noise first. Rarity puts the signal
# first. This is the shape of the real failure, cut down to a fixture.
NOISE = {
    "subject": "chore: update the docs and the docstrings under docs-gen",
    "body": "",
    "scope": "docs",
    "files": [{"path": "docs/x.md"}],
}
PLACED = {
    "subject": "feat: sections are placed by the chain",
    "body": "",
    "scope": "",
    "files": [{"path": "skills/place/run.py"}],
}
SUBJECT = "how documents are placed in the doc set"


def corpus(size=40):
    return [dict(NOISE) for _ in range(size)] + [PLACED]


def test_a_term_the_whole_corpus_carries_stops_deciding():
    """`doc` matched `docs-`, `docstrings` and `.docs-gen` at full weight, and
    the commits actually about placement lost to cleanup and docstrings."""
    assert commit_select.select_commits(corpus(), SUBJECT)[0] is PLACED


def test_the_unweighted_ranking_misses_it():
    """The behaviour this replaced, held up so the change has a witness."""
    wanted = commit_select._words(SUBJECT)
    flat = sorted(corpus(), key=lambda c: -commit_select.score(c, wanted))
    assert flat[0] is not PLACED


def test_a_small_corpus_is_not_weighted():
    """Rarity is a statistic, and nine commits carry none of it."""
    weights = commit_select.term_weights(corpus(5), {"doc", "placed"})
    assert set(weights.values()) == {1.0}


def test_a_rare_term_outweighs_a_common_one():
    weights = commit_select.term_weights(corpus(), {"doc", "placed"})
    assert weights["placed"] > weights["doc"]
    assert weights["doc"] < 0.5


def test_weighting_leaves_the_score_alone_when_every_term_is_equal():
    """The weighted score with every weight at 1 is the score from before."""
    wanted = commit_select._words("placed sections")
    flat = {word: 1.0 for word in wanted}
    assert commit_select.score(PLACED, wanted) > 0
    assert commit_select.score(PLACED, wanted) == commit_select.score(PLACED, wanted, flat)


def test_a_subject_whose_every_term_is_everywhere_still_ranks():
    """Weighted, every one of these scores zero. Returning nothing is wrong."""
    commits = [dict(NOISE) for _ in range(40)]
    commits[7] = {**NOISE, "body": "docs again, and the docs after that"}
    ranked = commit_select.select_commits(commits, "docs")
    assert ranked
    assert ranked[0] is commits[7]

#!/usr/bin/env python3
"""Rank commits by how closely they match a documentation subject."""

from __future__ import annotations

import math
import re

# Words that match most subjects and therefore select nothing.
_STOP = {
    "the",
    "and",
    "for",
    "with",
    "how",
    "use",
    "using",
    "from",
    "into",
    "not",
    "does",
    "this",
    "that",
    "its",
    "can",
    "are",
    "was",
    "add",
    "adds",
    "added",
    "update",
    "updates",
    "updated",
    "fix",
    "fixes",
    "fixed",
    "change",
    "changes",
    "changed",
}

# Roughly the scale `digest.py` already uses for its hotspot and module
# rankings (20 and 15 respectively), so a "relevant history" list reads at
# about the same length as the sections a writer already sees.
DEFAULT_LIMIT = 30

# A commit is filed under its subject line, so a hit there is the strongest
# signal. Scope is usually a module name, more specific than free text. A path
# hit shows a commit touched relevant code whatever its prose says.
SUBJECT_WEIGHT = 3
SCOPE_WEIGHT = 2
BODY_WEIGHT = 1
PATH_WEIGHT = 1


def _words(text):
    """Lowercase word tokens worth matching on, three characters or longer."""
    found = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {word for word in found if len(word) > 2 and word not in _STOP}


def _paths(files):
    """The file paths on a commit, lowercased, for substring matching."""
    return [(entry or {}).get("path") or "" for entry in files or ()]


def _has(word, text):
    """1 when `word` appears as a substring of `text`, 0 otherwise."""
    return 1 if word and word in (text or "").lower() else 0


# Rarity is a statistic about a corpus, and a handful of commits carries none
# of it. Below this many, every term counts the same, which is how the ranking
# worked before and what the small fixtures in the tests expect.
MIN_CORPUS = 10


def _haystack(commit):
    """Everything on a commit a term can match, lowercased once."""
    return " ".join(
        [
            commit.get("subject") or "",
            commit.get("body") or "",
            commit.get("scope") or "",
            *_paths(commit.get("files")),
        ]
    ).lower()


def term_weights(commits, wanted):
    """Each term weighted by how little of the corpus already carries it.

    Counting every term the same let a term carried by nearly every commit
    decide the ranking. Measured on this repository's own 199 commits, the
    subject "how documents are placed in the doc set" came back with commits
    about docstrings and cleanup: `doc` is a substring of `docs-`,
    `docstrings` and `.docs-gen`, so it matched almost everything at full
    weight and drowned out `placed`. Weighted, `doc` falls to 0.12 and
    `placed` rises to 3.1, and the placement commits come back instead.
    """
    total = len(commits)
    if total < MIN_CORPUS:
        return {word: 1.0 for word in wanted}
    haystacks = [_haystack(commit) for commit in commits]
    return {
        word: math.log((total + 1) / (sum(1 for text in haystacks if word in text) + 1))
        for word in wanted
    }


def score(commit, wanted, weights=None):
    """How closely one commit matches the subject's terms.

    `weights` scales each term by its rarity. Without it every term counts
    the same, which is the only thing a caller scoring one commit on its own
    can ask for.
    """
    if not wanted:
        return 0
    paths = _paths(commit.get("files"))
    total = 0.0
    for word in wanted:
        weight = 1.0 if weights is None else weights.get(word, 1.0)
        if not weight:
            continue
        total += weight * (
            SUBJECT_WEIGHT * _has(word, commit.get("subject"))
            + BODY_WEIGHT * _has(word, commit.get("body"))
            + SCOPE_WEIGHT * _has(word, commit.get("scope"))
            + PATH_WEIGHT * sum(_has(word, path) for path in paths)
        )
    return total


def select_commits(commits, subject, limit=DEFAULT_LIMIT):
    """The commits most relevant to `subject`, ranked and capped at `limit`."""
    if not commits:
        return []
    wanted = _words(subject)
    if not wanted:
        return list(commits)[:limit]

    weights = term_weights(commits, wanted)
    scored = [
        (value, commit)
        for value, commit in ((score(c, wanted, weights), c) for c in commits)
        if value > 0
    ]
    if not scored:
        # Every term that matched is a term the whole corpus carries, so
        # rarity has nothing to say about them. Rank on hits alone rather
        # than returning nothing for a subject that does match.
        scored = [
            (value, commit)
            for value, commit in ((score(c, wanted), c) for c in commits)
            if value > 0
        ]
    ranked = sorted(
        enumerate(scored),
        key=lambda pair: (-pair[1][0], 0 if pair[1][1].get("breaking") else 1, pair[0]),
    )
    return [commit for _, (_, commit) in ranked][:limit]

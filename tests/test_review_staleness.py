"""docs-review: a document whose subject moved.

docs-orc dropped this check when it forked, because a topic run has no
watermark to compare against. docs-sync does, and a hand-written page that has
gone stale is the finding a human most needs: it is the one case the tool will
not fix for them.

This test does not start red. `check_staleness` is already here, and the merge
is about to replace the whole file with docs-orc's, which does not have it. The
test exists so that replacement cannot quietly drop it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SKILL = Path(__file__).resolve().parent.parent / "skills" / "docs-review" / "scripts"
if str(_SKILL) not in sys.path:
    sys.path.insert(0, str(_SKILL))

import review  # noqa: E402


def test_a_manual_page_covering_a_changed_module_warns():
    findings = review.check_staleness(
        "docs/queue.md",
        {"managed": "manual", "source_modules": ["pkg/queue"]},
        {"rebuild": ["pkg/queue"]},
        "abc1234",
    )
    assert [f["kind"] for f in findings] == ["stale-manual"]
    assert findings[0]["severity"] == "warning"


def test_a_generated_page_at_head_is_not_stale():
    findings = review.check_staleness(
        "docs/queue.md",
        {"managed": "generated", "source_modules": ["pkg/queue"], "source_sha": "abc1234"},
        {"rebuild": ["pkg/queue"]},
        "abc1234567",
    )
    assert findings == []


def test_a_page_covering_nothing_that_moved_is_not_stale():
    findings = review.check_staleness(
        "docs/queue.md",
        {"managed": "generated", "source_modules": ["pkg/other"]},
        {"rebuild": ["pkg/queue"]},
        "abc1234",
    )
    assert findings == []

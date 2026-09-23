"""lib/git/api_surface.py: the fingerprint diff that decides what to rebuild.

docs-orc dropped this half when it forked. docs-sync needs it back, and it has
to coexist with `usable_modules`, which docs-orc added while it was gone.

Signatures are the ones this branch already ships: `diff_snapshots(before,
after)` takes two `{"modules": {name: {"hash", "symbols"}}}` snapshots, where a
symbol carries `fp`, `signature` and `file`, and returns a per-module record of
what was added, removed, changed and moved. `classify(git_context, api_diff)`
turns that record into a relevance verdict.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lib.git import api_surface  # noqa: E402


def _snapshot(symbols, hash_="h1"):
    return {"modules": {"pkg/queue": {"hash": hash_, "symbols": symbols}}}


def _symbol(fp, signature, file="pkg/queue/queue.py"):
    return {"fp": fp, "signature": signature, "file": file}


def test_a_removed_symbol_is_recorded_as_removed():
    before = _snapshot({"Push": _symbol("a", "Push(x)"), "Pop": _symbol("b", "Pop()")})
    after = _snapshot({"Push": _symbol("a", "Push(x)")}, hash_="h2")
    diff = api_surface.diff_snapshots(before, after)
    assert diff["modules"]["pkg/queue"]["removed"] == ["Pop"]
    assert diff["modules"]["pkg/queue"]["added"] == []


def test_a_changed_signature_is_recorded_with_both_sides():
    before = _snapshot({"Push": _symbol("a", "Push(x)")})
    after = _snapshot({"Push": _symbol("z", "Push(x, timeout)")}, hash_="h2")
    changed = api_surface.diff_snapshots(before, after)["modules"]["pkg/queue"]["changed"]
    assert changed == [{"symbol": "Push", "before": "Push(x)", "after": "Push(x, timeout)"}]


def test_a_module_whose_hash_is_unchanged_is_skipped_entirely():
    same = _snapshot({"Push": _symbol("a", "Push(x)")})
    diff = api_surface.diff_snapshots(same, _snapshot({"Push": _symbol("a", "Push(x)")}))
    assert diff["modules"] == {}


def test_moved_registry_boundaries_force_a_full_rebuild():
    verdict = api_surface.classify({}, {"registry_changed": True})
    assert verdict["verdict"] == "full_rebuild"


def test_usable_modules_survives_the_graft():
    assert callable(api_surface.usable_modules)

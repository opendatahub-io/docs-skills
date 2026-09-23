"""Bounding the onboarding synthesis, and reading only this run's summaries.

Synthesis used to load every JSON file under `<out>/modules` and hand the lot
to one model call. Two things went wrong with that. A repository with enough
modules exceeded the model's context window, and the only thing said about it
was `$: no JSON object or array found in output`. And the glob picked up
summaries an earlier run had left, including ones whose module boundaries had
since moved, so a guide could describe a repository that no longer existed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_ANALYZE = REPO_ROOT / "skills" / "docs-repo-analyze" / "scripts"
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
for _path in (_ANALYZE, _ENGINE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import analyze  # noqa: E402


def registry(*names, language="python"):
    return {
        "language": language,
        "module_count": len(names),
        "config_files": [],
        "modules": {n: {"kind": "library", "file_count": 1, "paths": [n]} for n in names},
    }


def summary(module, size=100):
    return {
        "module": module,
        "purpose": "x" * size,
        "responsibilities": ["r"],
        "dependencies": [],
        "gotchas": ["g"],
        "evidence": [f"{module}/mod.py:1"],
    }


def seed(out, *summaries):
    (out / "modules").mkdir(parents=True, exist_ok=True)
    for entry in summaries:
        name = analyze.slug(entry["module"])
        (out / "modules" / f"{name}.json").write_text(json.dumps(entry))
    return out


# ------------------------------------------------------ only this run's reading


def test_a_summary_for_a_module_the_registry_does_not_hold_is_ignored(tmp_path):
    """An earlier run whose boundaries have since moved leaves these behind."""
    out = seed(tmp_path, summary("pkg/queue"), summary("pkg/gone"))
    kept = analyze.module_summaries(out, registry("pkg/queue"))
    assert [entry["module"] for entry in kept] == ["pkg/queue"]


def test_the_summaries_come_back_in_a_stable_order(tmp_path):
    out = seed(tmp_path, summary("pkg/zeta"), summary("pkg/alpha"), summary("pkg/mid"))
    names = [e["module"] for e in analyze.module_summaries(out, registry("pkg/zeta", "pkg/alpha", "pkg/mid"))]
    assert names == sorted(names)


def test_an_unreadable_summary_is_skipped_rather_than_ending_the_step(tmp_path):
    out = seed(tmp_path, summary("pkg/queue"))
    (out / "modules" / "pkg__broken.json").write_text("{not json")
    kept = analyze.module_summaries(out, registry("pkg/queue", "pkg/broken"))
    assert [entry["module"] for entry in kept] == ["pkg/queue"]


# ------------------------------------------------------------------ partition


def test_a_small_set_is_one_batch():
    """One batch means one call, which is exactly today's behaviour."""
    batches = analyze.partition([summary(f"pkg/m{i}") for i in range(5)], budget=100_000)
    assert len(batches) == 1


def test_a_set_over_the_budget_is_split():
    batches = analyze.partition([summary(f"pkg/m{i}", size=400) for i in range(20)], budget=2_000)
    assert len(batches) > 1
    assert sum(len(b) for b in batches) == 20


def test_partitioning_is_deterministic():
    summaries = [summary(f"pkg/m{i}", size=400) for i in range(20)]
    first = analyze.partition(summaries, budget=2_000)
    second = analyze.partition(list(summaries), budget=2_000)
    assert [[e["module"] for e in b] for b in first] == [[e["module"] for e in b] for b in second]


def test_every_module_lands_in_exactly_one_batch():
    summaries = [summary(f"pkg/m{i}", size=400) for i in range(20)]
    placed = [e["module"] for batch in analyze.partition(summaries, budget=2_000) for e in batch]
    assert sorted(placed) == sorted(e["module"] for e in summaries)
    assert len(placed) == len(set(placed))


def test_a_single_summary_larger_than_the_budget_still_gets_a_batch():
    """Refusing to place it would drop a module from the guide silently."""
    batches = analyze.partition([summary("pkg/huge", size=50_000)], budget=1_000)
    assert [e["module"] for b in batches for e in b] == ["pkg/huge"]


# ------------------------------------------------------------------ synthesis


class FakeStep:
    """Records each call, and answers with something the schema accepts."""

    def __init__(self, fail_on=None):
        self.payloads = []
        self.fail_on = fail_on

    def run_step(self, prompt, payload, schema, command, timeout, **kw):
        self.payloads.append(payload)
        if self.fail_on is not None and len(self.payloads) == self.fail_on:
            raise analyze.step.StepError(["$: no JSON object or array found"], "not json at all")
        if "batch" in (payload.get("_kind") or ""):
            return {"modules": [{"module": m["module"], "purpose": "p"} for m in payload["modules"]]}, 1
        return {
            "frontmatter": {"title": "Guide", "description": "d" * 20, "type": "overview"},
            "sections": [
                {"id": f"s{i}", "heading": f"H{i}", "body": "b" * 40} for i in range(3)
            ],
        }, 1


def test_a_small_repository_makes_one_call(tmp_path, monkeypatch):
    out = seed(tmp_path, *(summary(f"pkg/m{i}") for i in range(3)))
    fake = FakeStep()
    monkeypatch.setattr(analyze.step, "run_step", fake.run_step)
    target = analyze.synthesize(registry(*(f"pkg/m{i}" for i in range(3))), out, "fake", 10, budget=100_000)
    assert target is not None and target.is_file()
    assert len(fake.payloads) == 1


def test_a_large_repository_batches_then_synthesizes(tmp_path, monkeypatch):
    names = [f"pkg/m{i}" for i in range(20)]
    out = seed(tmp_path, *(summary(n, size=400) for n in names))
    fake = FakeStep()
    monkeypatch.setattr(analyze.step, "run_step", fake.run_step)
    target = analyze.synthesize(registry(*names), out, "fake", 10, budget=2_000)
    assert target is not None and target.is_file()
    assert len(fake.payloads) > 2, "expected one call per batch, then the final one"
    # Every module reaches a batch call, and the final call sees the compacted set.
    batched = {m["module"] for p in fake.payloads[:-1] for m in p["modules"]}
    assert batched == set(names)


def test_a_narrowed_run_does_not_synthesize(tmp_path, monkeypatch):
    """A guide built from 3 of 50 modules describes a repository nobody has."""
    names = [f"pkg/m{i}" for i in range(50)]
    out = seed(tmp_path, *(summary(n) for n in names[:3]))
    fake = FakeStep()
    monkeypatch.setattr(analyze.step, "run_step", fake.run_step)
    target = analyze.synthesize(
        registry(*names), out, "fake", 10, budget=100_000, narrowed=True
    )
    assert target is None
    assert fake.payloads == []


def test_a_narrowed_run_leaves_an_existing_guide_alone(tmp_path, monkeypatch):
    names = [f"pkg/m{i}" for i in range(50)]
    out = seed(tmp_path, *(summary(n) for n in names[:3]))
    (out / "ONBOARDING.md").write_text("# Kept\n")
    monkeypatch.setattr(analyze.step, "run_step", FakeStep().run_step)
    analyze.synthesize(registry(*names), out, "fake", 10, budget=100_000, narrowed=True)
    assert (out / "ONBOARDING.md").read_text() == "# Kept\n"


# ------------------------------------------------------------ failure artifact


def test_a_failed_synthesis_keeps_the_raw_reply_and_the_input_size(tmp_path, monkeypatch):
    """`$: no JSON object or array found in output` on its own says nothing
    about why. StepError already carries the raw reply; it was the caller that
    threw it away."""
    names = [f"pkg/m{i}" for i in range(3)]
    out = seed(tmp_path, *(summary(n) for n in names))
    monkeypatch.setattr(analyze.step, "run_step", FakeStep(fail_on=1).run_step)
    target = analyze.synthesize(registry(*names), out, "fake -p", 10, budget=100_000)
    assert target is None
    record = json.loads((out / "synthesis-error.json").read_text())
    assert record["command"] == "fake -p"
    assert record["raw"] == "not json at all"
    assert record["input_chars"] > 0
    assert record["modules"] == 3
    assert "no JSON object" in record["errors"][0]


def test_a_batch_failure_is_recorded_with_the_batch_it_came_from(tmp_path, monkeypatch):
    names = [f"pkg/m{i}" for i in range(20)]
    out = seed(tmp_path, *(summary(n, size=400) for n in names))
    monkeypatch.setattr(analyze.step, "run_step", FakeStep(fail_on=1).run_step)
    assert analyze.synthesize(registry(*names), out, "fake", 10, budget=2_000) is None
    record = json.loads((out / "synthesis-error.json").read_text())
    assert record["stage"] == "batch"
    assert record["batch"] == 1


# ----------------------------------------------------------------- the budget


def test_the_budget_is_configurable_and_has_a_default():
    from lib.pipeline import config

    assert config.DEFAULTS["analyze"]["synthesis_budget"] > 0
    assert "token_budget" not in config.DEFAULTS, "the dead key should have become this one"


def test_the_analyzer_takes_the_budget_on_the_command_line():
    parser_help = (
        REPO_ROOT / "skills" / "docs-repo-analyze" / "scripts" / "analyze.py"
    ).read_text()
    assert "--synthesis-budget" in parser_help

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
        if "reading-order" not in prompt:
            return {
                "modules": [{"module": m["module"], "purpose": "p"} for m in payload["modules"]]
            }, 1
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


# ------------------------------------------------- what compaction may shed


def full_summary(module):
    """A module summary with every field `analyze-module-out.json` allows."""
    return {
        "module": module,
        "purpose": "p",
        "responsibilities": ["r"],
        "public_api": [{"name": "f", "signature": "f()"} for _ in range(50)],
        "dependencies": ["pkg/other"],
        "data_flow": "in at the top, out at the bottom",
        "gotchas": ["it retries silently (mod.py:12)"],
        "onboarding_priority": 2,
        "evidence": [f"{module}/mod.py:1"],
    }


def test_the_batch_prompt_carries_every_field_synthesis_reads():
    """synthesize-modules.md orders reading-order by `onboarding_priority` and
    traces key-flows from `data_flow`. A compaction that drops either degrades
    the guide on exactly the repositories batching exists for, and says
    nothing."""
    prompt = (analyze.PROMPTS / "synthesize-batch.md").read_text()
    schema = json.loads((analyze.SCHEMAS / "synthesize-batch-out.json").read_text())
    fields = schema["properties"]["modules"]["items"]["properties"]
    for name in ("onboarding_priority", "data_flow", "gotchas", "dependencies", "evidence"):
        assert name in fields, f"the batch schema drops {name}"
        assert name in prompt, f"the batch prompt never mentions {name}"


def test_public_api_is_what_compaction_sheds():
    """It is the bulk of a summary's size and synthesis never reads it."""
    schema = json.loads((analyze.SCHEMAS / "synthesize-batch-out.json").read_text())
    assert "public_api" not in schema["properties"]["modules"]["items"]["properties"]


def test_the_batch_call_sends_the_model_no_private_keys(tmp_path, monkeypatch):
    """A key the payload carries reaches the model as part of `{{input}}`, and
    `build_values` also exposes it as a `{{placeholder}}`. A test hook does not
    belong in either."""
    names = [f"pkg/m{i}" for i in range(20)]
    out = seed(tmp_path, *(summary(n, size=400) for n in names))
    seen = []

    def run_step(prompt, payload, schema, command, timeout, **kw):
        seen.append(payload)
        if "reading-order" in prompt:
            return {
                "frontmatter": {"title": "G", "description": "d" * 20, "type": "overview"},
                "sections": [{"id": f"s{i}", "heading": f"H{i}", "body": "b" * 40} for i in range(3)],
            }, 1
        return {"modules": [{"module": m["module"], "purpose": "p"} for m in payload["modules"]]}, 1

    monkeypatch.setattr(analyze.step, "run_step", run_step)
    analyze.synthesize(registry(*names), out, "fake", 10, budget=2_000)
    for payload in seen:
        private = [k for k in payload if k.startswith("_")]
        assert private == [], f"payload carries {private}"


def test_a_zero_or_negative_budget_still_makes_progress():
    """A misconfigured budget must not produce a batch per module silently, nor
    loop. One batch per module is the honest floor."""
    summaries = [summary(f"pkg/m{i}") for i in range(4)]
    for budget in (0, -1):
        batches = analyze.partition(summaries, budget=budget)
        placed = [e["module"] for b in batches for e in b]
        assert sorted(placed) == sorted(e["module"] for e in summaries), budget


# ------------------------------------------------ the batch keeps every module


def _batching_fake(reply):
    """A fake whose batch replies are whatever `reply(batch)` returns."""

    def run_step(prompt, payload, schema, command, timeout, **kw):
        if "reading-order" not in prompt:
            return {"modules": reply(payload["modules"])}, 1
        return {
            "frontmatter": {"title": "G", "description": "d" * 20, "type": "overview"},
            "sections": [{"id": f"s{i}", "heading": f"H{i}", "body": "b" * 40} for i in range(3)],
        }, 1

    return run_step


def test_a_module_the_batch_reply_dropped_is_restored(tmp_path, monkeypatch):
    """`Guards live in scripts, never in prompts`. The batch prompt asks for
    every module back; a model that returns nine of ten would otherwise delete
    a module from the guide and say nothing."""
    names = [f"pkg/m{i:02d}" for i in range(20)]
    out = seed(tmp_path, *(full_summary(n) for n in names))
    monkeypatch.setattr(
        analyze.step, "run_step", _batching_fake(lambda batch: [dict(b) for b in batch[:-1]])
    )
    reduced = analyze.compact(analyze.module_summaries(out, registry(*names)), out, "f", 10, 2_000)
    assert {e["module"] for e in reduced} == set(names)


def test_a_restored_module_still_sheds_its_public_api(tmp_path, monkeypatch):
    """The fallback is the original summary minus the one field compaction
    exists to drop, not the original whole."""
    names = [f"pkg/m{i:02d}" for i in range(20)]
    out = seed(tmp_path, *(full_summary(n) for n in names))
    monkeypatch.setattr(analyze.step, "run_step", _batching_fake(lambda batch: []))
    reduced = analyze.compact(analyze.module_summaries(out, registry(*names)), out, "f", 10, 2_000)
    assert {e["module"] for e in reduced} == set(names)
    assert all("public_api" not in e for e in reduced)
    assert all(e.get("onboarding_priority") == 2 for e in reduced)


def test_a_module_the_batch_invented_is_dropped(tmp_path, monkeypatch):
    """A module name nothing analyzed is a claim about code that may not exist."""
    names = [f"pkg/m{i:02d}" for i in range(20)]
    out = seed(tmp_path, *(full_summary(n) for n in names))

    def reply(batch):
        return [dict(b) for b in batch] + [{"module": "pkg/invented", "purpose": "p"}]

    monkeypatch.setattr(analyze.step, "run_step", _batching_fake(reply))
    reduced = analyze.compact(analyze.module_summaries(out, registry(*names)), out, "f", 10, 2_000)
    assert {e["module"] for e in reduced} == set(names)

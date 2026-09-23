"""Bounding the onboarding synthesis, and reading only this run's summaries.

Synthesis used to load every JSON file under `<out>/modules` and hand the lot
to one model call. Two things went wrong with that. A repository with enough
modules exceeded the model's context window, and the only thing said about it
was `$: no JSON object or array found in output`. And the glob picked up
summaries an earlier run had left, including ones whose module boundaries had
since moved, so a guide could describe a repository that no longer existed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

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
    """A module summary in the shape `analyze-module-out.json` defines."""
    return {
        "module": module,
        "purpose": "x" * size,
        "responsibilities": ["r"],
        "dependencies": [],
        "gotchas": [{"summary": "it retries silently", "evidence": f"{module}/mod.py:12"}],
        "onboarding_priority": "early",
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
    reg = registry("pkg/zeta", "pkg/alpha", "pkg/mid")
    names = [e["module"] for e in analyze.module_summaries(out, reg)]
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


def _guide():
    """A synthesis reply `synthesize-out.json` accepts."""
    return {
        "frontmatter": {"title": "Guide", "description": "d" * 20, "type": "overview"},
        "sections": [{"id": f"s{i}", "heading": f"H{i}", "body": "b" * 40} for i in range(3)],
    }


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
        return _guide(), 1


def test_a_small_repository_makes_one_call(tmp_path, monkeypatch):
    out = seed(tmp_path, *(summary(f"pkg/m{i}") for i in range(3)))
    fake = FakeStep()
    monkeypatch.setattr(analyze.step, "run_step", fake.run_step)
    reg = registry(*(f"pkg/m{i}" for i in range(3)))
    target = analyze.synthesize(reg, out, "fake", 10, budget=100_000)
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
    target = analyze.synthesize(registry(*names), out, "fake", 10, budget=100_000, narrowed=True)
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
    with pytest.raises(analyze.SynthesisError):
        analyze.synthesize(registry(*names), out, "fake -p", 10, budget=100_000)
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
    assert analyze.synthesize(registry(*names), out, "fake", 10, budget=8_000) is not None
    record = json.loads((out / "synthesis-error.json").read_text())
    assert record["stage"] == "batch"
    assert record["batch"] == 1
    assert record["recovered"] is True


def test_one_failed_batch_does_not_cost_the_run_its_guide(tmp_path, monkeypatch):
    """Five compacted batches and one that timed out is a larger final payload.
    It is not a reason to finish a paid-for run with no guide in it."""
    names = [f"pkg/m{i:02d}" for i in range(20)]
    out = seed(tmp_path, *(summary(n, size=400) for n in names))
    monkeypatch.setattr(analyze.step, "run_step", FakeStep(fail_on=2).run_step)
    target = analyze.synthesize(registry(*names), out, "fake", 10, budget=8_000)
    assert target is not None and target.is_file()


def test_a_failed_batch_keeps_its_own_modules(tmp_path, monkeypatch):
    """The batch that failed carries its summaries forward rather than losing
    them, so no module drops out of the guide over one bad call."""
    names = [f"pkg/m{i:02d}" for i in range(20)]
    out = seed(tmp_path, *(full_summary(n) for n in names))
    monkeypatch.setattr(analyze.step, "run_step", FakeStep(fail_on=1).run_step)
    summaries = analyze.module_summaries(out, registry(*names))
    reduced = analyze.compact(summaries, out, "fake", 10, 8_000)
    assert {e["module"] for e in reduced} == set(names)
    assert all("public_api" not in e for e in reduced)


def test_a_stale_error_record_does_not_outlive_its_run(tmp_path, monkeypatch):
    """`synthesis-error.json` reads as the current state of `.docs-gen/`. One a
    previous failure left behind diagnoses a failure against a guide that is
    fine."""
    names = [f"pkg/m{i}" for i in range(3)]
    out = seed(tmp_path, *(summary(n) for n in names))
    (out / "synthesis-error.json").write_text('{"stage": "synthesis"}')
    monkeypatch.setattr(analyze.step, "run_step", FakeStep().run_step)
    assert analyze.synthesize(registry(*names), out, "fake", 10, budget=100_000) is not None
    assert not (out / "synthesis-error.json").exists()


def test_the_error_record_masks_a_key_in_the_command(tmp_path, monkeypatch):
    """`.docs-gen/` is written inside the repository being documented, and
    `llm_cmd` comes from `DOCS_LLM_CMD`, which can carry a key in its argv."""
    names = [f"pkg/m{i}" for i in range(3)]
    out = seed(tmp_path, *(summary(n) for n in names))
    monkeypatch.setattr(analyze.step, "run_step", FakeStep(fail_on=1).run_step)
    with pytest.raises(analyze.SynthesisError):
        analyze.synthesize(registry(*names), out, "llm --api-key sk-live-abc123", 10)
    record = json.loads((out / "synthesis-error.json").read_text())
    assert "sk-live-abc123" not in record["command"]
    assert "llm" in record["command"]


def test_the_error_record_caps_the_raw_reply(tmp_path, monkeypatch):
    """A reply that is not JSON has no reason to be small."""

    def run_step(prompt, payload, schema, command, timeout, **kw):
        raise analyze.step.StepError(["$: no JSON"], "x" * 100_000)

    names = [f"pkg/m{i}" for i in range(3)]
    out = seed(tmp_path, *(summary(n) for n in names))
    monkeypatch.setattr(analyze.step, "run_step", run_step)
    with pytest.raises(analyze.SynthesisError):
        analyze.synthesize(registry(*names), out, "fake", 10)
    record = json.loads((out / "synthesis-error.json").read_text())
    assert len(record["raw"]) == analyze.step.RAW_CAP


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
        "public_api": [{"name": "f", "summary": "does a thing"} for _ in range(50)],
        "dependencies": ["pkg/other"],
        "data_flow": "in at the top, out at the bottom",
        "gotchas": [{"summary": "it retries silently", "evidence": "mod.py:12"}],
        "onboarding_priority": "early",
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
            return _guide(), 1
        return {"modules": [{"module": m["module"], "purpose": "p"} for m in payload["modules"]]}, 1

    monkeypatch.setattr(analyze.step, "run_step", run_step)
    analyze.synthesize(registry(*names), out, "fake", 10, budget=2_000)
    for payload in seen:
        private = [k for k in payload if k.startswith("_")]
        assert private == [], f"payload carries {private}"


def test_a_zero_or_negative_budget_still_places_every_module():
    """`partition` is arithmetic and stays total. Rejecting the budget is the
    command line's job, one layer up."""
    summaries = [summary(f"pkg/m{i}") for i in range(4)]
    for budget in (0, -1):
        batches = analyze.partition(summaries, budget=budget)
        placed = [e["module"] for b in batches for e in b]
        assert sorted(placed) == sorted(e["module"] for e in summaries), budget


def test_a_budget_under_the_floor_is_refused_on_the_command_line():
    """Under the floor every module gets a batch and a call of its own: 200
    modules become 201 model calls at up to `--timeout` each, announced in a
    single log line."""
    for value in ("0", "-1", "100"):
        with pytest.raises(argparse.ArgumentTypeError):
            analyze.synthesis_budget(value)
    assert analyze.synthesis_budget(str(analyze.MIN_SYNTHESIS_BUDGET)) > 0


def test_compact_clamps_a_budget_under_the_floor(tmp_path, monkeypatch):
    """A library caller does not go through argparse, and a budget of 1 would
    otherwise be one model call per module."""
    names = [f"pkg/m{i:02d}" for i in range(40)]
    out = seed(tmp_path, *(summary(n, size=300) for n in names))
    calls = []

    def reply(batch):
        calls.append(len(batch))
        return [{"module": b["module"], "purpose": "p"} for b in batch]

    monkeypatch.setattr(analyze.step, "run_step", _batching_fake(reply))
    analyze.compact(analyze.module_summaries(out, registry(*names)), out, "f", 10, 1)
    assert calls, "expected compaction to run"
    assert max(calls) > 1, "the floor should not batch one module at a time"
    assert len(calls) < len(names), "a batch per module is what the floor exists to prevent"


# ------------------------------------------------ the batch keeps every module


def _batching_fake(reply):
    """A fake whose batch replies are whatever `reply(batch)` returns."""

    def run_step(prompt, payload, schema, command, timeout, **kw):
        if "reading-order" not in prompt:
            return {"modules": reply(payload["modules"])}, 1
        return _guide(), 1

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
    assert all(e.get("onboarding_priority") == "early" for e in reduced)


def test_a_module_the_batch_invented_is_dropped(tmp_path, monkeypatch):
    """A module name nothing analyzed is a claim about code that may not exist."""
    names = [f"pkg/m{i:02d}" for i in range(20)]
    out = seed(tmp_path, *(full_summary(n) for n in names))

    def reply(batch):
        return [dict(b) for b in batch] + [{"module": "pkg/invented", "purpose": "p"}]

    monkeypatch.setattr(analyze.step, "run_step", _batching_fake(reply))
    reduced = analyze.compact(analyze.module_summaries(out, registry(*names)), out, "f", 10, 2_000)
    assert {e["module"] for e in reduced} == set(names)


# ------------------------------------------- the batch contract and the summary


def test_a_module_summary_validates_against_the_batch_contract():
    """The two schemas describe the same record at two sizes, so every field
    they share has to agree on its shape. When they disagreed, the batch step
    rejected a reply that obeyed the prompt, the retry repeated it, and every
    repository over the budget finished with no guide at all."""
    from lib.run import step as step_lib

    batch = json.loads((analyze.SCHEMAS / "synthesize-batch-out.json").read_text())
    module = json.loads((analyze.SCHEMAS / "analyze-module-out.json").read_text())
    shared = set(batch["properties"]["modules"]["items"]["properties"]) & set(module["properties"])
    assert "onboarding_priority" in shared and "gotchas" in shared
    for name in shared:
        assert batch["properties"]["modules"]["items"]["properties"][name].get("type") == module[
            "properties"
        ][name].get("type"), f"{name} has a different type in each schema"

    # And the whole record, end to end, through the validator the step uses.
    reply = {"modules": [{k: v for k, v in full_summary("pkg/q").items() if k != "public_api"}]}
    assert step_lib.validate(reply, batch) == []


def test_the_batch_prompt_shows_the_shapes_the_contract_requires():
    """The model copies the example. An example in the wrong shape is the same
    bug as a schema in the wrong shape, one layer further out."""
    prompt = (analyze.PROMPTS / "synthesize-batch.md").read_text()
    assert '"onboarding_priority": 2' not in prompt
    assert "first|early|later|reference" in prompt
    assert '"gotchas": [{"summary"' in prompt


# --------------------------------------------------------- what the budget counts


def test_a_summary_is_measured_as_the_prompt_will_carry_it():
    """`step.render` serializes with `indent=2, sort_keys=True`. Measuring with
    a compact dump undercounts the real prompt by around half, so a budget
    tuned to sit under the context window overruns it."""
    from lib.run import step as step_lib

    entry = full_summary("pkg/queue")
    rendered = step_lib.render("{{input}}", step_lib.build_values({"modules": [entry]}, {}))
    assert analyze.entry_size(entry) > len(json.dumps(entry))
    assert analyze.entry_size(entry) <= len(rendered)


# ------------------------------------------------ what the model may hand back


def test_public_api_echoed_back_by_the_model_is_stripped(tmp_path, monkeypatch):
    """The contract does not forbid extra keys, so a reply that returns the
    input unchanged validates. Compaction that sheds nothing still costs a call
    per batch, and the final call carries the bulk it was meant to remove."""
    names = [f"pkg/m{i:02d}" for i in range(20)]
    out = seed(tmp_path, *(full_summary(n) for n in names))
    monkeypatch.setattr(
        analyze.step, "run_step", _batching_fake(lambda batch: [dict(b) for b in batch])
    )
    summaries = analyze.module_summaries(out, registry(*names))
    reduced = analyze.compact(summaries, out, "f", 10, 8_000)
    assert all("public_api" not in e for e in reduced)
    assert sum(analyze.entry_size(e) for e in reduced) < sum(
        analyze.entry_size(e) for e in summaries
    )


def test_the_batch_order_survives_a_partial_reply(tmp_path, monkeypatch):
    """`module_summaries` sorts, `partition` preserves, and the guide orders its
    reading list from this input. Model-returned records followed by the
    fallbacks would reorder the guide between two runs of identical code."""
    names = [f"pkg/m{i:02d}" for i in range(20)]
    out = seed(tmp_path, *(full_summary(n) for n in names))
    # Every batch drops its first module, which is the one a reordering fix
    # would otherwise move to the end.
    monkeypatch.setattr(
        analyze.step, "run_step", _batching_fake(lambda batch: [dict(b) for b in batch[1:]])
    )
    summaries = analyze.module_summaries(out, registry(*names))
    reduced = analyze.compact(summaries, out, "f", 10, 8_000)
    assert [e["module"] for e in reduced] == [e["module"] for e in summaries]


def test_compaction_that_sheds_nothing_stops_rather_than_paying_again(tmp_path, monkeypatch):
    """The loop exists because one pass is not a guarantee. A model that
    returns the input unchanged would make it a bill instead."""
    names = [f"pkg/m{i:02d}" for i in range(20)]
    out = seed(tmp_path, *(summary(n, size=400) for n in names))
    calls = []

    def reply(batch):
        calls.append(len(batch))
        return [dict(b) for b in batch]

    monkeypatch.setattr(analyze.step, "run_step", _batching_fake(reply))
    summaries = analyze.module_summaries(out, registry(*names))
    analyze.compact(summaries, out, "f", 10, 8_000)
    one_pass = len(analyze.partition(summaries, 8_000))
    assert len(calls) == one_pass, "a pass that sheds nothing should not buy another"


# ------------------------------------------------------ nothing to do, or broken


def test_a_run_with_no_summaries_is_nothing_to_do_rather_than_a_failure(tmp_path):
    """It writes no record, so treating it as a failure sends whoever reads the
    exit code looking for a `synthesis-error.json` that was never written."""
    out = tmp_path
    (out / "modules").mkdir()
    assert analyze.synthesize(registry("pkg/queue"), out, "fake", 10) is None
    assert not (out / "synthesis-error.json").exists()


# ------------------------------------------------------- the command line

_ANALYZE_PY = REPO_ROOT / "skills" / "docs-repo-analyze" / "scripts" / "analyze.py"


def _repo(tmp_path):
    pkg = tmp_path / "pkg" / "queue"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "queue.py").write_text("def push(item):\n    return item\n")
    return tmp_path


def _run(*args):
    return subprocess.run([sys.executable, str(_ANALYZE_PY), *args], capture_output=True, text=True)


def test_modules_naming_nothing_in_the_registry_is_an_error(tmp_path):
    """Summarizing nothing and synthesizing nothing looks exactly like a clean
    run by the time it reaches the exit code, and `--modules` takes module
    paths, which are easy to mistype."""
    repo = _repo(tmp_path / "repo")
    done = _run(
        "--repo",
        str(repo),
        "--out",
        str(tmp_path / "out"),
        "--llm-cmd",
        "false",
        "--modules",
        "pkg/qeueu",
    )
    assert done.returncode == 2, done.stdout + done.stderr
    assert "pkg/qeueu" in done.stdout + done.stderr


def test_a_budget_under_the_floor_is_rejected_before_the_run(tmp_path):
    repo = _repo(tmp_path / "repo")
    done = _run("--repo", str(repo), "--out", str(tmp_path / "out"), "--synthesis-budget", "0")
    assert done.returncode == 2
    assert "floor" in done.stderr


# ----------------------------------------------------------- the config surface


def test_docs_sync_passes_the_configured_budget_through():
    """A key in `DEFAULTS` and in the example config that nothing reads is a
    setting a repository can configure and never have applied."""
    source = (REPO_ROOT / "skills" / "docs-sync" / "scripts" / "sync.py").read_text()
    assert "--synthesis-budget" in source
    assert "synthesis_budget" in source

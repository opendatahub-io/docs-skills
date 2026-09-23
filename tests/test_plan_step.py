"""Deciding what to write from what the repository shows.

The validation here exists because each malformed deliverable fails later and
further from its cause: an unknown type reaches the writer and produces a
document no structural rule gates, and an invented source reaches it as
evidence for a claim nothing supports.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_PLAN = REPO_ROOT / "skills" / "docs-plan" / "scripts"
if str(_PLAN) not in sys.path:
    sys.path.insert(0, str(_PLAN))

import plan  # noqa: E402

MODULE = "pkg/registry"


def deliverable(**over):
    base = {
        "path": "configure-the-registry.md",
        "type": "procedure",
        "title": "Configure the registry",
        "rationale": "Nothing says how",
        "sources": [MODULE],
    }
    base.update(over)
    return base


def seed_registry(out, modules=(MODULE,)):
    """A registry with the modules named, as docs-repo-analyze writes it."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "registry.json").write_text(
        json.dumps(
            {
                "language": "python",
                "module_count": len(modules),
                "modules": {
                    name: {"kind": "library", "file_count": 2, "paths": [name]} for name in modules
                },
            }
        )
    )
    return out


def fake_plan(monkeypatch, result, calls=None):
    def run_step(prompt_text, payload, *a, **k):
        if calls is not None:
            calls.append(payload)
        return result, 1

    monkeypatch.setattr(plan.step, "run_step", run_step)


# ----------------------------------------------------------------- validation


def test_a_well_formed_deliverable_survives():
    kept, rejected, adjusted = plan.validate([deliverable()], {MODULE})
    assert len(kept) == 1 and rejected == []


@pytest.mark.parametrize(
    "path",
    ["docs/thing.md", "../escape.md", "Thing.md", "thing", "thing.txt", "two words.md", ""],
)
def test_a_path_that_is_not_a_bare_kebab_case_file_is_rejected(path):
    """The writer joins this onto docs_dir, so a directory or a traversal in
    it decides where a file lands."""
    kept, rejected, adjusted = plan.validate([deliverable(path=path)], {MODULE})
    assert kept == [] and len(rejected) == 1


def test_an_unknown_type_is_rejected():
    """The three types are what the structural Vale rules gate on. A fourth
    produces a document nothing checks."""
    kept, rejected, adjusted = plan.validate([deliverable(type="tutorial")], {MODULE})
    assert kept == [] and len(rejected) == 1


def test_a_duplicate_path_is_rejected_once():
    kept, rejected, adjusted = plan.validate([deliverable(), deliverable()], {MODULE})
    assert len(kept) == 1 and len(rejected) == 1


def test_a_missing_title_or_rationale_is_rejected():
    kept, rejected, adjusted = plan.validate([deliverable(title="  ")], {MODULE})
    assert kept == [] and len(rejected) == 1


def test_an_invented_source_is_dropped_but_the_deliverable_survives():
    """A module nothing found is evidence for a claim nothing supports, so the
    source goes rather than the whole deliverable."""
    kept, rejected, adjusted = plan.validate(
        [deliverable(sources=[MODULE, "pkg/imaginary"])], {MODULE}
    )
    assert kept[0]["sources"] == [MODULE]
    assert len(adjusted) == 1


def test_a_deliverable_with_no_sources_is_allowed():
    kept, rejected, adjusted = plan.validate([deliverable(sources=[])], {MODULE})
    assert len(kept) == 1 and kept[0]["sources"] == []


def test_an_update_keeps_its_kind():
    kept, _, _ = plan.validate([deliverable(kind="update")], {MODULE})
    assert kept[0]["kind"] == "update"


# --------------------------------------------------------------------- render


def test_every_line_below_a_heading_is_a_list_item():
    """DocsPlan fails a non-list line long enough to be a paragraph, which is
    what keeps a plan from becoming the document it is planning."""
    text = plan.render("mirroring", [deliverable()], ["already covered"], [])
    body = text.split("---", 2)[2]
    for line in body.splitlines():
        if line.strip() and not line.startswith("#"):
            assert line.startswith("- "), line


def test_every_bullet_carries_a_source():
    text = plan.render(
        "mirroring", [deliverable()], ["covered thing"], [{"path": "x.md", "reason": "bad"}]
    )
    bullets = [line for line in text.splitlines() if line.startswith("- ")]
    assert bullets and all("[src:" in line for line in bullets)


def test_an_empty_plan_still_renders_a_sourced_bullet():
    text = plan.render("mirroring", [], [], [])
    bullets = [line for line in text.splitlines() if line.startswith("- ")]
    assert all("[src:" in line for line in bullets)


def test_the_artifact_lints_clean_under_its_own_voice(tmp_path):
    (tmp_path / "plan.md").write_text(
        plan.render("mirroring", [deliverable()], ["basics"], [{"path": "x.md", "reason": "bad"}])
    )
    config = tmp_path / "v.ini"
    config.write_text(
        f"StylesPath = {REPO_ROOT / 'styles'}\nMinAlertLevel = error\n\n"
        "[*.md]\nBasedOnStyles = DocsPlan\n"
    )
    done = subprocess.run(
        ["vale", "--config", str(config), "--output=JSON", str(tmp_path / "plan.md")],
        capture_output=True,
        text=True,
    )
    assert done.stdout.strip() == "{}", done.stdout


# ---------------------------------------------------------------- the step


def test_a_missing_registry_exits_two(tmp_path):
    assert plan.main(["--out", str(tmp_path), "--llm-cmd", "fake"]) == 2


def test_a_registry_with_no_modules_exits_one(tmp_path):
    seed_registry(tmp_path, modules=())
    assert plan.main(["--out", str(tmp_path), "--llm-cmd", "fake"]) == 1


def test_an_unreadable_registry_exits_two(tmp_path):
    (tmp_path / "registry.json").write_text("{not json")
    assert plan.main(["--out", str(tmp_path), "--llm-cmd", "fake"]) == 2


def test_a_plan_where_everything_is_rejected_exits_one(tmp_path, monkeypatch):
    seed_registry(tmp_path)
    fake_plan(monkeypatch, {"deliverables": [deliverable(type="bad")]})
    assert plan.main(["--out", str(tmp_path), "--llm-cmd", "fake"]) == 1


def test_a_run_writes_both_artifacts(tmp_path, monkeypatch):
    seed_registry(tmp_path)
    fake_plan(monkeypatch, {"deliverables": [deliverable()], "covered": ["basics"]})
    assert plan.main(["--out", str(tmp_path), "--llm-cmd", "fake", "--topic", "mirroring"]) == 0
    report = json.loads((tmp_path / "plan.json").read_text())
    assert report["deliverables"][0]["path"] == "configure-the-registry.md"
    assert report["covered"] == ["basics"]
    assert "configure-the-registry.md" in (tmp_path / "plan.md").read_text()


def test_a_model_failure_exits_two(tmp_path, monkeypatch):
    seed_registry(tmp_path)

    def boom(*a, **k):
        raise plan.step.StepError(["no usable reply"], "")

    monkeypatch.setattr(plan.step, "run_step", boom)
    assert plan.main(["--out", str(tmp_path), "--llm-cmd", "fake"]) == 2


# ------------------------------------------------------------------ evidence


def test_the_modules_reach_the_planner(tmp_path, monkeypatch):
    calls = []
    seed_registry(tmp_path, modules=(MODULE, "pkg/scheduler"))
    fake_plan(monkeypatch, {"deliverables": []}, calls)
    plan.main(["--out", str(tmp_path), "--llm-cmd", "fake"])
    assert [entry["module"] for entry in calls[0]["modules"]] == ["pkg/registry", "pkg/scheduler"]
    assert calls[0]["language"] == "python"


def test_the_public_api_reaches_the_planner(tmp_path, monkeypatch):
    calls = []
    seed_registry(tmp_path)
    (tmp_path / "api-surface.json").write_text(
        json.dumps({"modules": {MODULE: {"symbols": {"connect": {}, "disconnect": {}}}}})
    )
    fake_plan(monkeypatch, {"deliverables": []}, calls)
    plan.main(["--out", str(tmp_path), "--llm-cmd", "fake"])
    entry = calls[0]["modules"][0]
    assert entry["symbols"] == ["connect", "disconnect"]
    assert entry["symbol_count"] == 2


def test_a_module_summary_reaches_the_planner(tmp_path, monkeypatch):
    calls = []
    seed_registry(tmp_path)
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "pkg__registry.json").write_text(
        json.dumps({"module": MODULE, "purpose": "Holds module boundaries"})
    )
    fake_plan(monkeypatch, {"deliverables": []}, calls)
    plan.main(["--out", str(tmp_path), "--llm-cmd", "fake"])
    assert calls[0]["modules"][0]["purpose"] == "Holds module boundaries"


def test_the_existing_docs_reach_the_planner(tmp_path, monkeypatch):
    calls = []
    out = seed_registry(tmp_path / ".docs-gen")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "registry.md").write_text("---\nmanaged: generated\ntitle: Registry\n---\n\n# R\n")
    fake_plan(monkeypatch, {"deliverables": []}, calls)
    plan.main(["--out", str(out), "--repo", str(tmp_path), "--llm-cmd", "fake"])
    assert calls[0]["existing"] == [
        {"path": "registry.md", "title": "Registry", "managed": "generated"}
    ]


def test_an_update_naming_an_existing_page_keeps_its_source(tmp_path):
    kept, _, adjusted = plan.validate(
        [deliverable(kind="update", path="registry.md", sources=["registry.md"])],
        {MODULE, "registry.md"},
    )
    assert kept[0]["sources"] == ["registry.md"]
    assert adjusted == []


def test_changes_reach_the_planner(tmp_path, monkeypatch):
    """A commit that changes behaviour a page describes is a reason to plan an
    update, whether or not a module summary already said so."""
    calls = []
    seed_registry(tmp_path)
    changes = [
        {
            "sha": "abc1234",
            "subject": "add tiering support",
            "type": "feat",
            "scope": "cache",
            "breaking": False,
            "pr": 12,
            "date": "2026-01-01T00:00:00+00:00",
        }
    ]
    (tmp_path / "changes.json").write_text(json.dumps({"commits": changes}))
    fake_plan(monkeypatch, {"deliverables": []}, calls)
    plan.main(
        ["--out", str(tmp_path), "--llm-cmd", "fake", "--changes", str(tmp_path / "changes.json")]
    )
    assert calls[0]["changes"] == changes


def test_no_changes_file_means_no_changes_key(tmp_path, monkeypatch):
    calls = []
    seed_registry(tmp_path)
    fake_plan(monkeypatch, {"deliverables": []}, calls)
    plan.main(["--out", str(tmp_path), "--llm-cmd", "fake"])
    assert "changes" not in calls[0]


def test_an_empty_changes_file_means_no_changes_key(tmp_path, monkeypatch):
    calls = []
    seed_registry(tmp_path)
    (tmp_path / "changes.json").write_text(json.dumps({"commits": []}))
    fake_plan(monkeypatch, {"deliverables": []}, calls)
    plan.main(
        ["--out", str(tmp_path), "--llm-cmd", "fake", "--changes", str(tmp_path / "changes.json")]
    )
    assert "changes" not in calls[0]


def test_the_history_digest_reaches_the_planner(tmp_path, monkeypatch):
    calls = []
    seed_registry(tmp_path)
    (tmp_path / "git-context.md").write_text("# History\n\n- Something moved\n")
    fake_plan(monkeypatch, {"deliverables": []}, calls)
    plan.main(
        ["--out", str(tmp_path), "--llm-cmd", "fake", "--context", str(tmp_path / "git-context.md")]
    )
    assert "Something moved" in calls[0]["history"]


# -------------------------------------------------------------------- prompt


def test_the_prompt_refuses_to_plan_an_update_to_a_manual_page():
    prompt = (plan.PROMPTS / "plan.md").read_text().lower()
    assert "never plan an update to a `manual` page" in prompt


def test_the_prompt_requires_an_update_path_to_exist():
    prompt = (plan.PROMPTS / "plan.md").read_text().lower()
    assert "must appear in `existing`" in prompt


def test_the_prompt_names_the_code_as_the_spine():
    prompt = (plan.PROMPTS / "plan.md").read_text().lower()
    assert "plan only what the code supports" in prompt

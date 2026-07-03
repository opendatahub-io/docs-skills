"""Tests for load_workflow.py — YAML load, when-evaluation, and validation.

Uses the real repo as plugin_root so skill references resolve against the actual
skills/ tree and the bundled default workflow YAML.
"""

import json
import subprocess
from pathlib import Path

import pytest
from load_workflow import (
    WorkflowError,
    evaluate_when,
    load,
    resolve_yaml_path,
    validate_steps,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "docs-orchestrator" / "scripts" / "load_workflow.py"


# ── resolve_yaml_path ────────────────────────────────────────────────────────


class TestResolveYamlPath:
    def test_default_falls_back_to_plugin_default(self):
        path = resolve_yaml_path("workflow", str(REPO_ROOT), base_path=None)
        assert path is not None
        assert path.endswith("skills/docs-orchestrator/defaults/docs-workflow.yaml")

    def test_project_override_wins(self, tmp_path):
        base = tmp_path / "wsroot" / "proj-1"
        base.mkdir(parents=True)
        override = tmp_path / "wsroot" / "docs-workflow.yaml"
        override.write_text("workflow:\n  name: docs-workflow\n  steps: []\n")
        path = resolve_yaml_path("workflow", str(REPO_ROOT), base_path=str(base))
        assert path == str(override)

    def test_unknown_workflow_returns_none(self):
        assert resolve_yaml_path("does-not-exist", str(REPO_ROOT), base_path=None) is None


# ── evaluate_when ────────────────────────────────────────────────────────────


class TestEvaluateWhen:
    def test_none_is_pending(self):
        assert evaluate_when(None, {}) == "pending"

    def test_create_merge_request_enabled(self):
        assert evaluate_when("create_merge_request", {"create_merge_request": True}) == "pending"

    def test_create_merge_request_disabled(self):
        assert evaluate_when("create_merge_request", {}) == "skipped"

    def test_has_pr_with_url(self):
        assert evaluate_when("has_pr", {"pr_urls": ["http://x/pr/1"]}) == "pending"

    def test_has_pr_without_url(self):
        assert evaluate_when("has_pr", {}) == "skipped"

    def test_has_source_repo_no_source_flag(self):
        assert evaluate_when("has_source_repo", {"no_source_repo": True}) == "skipped"

    def test_has_source_repo_resolved(self):
        assert evaluate_when("has_source_repo", {"has_source_repo": True}) == "pending"

    def test_has_source_repo_unresolved_defers(self):
        assert evaluate_when("has_source_repo", {}) == "deferred"

    def test_has_many_requirements_defers(self):
        assert evaluate_when("has_many_requirements", {}) == "deferred"


# ── validate_steps ───────────────────────────────────────────────────────────


def _step(name, skill, inputs=None, when=None):
    s = {"name": name, "skill": skill, "description": "d"}
    if inputs is not None:
        s["inputs"] = inputs
    if when is not None:
        s["when"] = when
    return s


class TestValidateSteps:
    def test_valid_has_no_errors(self):
        steps = [
            _step("requirements", "docs-workflow-requirements"),
            _step("writing", "docs-workflow-writing", inputs=["requirements"]),
        ]
        assert validate_steps(steps, str(REPO_ROOT)) == []

    def test_duplicate_names(self):
        steps = [
            _step("requirements", "docs-workflow-requirements"),
            _step("requirements", "docs-workflow-writing"),
        ]
        errors = validate_steps(steps, str(REPO_ROOT))
        assert any("unique" in e.lower() or "duplicate" in e.lower() for e in errors)

    def test_unknown_skill(self):
        steps = [_step("x", "docs-workflow-nonexistent")]
        errors = validate_steps(steps, str(REPO_ROOT))
        assert any("nonexistent" in e for e in errors)

    def test_plugin_qualified_skill_resolves(self):
        steps = [_step("x", "docs-skills:docs-workflow-requirements")]
        assert validate_steps(steps, str(REPO_ROOT)) == []

    def test_input_references_missing_step(self):
        steps = [_step("writing", "docs-workflow-writing", inputs=["ghost"])]
        errors = validate_steps(steps, str(REPO_ROOT))
        assert any("ghost" in e for e in errors)


# ── load (integration against the real default workflow) ─────────────────────


class TestLoad:
    def test_loads_default_workflow(self):
        result = load("workflow", str(REPO_ROOT), options={"create_merge_request": False})
        names = [s["name"] for s in result["steps"]]
        assert "requirements" in names
        assert result["yaml_path"].endswith("defaults/docs-workflow.yaml")

    def test_status_classification(self):
        result = load("workflow", str(REPO_ROOT), options={"create_merge_request": False})
        status = {s["name"]: s["status"] for s in result["steps"]}
        assert status["requirements"] == "pending"  # no when
        assert status["code-analysis"] == "deferred"  # has_source_repo, unresolved
        assert status["quality-gate"] == "pending"  # no when — always runs
        assert status["create-merge-request"] == "skipped"  # flag off
        assert status["pipeline-diagnostics"] == "pending"

    def test_create_mr_enabled_makes_step_pending(self):
        result = load("workflow", str(REPO_ROOT), options={"create_merge_request": True})
        status = {s["name"]: s["status"] for s in result["steps"]}
        assert status["create-merge-request"] == "pending"

    def test_missing_workflow_raises(self):
        with pytest.raises(WorkflowError):
            load("does-not-exist", str(REPO_ROOT), options={})


# ── CLI (via uv run --script, exercises the PEP 723 path) ────────────────────


class TestCli:
    def _run(self, args):
        return subprocess.run(
            ["uv", "run", "--script", str(SCRIPT), *args],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )

    def test_cli_emits_step_json(self, tmp_path):
        opts = tmp_path / "options.json"
        opts.write_text(json.dumps({"create_merge_request": False}))
        result = self._run(
            ["--workflow", "workflow", "--plugin-root", str(REPO_ROOT), "--options", str(opts)]
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert any(s["name"] == "requirements" for s in payload["steps"])

    def test_cli_unknown_workflow_exits_nonzero(self, tmp_path):
        opts = tmp_path / "options.json"
        opts.write_text("{}")
        result = self._run(
            ["--workflow", "ghost", "--plugin-root", str(REPO_ROOT), "--options", str(opts)]
        )
        assert result.returncode != 0

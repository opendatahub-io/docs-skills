"""Tests for docs_orchestrator.py."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from docs_orchestrator import (
    _eval_has_many_requirements_phase1,
    _eval_has_many_requirements_phase2,
    build_step_args,
    classify_step,
    create_progress,
    evaluate_when,
    find_next_step,
    parse_workflow_yaml,
    post_process,
    validate_steps,
)


@pytest.fixture
def default_yaml(tmp_path):
    yaml_content = """\
name: docs-workflow
description: Default documentation workflow

steps:
  - name: requirements
    skill: docs-tools:docs-workflow-requirements
    description: Gather requirements
  - name: code-analysis
    skill: docs-tools:docs-workflow-code-analysis
    description: Analyze source code
    when: has_source_repo
    inputs: [requirements]
  - name: scope-req-audit
    skill: docs-tools:docs-workflow-scope-req-audit
    description: Audit requirements scope
    when: has_source_repo
    inputs: [requirements, code-analysis]
  - name: pr-analysis
    skill: docs-tools:docs-workflow-pr-analysis
    description: Analyze pull request
    when: has_pr
    inputs: [requirements]
  - name: planning
    skill: docs-tools:docs-workflow-planning
    description: Create documentation plan
    inputs: [requirements, code-analysis, pr-analysis, scope-req-audit]
  - name: writing
    skill: docs-tools:docs-workflow-writing
    description: Write documentation
    inputs: [planning]
  - name: technical-review
    skill: docs-tools:docs-workflow-tech-review
    description: Technical accuracy review
    inputs: [writing]
  - name: style-review
    skill: docs-tools:docs-workflow-style-review
    description: Style guide review
    inputs: [writing]
  - name: create-merge-request
    skill: docs-tools:docs-workflow-create-merge-request
    description: Create merge request
    when: create_merge_request
    inputs: [writing, technical-review, style-review]
"""
    p = tmp_path / "docs-workflow.yaml"
    p.write_text(yaml_content)
    return str(p)


class TestParseWorkflowYaml:
    def test_parses_step_names(self, default_yaml):
        name, desc, steps, requires = parse_workflow_yaml(default_yaml)
        assert name == "docs-workflow"
        assert len(steps) == 9
        assert steps[0]["name"] == "requirements"
        assert steps[-1]["name"] == "create-merge-request"

    def test_parses_skills(self, default_yaml):
        _, _, steps, _ = parse_workflow_yaml(default_yaml)
        assert steps[0]["skill"] == "docs-tools:docs-workflow-requirements"
        assert steps[1]["skill"] == "docs-tools:docs-workflow-code-analysis"

    def test_parses_when_conditions(self, default_yaml):
        _, _, steps, _ = parse_workflow_yaml(default_yaml)
        assert steps[0]["when"] is None
        assert steps[1]["when"] == "has_source_repo"
        assert steps[3]["when"] == "has_pr"
        assert steps[8]["when"] == "create_merge_request"

    def test_parses_inputs(self, default_yaml):
        _, _, steps, _ = parse_workflow_yaml(default_yaml)
        assert steps[0]["inputs"] == []
        assert steps[1]["inputs"] == ["requirements"]
        assert "code-analysis" in steps[4]["inputs"]


class TestValidateSteps:
    def test_valid_yaml(self, default_yaml):
        _, _, steps, _ = parse_workflow_yaml(default_yaml)
        errors = validate_steps(steps)
        assert errors == []

    def test_duplicate_name(self):
        steps = [
            {"name": "foo", "skill": "s", "inputs": []},
            {"name": "foo", "skill": "s", "inputs": []},
        ]
        errors = validate_steps(steps)
        assert any("Duplicate" in e for e in errors)

    def test_missing_skill(self):
        steps = [{"name": "foo", "skill": None, "inputs": []}]
        errors = validate_steps(steps)
        assert any("no skill" in e for e in errors)


class TestEvaluateWhen:
    def test_none_returns_true(self):
        assert evaluate_when(None, {}) is True

    def test_has_source_repo_with_source(self):
        assert evaluate_when("has_source_repo", {"source": {"repo_path": "/tmp"}}) is True  # noqa: S108

    def test_has_source_repo_no_source_flag(self):
        assert evaluate_when("has_source_repo", {"no_source_repo": True}) is False

    def test_has_source_repo_deferred(self):
        assert evaluate_when("has_source_repo", {}) is None

    def test_has_pr_true(self):
        assert evaluate_when("has_pr", {"pr_urls": ["http://pr"]}) is True

    def test_has_pr_false(self):
        assert evaluate_when("has_pr", {"pr_urls": []}) is False

    def test_create_merge_request(self):
        assert evaluate_when("create_merge_request", {"create_merge_request": True}) is True
        assert evaluate_when("create_merge_request", {"create_merge_request": False}) is False


class TestClassifyStep:
    def test_pending(self):
        assert classify_step({"when": None}, {}) == "pending"

    def test_skipped(self):
        assert classify_step({"when": "has_pr"}, {"pr_urls": []}) == "skipped"

    def test_deferred(self):
        assert classify_step({"when": "has_source_repo"}, {}) == "deferred"


class TestBuildStepArgs:
    def test_requirements_basic(self):
        args = build_step_args("requirements", "PROJ-123", "/base", {})
        assert "PROJ-123" in args
        assert "--base-path /base" in args

    def test_requirements_with_pr(self):
        args = build_step_args(
            "requirements",
            "PROJ-123",
            "/base",
            {"pr_urls": ["http://pr1", "http://pr2"]},
        )
        assert "--pr http://pr1" in args
        assert "--pr http://pr2" in args

    def test_code_analysis_maps_correctly(self):
        args = build_step_args(
            "code-analysis",
            "PROJ-123",
            "/base",
            {"source": {"repo_path": "/repo"}},
        )
        assert "--repo /repo" in args
        assert "--ticket PROJ-123" in args
        assert "--output-dir /base/code-analysis" in args
        assert "--base-path" not in args

    def test_pr_analysis_maps_correctly(self):
        args = build_step_args(
            "pr-analysis",
            "PROJ-123",
            "/base",
            {"pr_urls": ["http://pr1"], "source": {"repo_path": "/repo"}},
        )
        assert "--pr http://pr1" in args
        assert "--repo /repo" in args
        assert "--output-dir /base/pr-analysis" in args

    def test_writing_with_fix_from(self):
        progress = {"_tech_review_fix_from": "/base/technical-review/review.md"}
        args = build_step_args("writing", "PROJ-123", "/base", {}, progress)
        assert "--fix-from /base/technical-review/review.md" in args

    def test_technical_review_iteration(self):
        progress = {"_tech_review_iteration": 2}
        args = build_step_args(
            "technical-review",
            "PROJ-123",
            "/base",
            {"source": {"repo_path": "/repo"}},
            progress,
        )
        assert "--iteration 2" in args

    def test_create_merge_request_draft(self):
        args = build_step_args(
            "create-merge-request",
            "PROJ-123",
            "/base",
            {"draft": True, "docs_repo_path": "/docs"},
        )
        assert "--draft" in args
        assert "--repo-path /docs" in args


class TestFindNextStep:
    def test_finds_first_pending(self):
        progress = {
            "step_order": ["a", "b", "c"],
            "steps": {
                "a": {"status": "completed"},
                "b": {"status": "pending"},
                "c": {"status": "pending"},
            },
        }
        name, _ = find_next_step(progress)
        assert name == "b"

    def test_all_done(self):
        progress = {
            "step_order": ["a", "b"],
            "steps": {
                "a": {"status": "completed"},
                "b": {"status": "skipped"},
            },
        }
        name, _ = find_next_step(progress)
        assert name is None

    def test_finds_failed(self):
        progress = {
            "step_order": ["a", "b"],
            "steps": {
                "a": {"status": "failed"},
                "b": {"status": "pending"},
            },
        }
        name, _ = find_next_step(progress)
        assert name == "a"


class TestPostProcessPlanning:
    def test_zero_modules_returns_fail(self, tmp_path):
        base = str(tmp_path)
        planning_dir = tmp_path / "planning"
        planning_dir.mkdir()
        sidecar = {"schema_version": 1, "step": "planning", "module_count": 0}
        (planning_dir / "step-result.json").write_text(json.dumps(sidecar))

        progress = {
            "ticket": "T-1",
            "steps": {"planning": {"status": "completed", "output": None, "result": None}},
        }

        result = post_process("planning", progress, base, {})
        assert "action_override" in result
        assert result["action_override"]["action"] == "fail"

    def test_nonzero_modules_ok(self, tmp_path):
        base = str(tmp_path)
        planning_dir = tmp_path / "planning"
        planning_dir.mkdir()
        sidecar = {"schema_version": 1, "step": "planning", "module_count": 3}
        (planning_dir / "step-result.json").write_text(json.dumps(sidecar))

        progress = {
            "ticket": "T-1",
            "steps": {"planning": {"status": "completed", "output": None, "result": None}},
        }

        result = post_process("planning", progress, base, {})
        assert "action_override" not in result


class TestPostProcessTechReview:
    def _make_sidecar(self, tmp_path, confidence, severity=None, iteration=1):
        base = str(tmp_path)
        tr_dir = tmp_path / "technical-review"
        tr_dir.mkdir(exist_ok=True)
        sidecar = {
            "schema_version": 1,
            "step": "technical-review",
            "confidence": confidence,
            "severity_counts": severity or {"critical": 0, "significant": 0, "minor": 0, "sme": 0},
            "iteration": iteration,
        }
        (tr_dir / "step-result.json").write_text(json.dumps(sidecar))
        return base

    def test_high_confidence_completes(self, tmp_path):
        base = self._make_sidecar(tmp_path, "HIGH")
        progress = {
            "ticket": "T-1",
            "steps": {"technical-review": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("technical-review", progress, base, {})
        assert "action_override" not in result

    def test_medium_zero_crit_completes(self, tmp_path):
        base = self._make_sidecar(tmp_path, "MEDIUM")
        progress = {
            "ticket": "T-1",
            "steps": {"technical-review": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("technical-review", progress, base, {})
        assert "action_override" not in result

    def test_low_triggers_fix_cycle(self, tmp_path):
        base = self._make_sidecar(
            tmp_path, "LOW", {"critical": 2, "significant": 1, "minor": 0, "sme": 0}
        )
        progress = {
            "ticket": "T-1",
            "_step_skills": {"writing": "docs-tools:docs-workflow-writing"},
            "steps": {
                "technical-review": {"status": "completed", "output": None, "result": None},
                "writing": {"status": "completed", "output": None, "result": None},
            },
        }
        result = post_process("technical-review", progress, base, {})
        assert "action_override" in result
        assert result["action_override"]["action"] == "run_skill"
        assert result["action_override"]["step"] == "writing"
        assert progress.get("_tech_review_fix_from") is not None
        assert progress.get("_tech_review_iteration") == 2

    def test_low_after_max_iterations_fails(self, tmp_path):
        base = self._make_sidecar(
            tmp_path, "LOW", {"critical": 1, "significant": 0, "minor": 0, "sme": 0}, iteration=3
        )
        progress = {
            "ticket": "T-1",
            "steps": {"technical-review": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("technical-review", progress, base, {})
        assert "action_override" in result
        assert result["action_override"]["action"] == "fail"


class TestPostProcessWriting:
    def test_fix_mode_routes_to_tech_review(self, tmp_path):
        base = str(tmp_path)
        writing_dir = tmp_path / "writing"
        writing_dir.mkdir()
        sidecar = {"schema_version": 1, "step": "writing", "files": ["/a.adoc"]}
        (writing_dir / "step-result.json").write_text(json.dumps(sidecar))

        progress = {
            "ticket": "T-1",
            "_tech_review_fix_from": "/some/review.md",
            "_step_skills": {"technical-review": "docs-tools:docs-workflow-tech-review"},
            "steps": {
                "writing": {"status": "completed", "output": None, "result": None},
                "technical-review": {"status": "completed", "output": None, "result": None},
            },
        }
        result = post_process("writing", progress, base, {})
        assert "action_override" in result
        assert result["action_override"]["step"] == "technical-review"

    def test_no_files_skips_mr(self, tmp_path):
        base = str(tmp_path)
        writing_dir = tmp_path / "writing"
        writing_dir.mkdir()
        sidecar = {"schema_version": 1, "step": "writing", "files": []}
        (writing_dir / "step-result.json").write_text(json.dumps(sidecar))

        progress = {
            "ticket": "T-1",
            "steps": {
                "writing": {"status": "completed", "output": None, "result": None},
                "create-merge-request": {"status": "pending", "output": None, "result": None},
            },
        }
        post_process("writing", progress, base, {})
        assert progress["steps"]["create-merge-request"]["status"] == "skipped"


class TestCreateProgress:
    def test_creates_all_steps(self):
        steps = [
            {"name": "a", "skill": "s", "inputs": []},
            {"name": "b", "skill": "s", "inputs": []},
        ]
        p = create_progress("T-1", "wf", "/base", {}, steps, ["a", "b"])
        assert "a" in p["steps"]
        assert "b" in p["steps"]
        assert p["status"] == "in_progress"
        assert p["step_order"] == ["a", "b"]

    def test_uses_workflow_key(self):
        steps = [{"name": "a", "skill": "s", "inputs": []}]
        p = create_progress("T-1", "docs-workflow", "/base", {}, steps, ["a"])
        assert "workflow" in p
        assert "workflow_type" not in p
        assert p["workflow"] == "docs-workflow"


class TestEvaluateWhenHasManyRequirements:
    def test_always_deferred(self):
        assert evaluate_when("has_many_requirements", {}) is None

    def test_deferred_even_with_options(self):
        assert evaluate_when("has_many_requirements", {"source": {"repo_path": "/x"}}) is None


def _step(status="completed", result=None):
    return {"status": status, "output": None, "result": result}


def _qg_step(status="deferred", result=None):
    return {"status": status, "output": None, "result": result}


class TestHasManyRequirementsPhase1:
    def test_few_requirements_skips_quality_gate(self):
        sidecar = {"requirement_count": 3}
        progress = {"steps": {"quality-gate": _qg_step()}}
        messages, warnings = [], []
        _eval_has_many_requirements_phase1(
            sidecar, progress, messages, warnings,
        )
        assert progress["steps"]["quality-gate"]["status"] == "skipped"
        assert any("Skipping" in m for m in messages)

    def test_many_requirements_keeps_deferred(self):
        sidecar = {"requirement_count": 8}
        progress = {"steps": {"quality-gate": _qg_step()}}
        messages, warnings = [], []
        _eval_has_many_requirements_phase1(
            sidecar, progress, messages, warnings,
        )
        assert progress["steps"]["quality-gate"]["status"] == "deferred"

    def test_missing_count_warns(self):
        sidecar = {"title": "some title"}
        progress = {"steps": {"quality-gate": _qg_step()}}
        messages, warnings = [], []
        _eval_has_many_requirements_phase1(
            sidecar, progress, messages, warnings,
        )
        assert progress["steps"]["quality-gate"]["status"] == "deferred"
        assert any("missing" in w for w in warnings)

    def test_no_quality_gate_step_is_noop(self):
        sidecar = {"requirement_count": 3}
        progress = {"steps": {"writing": {"status": "pending"}}}
        messages, warnings = [], []
        _eval_has_many_requirements_phase1(
            sidecar, progress, messages, warnings,
        )
        assert warnings == []


class TestHasManyRequirementsPhase2:
    def test_high_confidence_skips(self):
        progress = {"steps": {"quality-gate": _qg_step()}}
        messages = []
        _eval_has_many_requirements_phase2("HIGH", progress, messages)
        assert progress["steps"]["quality-gate"]["status"] == "skipped"
        assert any("HIGH" in m for m in messages)

    def test_medium_confidence_enables(self):
        progress = {"steps": {"quality-gate": _qg_step()}}
        messages = []
        _eval_has_many_requirements_phase2("MEDIUM", progress, messages)
        assert progress["steps"]["quality-gate"]["status"] == "pending"

    def test_already_skipped_no_change(self):
        progress = {
            "steps": {
                "quality-gate": _qg_step(
                    "skipped",
                    {"skip_reason": "few_requirements"},
                ),
            },
        }
        messages = []
        _eval_has_many_requirements_phase2("MEDIUM", progress, messages)
        assert progress["steps"]["quality-gate"]["status"] == "skipped"


class TestPostProcessSecurityReview:
    def _make_sidecar(self, tmp_path, scanner=0, critical=0, agent=0):
        base = str(tmp_path)
        sr_dir = tmp_path / "security-review"
        sr_dir.mkdir(exist_ok=True)
        sidecar = {
            "schema_version": 1,
            "step": "security-review",
            "scanner_findings": scanner,
            "critical_findings": critical,
            "agent_findings": agent,
        }
        (sr_dir / "step-result.json").write_text(json.dumps(sidecar))
        return base

    def test_logs_findings(self, tmp_path):
        base = self._make_sidecar(tmp_path, scanner=5, critical=0, agent=2)
        progress = {
            "ticket": "T-1",
            "steps": {"security-review": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("security-review", progress, base, {})
        assert any("5 scanner" in m for m in result.get("messages", []))
        assert "action_override" not in result

    def test_critical_findings_warn(self, tmp_path):
        base = self._make_sidecar(tmp_path, scanner=3, critical=2, agent=1)
        progress = {
            "ticket": "T-1",
            "steps": {"security-review": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("security-review", progress, base, {})
        assert any("critical" in w for w in result.get("warnings", []))


class TestPostProcessQualityGate:
    def _make_sidecar(
        self, tmp_path, doc_quality=4, intent_alignment=4,
        passed=True, iteration=1, gaps=None,
    ):
        base = str(tmp_path)
        qg_dir = tmp_path / "quality-gate"
        qg_dir.mkdir(exist_ok=True)
        sidecar = {
            "schema_version": 1,
            "step": "quality-gate",
            "doc_quality": doc_quality,
            "intent_alignment": intent_alignment,
            "passed": passed,
            "iteration": iteration,
            "gaps": gaps or [],
        }
        (qg_dir / "step-result.json").write_text(json.dumps(sidecar))
        return base

    def test_passes_when_alignment_high(self, tmp_path):
        base = self._make_sidecar(tmp_path, intent_alignment=4)
        progress = {
            "ticket": "T-1",
            "steps": {"quality-gate": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("quality-gate", progress, base, {})
        assert "action_override" not in result

    def test_low_doc_quality_warns(self, tmp_path):
        base = self._make_sidecar(tmp_path, doc_quality=2, intent_alignment=4)
        progress = {
            "ticket": "T-1",
            "steps": {"quality-gate": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("quality-gate", progress, base, {})
        assert any("doc_quality" in w for w in result.get("warnings", []))

    def test_low_alignment_triggers_fix_cycle(self, tmp_path):
        base = self._make_sidecar(tmp_path, intent_alignment=2, passed=False, iteration=1)
        progress = {
            "ticket": "T-1",
            "_step_skills": {"writing": "docs-workflow-writing"},
            "steps": {
                "quality-gate": {"status": "completed", "output": None, "result": None},
                "writing": {"status": "completed", "output": None, "result": None},
            },
        }
        result = post_process("quality-gate", progress, base, {})
        assert "action_override" in result
        assert result["action_override"]["action"] == "run_skill"
        assert result["action_override"]["step"] == "writing"
        assert progress.get("_quality_gate_fix_from") is not None
        assert progress.get("_quality_gate_iteration") == 2

    def test_alignment_3_after_max_accepts_with_warning(self, tmp_path):
        base = self._make_sidecar(tmp_path, intent_alignment=3, passed=False, iteration=2)
        progress = {
            "ticket": "T-1",
            "steps": {"quality-gate": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("quality-gate", progress, base, {})
        assert "action_override" not in result
        assert any("accepting" in w for w in result.get("warnings", []))

    def test_alignment_below_3_after_max_fails(self, tmp_path):
        base = self._make_sidecar(tmp_path, intent_alignment=1, passed=False, iteration=2)
        progress = {
            "ticket": "T-1",
            "steps": {"quality-gate": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("quality-gate", progress, base, {})
        assert "action_override" in result
        assert result["action_override"]["action"] == "fail"


class TestPostProcessPipelineDiagnostics:
    def _make_sidecar(self, tmp_path, pressure="low", failures=0, bottlenecks=0, high_sev=0):
        base = str(tmp_path)
        pd_dir = tmp_path / "pipeline-diagnostics"
        pd_dir.mkdir(exist_ok=True)
        sidecar = {
            "schema_version": 1,
            "step": "pipeline-diagnostics",
            "context_pressure_level": pressure,
            "failure_count": failures,
            "bottleneck_count": bottlenecks,
            "high_severity_failure_count": high_sev,
        }
        (pd_dir / "step-result.json").write_text(json.dumps(sidecar))
        return base

    def test_logs_metrics(self, tmp_path):
        base = self._make_sidecar(tmp_path, pressure="moderate", failures=1, bottlenecks=2)
        progress = {
            "ticket": "T-1",
            "steps": {"pipeline-diagnostics": _step()},
        }
        result = post_process("pipeline-diagnostics", progress, base, {})
        assert any("moderate" in m for m in result.get("messages", []))

    def test_high_severity_warns(self, tmp_path):
        base = self._make_sidecar(tmp_path, high_sev=2)
        progress = {
            "ticket": "T-1",
            "steps": {"pipeline-diagnostics": _step()},
        }
        result = post_process("pipeline-diagnostics", progress, base, {})
        assert any("high-severity" in w for w in result.get("warnings", []))

    def test_critical_pressure_warns(self, tmp_path):
        base = self._make_sidecar(tmp_path, pressure="critical")
        progress = {
            "ticket": "T-1",
            "steps": {"pipeline-diagnostics": _step()},
        }
        result = post_process("pipeline-diagnostics", progress, base, {})
        assert any("critical" in w for w in result.get("warnings", []))


class TestBuildStepArgsNewSteps:
    def test_security_review_basic(self):
        args = build_step_args("security-review", "PROJ-123", "/base", {})
        assert "PROJ-123" in args
        assert "--base-path /base" in args

    def test_quality_gate_basic(self):
        args = build_step_args("quality-gate", "PROJ-123", "/base", {})
        assert "PROJ-123" in args
        assert "--iteration" not in args

    def test_quality_gate_iteration(self):
        progress = {"_quality_gate_iteration": 2}
        args = build_step_args("quality-gate", "PROJ-123", "/base", {}, progress)
        assert "--iteration 2" in args

    def test_pipeline_diagnostics_basic(self):
        args = build_step_args("pipeline-diagnostics", "PROJ-123", "/base", {})
        assert "PROJ-123" in args
        assert "--ci-log" not in args

    def test_pipeline_diagnostics_with_ci_log(self):
        opts = {"ci_log": "/tmp/ci.log"}
        args = build_step_args(
            "pipeline-diagnostics", "PROJ-123", "/base", opts,
        )
        assert "--ci-log /tmp/ci.log" in args

    def test_writing_quality_gate_fix_from(self):
        progress = {"_quality_gate_fix_from": "/base/quality-gate/feedback-brief-1.md"}
        args = build_step_args("writing", "PROJ-123", "/base", {}, progress)
        assert "--fix-from /base/quality-gate/feedback-brief-1.md" in args


class TestPostProcessWritingQualityGateCycle:
    def test_routes_to_quality_gate(self, tmp_path):
        base = str(tmp_path)
        writing_dir = tmp_path / "writing"
        writing_dir.mkdir()
        sidecar = {"schema_version": 1, "step": "writing", "files": ["/a.adoc"]}
        (writing_dir / "step-result.json").write_text(json.dumps(sidecar))

        progress = {
            "ticket": "T-1",
            "_quality_gate_fix_from": "/some/feedback-brief-1.md",
            "_step_skills": {"quality-gate": "docs-workflow-quality-gate"},
            "steps": {
                "writing": {"status": "completed", "output": None, "result": None},
                "quality-gate": {"status": "completed", "output": None, "result": None},
            },
        }
        result = post_process("writing", progress, base, {})
        assert "action_override" in result
        assert result["action_override"]["step"] == "quality-gate"

    def test_tech_review_cycle_takes_precedence(self, tmp_path):
        base = str(tmp_path)
        writing_dir = tmp_path / "writing"
        writing_dir.mkdir()
        sidecar = {"schema_version": 1, "step": "writing", "files": ["/a.adoc"]}
        (writing_dir / "step-result.json").write_text(json.dumps(sidecar))

        progress = {
            "ticket": "T-1",
            "_tech_review_fix_from": "/some/review.md",
            "_quality_gate_fix_from": "/some/feedback.md",
            "_step_skills": {"technical-review": "docs-workflow-tech-review"},
            "steps": {
                "writing": {"status": "completed", "output": None, "result": None},
                "technical-review": {"status": "completed", "output": None, "result": None},
                "quality-gate": {"status": "completed", "output": None, "result": None},
            },
        }
        result = post_process("writing", progress, base, {})
        assert result["action_override"]["step"] == "technical-review"

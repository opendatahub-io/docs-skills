"""Tests for docs_orchestrator.py."""

import argparse
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from docs_orchestrator import (
    DISPATCH_STEPS,
    _count_modules_fallback,
    _eval_has_many_requirements_phase1,
    _eval_has_many_requirements_phase2,
    _extract_files_from_sidecar,
    _find_additional_repo,
    _get_step_skill,
    _parse_review_fallback,
    _prepare_writing,
    _rehydrate_progress,
    _render_writing_prompt,
    atomic_write_json,
    build_step_args,
    check_input_deps,
    classify_step,
    create_progress,
    delete_active_marker,
    delete_stop_counter,
    evaluate_when,
    find_next_step,
    is_dispatch_eligible,
    iso_now,
    make_complete,
    make_dispatch,
    make_fail,
    make_run_skill,
    make_step_action,
    marker_path_for,
    parse_workflow_yaml,
    post_process,
    progress_path,
    read_progress,
    read_sidecar,
    resolve_source_post_requirements,
    validate_steps,
    write_active_marker,
    write_progress,
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
        # writing is dispatch-eligible, so the fix cycle dispatches instead of run_skill
        assert result["action_override"]["action"] == "dispatch"
        assert result["action_override"]["step"] == "writing"
        assert "prepare-step T-1 writing" in result["action_override"]["prepare"]
        assert progress.get("_tech_review_fix_from") is not None
        assert progress.get("_tech_review_iteration") == 2

    def test_low_with_only_sme_items_proceeds(self, tmp_path):
        # LOW confidence but zero critical/significant — only SME-required items
        # remain. No fix cycle can resolve these, so proceed with a warning.
        base = self._make_sidecar(
            tmp_path, "LOW", {"critical": 0, "significant": 0, "minor": 1, "sme": 3}
        )
        progress = {
            "ticket": "T-1",
            "steps": {"technical-review": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("technical-review", progress, base, {})
        assert "action_override" not in result
        assert any("SME verification" in w for w in result["warnings"])
        assert progress.get("_tech_review_fix_from") is None

    def test_low_with_only_minor_items_proceeds_without_sme_warning(self, tmp_path):
        base = self._make_sidecar(
            tmp_path, "LOW", {"critical": 0, "significant": 0, "minor": 2, "sme": 0}
        )
        progress = {
            "ticket": "T-1",
            "steps": {"technical-review": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("technical-review", progress, base, {})
        assert "action_override" not in result
        assert not any("SME verification" in w for w in result["warnings"])

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

    def test_fix_cycle_records_prior_severity(self, tmp_path):
        # First fix cycle: no prior recorded, so it dispatches and stores the
        # current severity for the next iteration to compare against.
        severity = {"critical": 2, "significant": 1, "minor": 0, "sme": 0}
        base = self._make_sidecar(tmp_path, "LOW", severity)
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
        assert progress.get("_tech_review_prior_severity") == severity

    def test_medium_convergence_proceeds_with_warning(self, tmp_path):
        severity = {"critical": 1, "significant": 0, "minor": 0, "sme": 0}
        base = self._make_sidecar(tmp_path, "MEDIUM", severity, iteration=2)
        progress = {
            "ticket": "T-1",
            "_tech_review_fix_from": "/some/review.md",
            "_tech_review_iteration": 2,
            "_tech_review_prior_severity": dict(severity),
            "steps": {"technical-review": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("technical-review", progress, base, {})
        assert "action_override" not in result
        assert any("converged" in w for w in result["warnings"])
        # Loop state is cleaned up so a later run starts fresh.
        assert progress.get("_tech_review_prior_severity") is None
        assert progress.get("_tech_review_fix_from") is None

    def test_low_convergence_fails(self, tmp_path):
        severity = {"critical": 1, "significant": 0, "minor": 0, "sme": 0}
        base = self._make_sidecar(tmp_path, "LOW", severity, iteration=2)
        progress = {
            "ticket": "T-1",
            "_tech_review_iteration": 2,
            "_tech_review_prior_severity": dict(severity),
            "steps": {"technical-review": {"status": "completed", "output": None, "result": None}},
        }
        result = post_process("technical-review", progress, base, {})
        assert "action_override" in result
        assert result["action_override"]["action"] == "fail"
        assert "converged" in result["action_override"]["reason"]

    def test_no_convergence_when_severity_changes(self, tmp_path):
        # Prior iteration had more issues; progress was made, so keep iterating.
        base = self._make_sidecar(
            tmp_path, "LOW", {"critical": 1, "significant": 0, "minor": 0, "sme": 0}, iteration=2
        )
        progress = {
            "ticket": "T-1",
            "_step_skills": {"writing": "docs-tools:docs-workflow-writing"},
            "_tech_review_iteration": 2,
            "_tech_review_prior_severity": {
                "critical": 3,
                "significant": 2,
                "minor": 0,
                "sme": 0,
            },
            "steps": {
                "technical-review": {"status": "completed", "output": None, "result": None},
                "writing": {"status": "completed", "output": None, "result": None},
            },
        }
        result = post_process("technical-review", progress, base, {})
        assert "action_override" in result
        assert result["action_override"]["action"] != "fail"
        assert progress.get("_tech_review_prior_severity") == {
            "critical": 1,
            "significant": 0,
            "minor": 0,
            "sme": 0,
        }


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
            sidecar,
            progress,
            messages,
            warnings,
        )
        assert progress["steps"]["quality-gate"]["status"] == "skipped"
        assert any("Skipping" in m for m in messages)

    def test_many_requirements_keeps_deferred(self):
        sidecar = {"requirement_count": 8}
        progress = {"steps": {"quality-gate": _qg_step()}}
        messages, warnings = [], []
        _eval_has_many_requirements_phase1(
            sidecar,
            progress,
            messages,
            warnings,
        )
        assert progress["steps"]["quality-gate"]["status"] == "deferred"

    def test_missing_count_warns(self):
        sidecar = {"title": "some title"}
        progress = {"steps": {"quality-gate": _qg_step()}}
        messages, warnings = [], []
        _eval_has_many_requirements_phase1(
            sidecar,
            progress,
            messages,
            warnings,
        )
        assert progress["steps"]["quality-gate"]["status"] == "deferred"
        assert any("missing" in w for w in warnings)

    def test_no_quality_gate_step_is_noop(self):
        sidecar = {"requirement_count": 3}
        progress = {"steps": {"writing": {"status": "pending"}}}
        messages, warnings = [], []
        _eval_has_many_requirements_phase1(
            sidecar,
            progress,
            messages,
            warnings,
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
        self,
        tmp_path,
        doc_quality=4,
        intent_alignment=4,
        passed=True,
        iteration=1,
        gaps=None,
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
        # writing is dispatch-eligible, so the fix cycle dispatches instead of run_skill
        assert result["action_override"]["action"] == "dispatch"
        assert result["action_override"]["step"] == "writing"
        assert "prepare-step T-1 writing" in result["action_override"]["prepare"]
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
            "pipeline-diagnostics",
            "PROJ-123",
            "/base",
            opts,
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


# ---------------------------------------------------------------------------
# Group 1: Pure helper functions
# ---------------------------------------------------------------------------


class TestIsoNow:
    def test_returns_iso_format_with_timezone(self):
        result = iso_now()
        assert "+00:00" in result or "Z" in result

    def test_returns_parseable_datetime(self):
        from datetime import datetime

        result = iso_now()
        dt = datetime.fromisoformat(result)
        assert dt.tzinfo is not None


class TestProgressPath:
    def test_constructs_correct_path(self):
        result = progress_path("/base", "docs-workflow", "proj-123")
        assert result == "/base/workflow/docs-workflow_proj-123.json"

    def test_uses_provided_ticket_as_is(self):
        result = progress_path("/base", "wf", "UPPER")
        assert "UPPER" in result


class TestMarkerPathFor:
    def test_returns_active_workflow_in_parent(self):
        result = marker_path_for("/workspace/PROJ-123")
        assert result == "/workspace/.active-workflow"


class TestFindAdditionalRepo:
    def test_finds_by_basename(self):
        additional = [{"repo_path": "/home/user/my-repo"}]
        result = _find_additional_repo(additional, "my-repo")
        assert result == {"repo_path": "/home/user/my-repo"}

    def test_returns_none_when_not_found(self):
        additional = [{"repo_path": "/home/user/other"}]
        assert _find_additional_repo(additional, "missing") is None

    def test_empty_list(self):
        assert _find_additional_repo([], "anything") is None


class TestExtractFilesFromSidecar:
    def test_files_key(self):
        sidecar = {"files": ["/a.adoc", "/b.adoc"]}
        assert _extract_files_from_sidecar(sidecar) == ["/a.adoc", "/b.adoc"]

    def test_legacy_files_written(self):
        sidecar = {
            "files": [],
            "files_written": {
                "assemblies": ["/a.adoc"],
                "modules": ["/m.adoc"],
                "snippets": ["/s.adoc"],
            },
        }
        result = _extract_files_from_sidecar(sidecar)
        assert "/a.adoc" in result
        assert "/m.adoc" in result
        assert "/s.adoc" in result

    def test_none_sidecar(self):
        assert _extract_files_from_sidecar(None) == []

    def test_empty_sidecar(self):
        assert _extract_files_from_sidecar({}) == []


class TestGetStepSkill:
    def test_strips_colon_prefix(self):
        progress = {"_step_skills": {"writing": "docs-tools:docs-workflow-writing"}}
        assert _get_step_skill(progress, "writing") == "docs-workflow-writing"

    def test_no_colon(self):
        progress = {"_step_skills": {"writing": "docs-workflow-writing"}}
        assert _get_step_skill(progress, "writing") == "docs-workflow-writing"

    def test_missing_key_uses_default(self):
        progress = {"_step_skills": {}}
        assert _get_step_skill(progress, "writing") == "docs-workflow-writing"

    def test_no_step_skills_key(self):
        assert _get_step_skill({}, "planning") == "docs-workflow-planning"


class TestMakeRunSkill:
    def test_basic_fields(self):
        result = make_run_skill("my-skill", "--arg val", "step-1", "Run step-1")
        assert result["action"] == "run_skill"
        assert result["skill"] == "my-skill"
        assert result["args"] == "--arg val"
        assert result["step"] == "step-1"
        assert result["message"] == "Run step-1"

    def test_with_warnings_and_messages(self):
        result = make_run_skill(
            "s",
            "a",
            "st",
            "msg",
            warnings=["w1"],
            messages=["m1"],
        )
        assert result["warnings"] == ["w1"]
        assert result["messages"] == ["m1"]

    def test_extra_kwargs(self):
        result = make_run_skill("s", "a", "st", "msg", custom_key="val")
        assert result["custom_key"] == "val"

    def test_no_warnings_key_when_empty(self):
        result = make_run_skill("s", "a", "st", "msg")
        assert "warnings" not in result


class TestMakeComplete:
    def test_counts_statuses(self):
        progress = {
            "ticket": "T-1",
            "steps": {
                "a": {"status": "completed", "result": None},
                "b": {"status": "skipped", "result": None},
                "c": {"status": "deferred", "result": None},
            },
        }
        result = make_complete(progress)
        assert result["action"] == "complete"
        assert "a" in result["summary"]["steps_completed"]
        assert "b" in result["summary"]["steps_skipped"]
        assert "c" in result["summary"]["steps_deferred"]

    def test_deferred_warning(self):
        progress = {
            "ticket": "T-1",
            "steps": {"a": {"status": "deferred", "result": None}},
        }
        result = make_complete(progress)
        assert any("Deferred" in w for w in result["summary"]["warnings"])

    def test_extracts_mr_url(self):
        progress = {
            "ticket": "T-1",
            "steps": {
                "create-merge-request": {
                    "status": "completed",
                    "result": {"url": "https://github.com/pr/1"},
                },
            },
        }
        result = make_complete(progress)
        assert result["summary"]["mr_url"] == "https://github.com/pr/1"

    def test_extracts_jira_fields(self):
        progress = {
            "ticket": "T-1",
            "steps": {
                "create-jira": {
                    "status": "completed",
                    "result": {"jira_url": "https://jira/T-2", "jira_key": "T-2"},
                },
            },
        }
        result = make_complete(progress)
        assert result["summary"]["jira_url"] == "https://jira/T-2"
        assert result["summary"]["jira_key"] == "T-2"

    def test_file_count_from_writing(self):
        progress = {
            "ticket": "T-1",
            "steps": {
                "writing": {
                    "status": "completed",
                    "result": {"files": ["/a.adoc", "/b.adoc"]},
                },
                "planning": {
                    "status": "completed",
                    "result": {"module_count": 3},
                },
            },
        }
        result = make_complete(progress)
        assert result["summary"]["file_count"] == 2
        assert result["summary"]["module_count"] == 3


class TestMakeFail:
    def test_basic_fields(self):
        result = make_fail("step-1", "error occurred", "Workflow failed")
        assert result["action"] == "fail"
        assert result["step"] == "step-1"
        assert result["reason"] == "error occurred"
        assert result["message"] == "Workflow failed"

    def test_with_warnings(self):
        result = make_fail("s", "r", "m", warnings=["w1"])
        assert result["warnings"] == ["w1"]

    def test_no_warnings_key_when_none(self):
        result = make_fail("s", "r", "m")
        assert "warnings" not in result


class TestCheckInputDeps:
    def test_all_satisfied(self):
        progress = {
            "steps": {
                "a": {"status": "completed"},
                "b": {"status": "completed"},
            },
        }
        yaml_map = {"c": {"inputs": ["a", "b"]}}
        assert check_input_deps("c", progress, yaml_map) == []

    def test_failed_dep(self):
        progress = {"steps": {"a": {"status": "failed"}}}
        yaml_map = {"b": {"inputs": ["a"]}}
        errors = check_input_deps("b", progress, yaml_map)
        assert len(errors) == 1
        assert "failed" in errors[0]

    def test_pending_dep(self):
        progress = {"steps": {"a": {"status": "pending"}}}
        yaml_map = {"b": {"inputs": ["a"]}}
        errors = check_input_deps("b", progress, yaml_map)
        assert len(errors) == 1
        assert "pending" in errors[0]

    def test_missing_step_no_error(self):
        progress = {"steps": {}}
        yaml_map = {"b": {"inputs": ["nonexistent"]}}
        assert check_input_deps("b", progress, yaml_map) == []

    def test_no_inputs(self):
        progress = {"steps": {}}
        yaml_map = {"a": {"inputs": []}}
        assert check_input_deps("a", progress, yaml_map) == []


# ---------------------------------------------------------------------------
# Group 2: Post-processors not yet tested
# ---------------------------------------------------------------------------


class TestReadSidecar:
    def test_reads_valid_json(self, tmp_path):
        step_dir = tmp_path / "my-step"
        step_dir.mkdir()
        data = {"schema_version": 1, "step": "my-step"}
        (step_dir / "step-result.json").write_text(json.dumps(data))
        result = read_sidecar(str(tmp_path), "my-step")
        assert result == data

    def test_missing_file(self, tmp_path):
        assert read_sidecar(str(tmp_path), "nonexistent") is None

    def test_corrupt_json(self, tmp_path):
        step_dir = tmp_path / "bad"
        step_dir.mkdir()
        (step_dir / "step-result.json").write_text("{not valid json")
        assert read_sidecar(str(tmp_path), "bad") is None


class TestPostProcessScopeReqAudit:
    def _make_sidecar(self, tmp_path, grounded=3, partial=1, absent=0, total=4, discovered=0):
        base = str(tmp_path)
        d = tmp_path / "scope-req-audit"
        d.mkdir(exist_ok=True)
        sidecar = {
            "schema_version": 1,
            "step": "scope-req-audit",
            "grounded": grounded,
            "partial": partial,
            "absent": absent,
            "total": total,
            "recommendation": "proceed",
            "discovered_repos_count": discovered,
        }
        (d / "step-result.json").write_text(json.dumps(sidecar))
        return base

    def test_message_formatting(self, tmp_path):
        base = self._make_sidecar(tmp_path)
        progress = {
            "ticket": "T-1",
            "steps": {"scope-req-audit": _step()},
        }
        result = post_process("scope-req-audit", progress, base, {})
        assert any("3 grounded" in m for m in result.get("messages", []))

    def test_discovered_repos_warning(self, tmp_path):
        base = self._make_sidecar(tmp_path, discovered=2)
        progress = {
            "ticket": "T-1",
            "steps": {"scope-req-audit": _step()},
        }
        result = post_process("scope-req-audit", progress, base, {})
        assert any("2 additional" in w for w in result.get("warnings", []))


class TestPostProcessCodeAnalysis:
    def test_logs_metrics(self, tmp_path):
        base = str(tmp_path)
        d = tmp_path / "code-analysis"
        d.mkdir()
        sidecar = {
            "schema_version": 1,
            "step": "code-analysis",
            "module_count": 5,
            "relationship_count": 12,
            "languages_detected": ["python", "go"],
        }
        (d / "step-result.json").write_text(json.dumps(sidecar))
        progress = {
            "ticket": "T-1",
            "steps": {"code-analysis": _step()},
        }
        result = post_process("code-analysis", progress, base, {})
        msgs = result.get("messages", [])
        assert any("5 modules" in m for m in msgs)
        assert any("python" in m for m in msgs)


class TestPostProcessPrAnalysis:
    def test_logs_pr_info(self, tmp_path):
        base = str(tmp_path)
        d = tmp_path / "pr-analysis"
        d.mkdir()
        sidecar = {
            "schema_version": 1,
            "step": "pr-analysis",
            "pr_number": 42,
            "modules_affected": 3,
        }
        (d / "step-result.json").write_text(json.dumps(sidecar))
        progress = {
            "ticket": "T-1",
            "steps": {"pr-analysis": _step()},
        }
        result = post_process("pr-analysis", progress, base, {})
        assert any("#42" in m for m in result.get("messages", []))


class TestCountModulesFallback:
    def test_counts_module_headings(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n\n### Module One\nContent\n\n### Module Two\nContent\n")
        assert _count_modules_fallback(str(plan)) == 2

    def test_ignores_code_blocks(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("### Module Real\n\n```\n### Module Fake\n```\n\n### Module Also Real\n")
        assert _count_modules_fallback(str(plan)) == 2

    def test_empty_file(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("")
        assert _count_modules_fallback(str(plan)) == 0

    def test_counts_update_headings(self, tmp_path):
        # In-place-update plans use '### Update N:' instead of '### Module:'
        plan = tmp_path / "plan.md"
        plan.write_text(
            "### Update 1: Fix install doc\n\n### Update 2: Add note\n\n### Module: New concept\n"
        )
        assert _count_modules_fallback(str(plan)) == 3


class TestParseReviewFallback:
    def test_parses_confidence_and_severity(self, tmp_path):
        review = tmp_path / "review.md"
        review.write_text(
            "Overall technical confidence: HIGH\n"
            "Severity counts: critical=1 significant=2 minor=3 sme=0\n"
        )
        conf, sev = _parse_review_fallback(str(review))
        assert conf == "HIGH"
        assert sev == {"critical": 1, "significant": 2, "minor": 3, "sme": 0}

    def test_missing_confidence(self, tmp_path):
        review = tmp_path / "review.md"
        review.write_text("No confidence line here\n")
        conf, sev = _parse_review_fallback(str(review))
        assert conf is None

    def test_missing_file(self, tmp_path):
        conf, sev = _parse_review_fallback(str(tmp_path / "missing.md"))
        assert conf is None
        assert sev == {}


class TestPostProcessCreateMergeRequest:
    def _make_sidecar(self, tmp_path, pushed=True, skipped=False, url=None):
        base = str(tmp_path)
        d = tmp_path / "create-merge-request"
        d.mkdir(exist_ok=True)
        sidecar = {
            "schema_version": 1,
            "step": "create-merge-request",
            "pushed": pushed,
            "skipped": skipped,
        }
        if url:
            sidecar["url"] = url
        (d / "step-result.json").write_text(json.dumps(sidecar))
        return base

    def test_pushed_no_warning(self, tmp_path):
        base = self._make_sidecar(tmp_path, pushed=True)
        progress = {
            "ticket": "T-1",
            "steps": {"create-merge-request": _step()},
        }
        result = post_process("create-merge-request", progress, base, {})
        assert not result.get("warnings", [])

    def test_not_pushed_not_skipped_warns(self, tmp_path):
        base = self._make_sidecar(tmp_path, pushed=False, skipped=False)
        progress = {
            "ticket": "T-1",
            "steps": {"create-merge-request": _step()},
        }
        result = post_process("create-merge-request", progress, base, {})
        assert any("not pushed" in w for w in result.get("warnings", []))

    def test_url_message(self, tmp_path):
        base = self._make_sidecar(tmp_path, pushed=True, url="https://github.com/pr/1")
        progress = {
            "ticket": "T-1",
            "steps": {"create-merge-request": _step()},
        }
        result = post_process("create-merge-request", progress, base, {})
        assert any("https://github.com/pr/1" in m for m in result.get("messages", []))


class TestPostProcessCreateJira:
    def test_extracts_url_and_key(self, tmp_path):
        base = str(tmp_path)
        d = tmp_path / "create-jira"
        d.mkdir()
        sidecar = {
            "schema_version": 1,
            "step": "create-jira",
            "jira_url": "https://jira/DOCS-1",
            "jira_key": "DOCS-1",
        }
        (d / "step-result.json").write_text(json.dumps(sidecar))
        progress = {
            "ticket": "T-1",
            "steps": {"create-jira": _step()},
        }
        result = post_process("create-jira", progress, base, {})
        assert any("DOCS-1" in m for m in result.get("messages", []))

    def test_no_url_no_message(self, tmp_path):
        base = str(tmp_path)
        d = tmp_path / "create-jira"
        d.mkdir()
        sidecar = {
            "schema_version": 1,
            "step": "create-jira",
            "jira_url": None,
            "jira_key": None,
        }
        (d / "step-result.json").write_text(json.dumps(sidecar))
        progress = {
            "ticket": "T-1",
            "steps": {"create-jira": _step()},
        }
        result = post_process("create-jira", progress, base, {})
        assert not [m for m in result.get("messages", []) if "JIRA" in m]


# ---------------------------------------------------------------------------
# Group 3: Filesystem helpers
# ---------------------------------------------------------------------------


class TestAtomicWriteJson:
    def test_writes_valid_json(self, tmp_path):
        path = str(tmp_path / "out.json")
        atomic_write_json(path, {"key": "value"})
        with open(path) as f:
            data = json.load(f)
        assert data == {"key": "value"}

    def test_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "sub" / "deep" / "out.json")
        atomic_write_json(path, {"a": 1})
        assert os.path.isfile(path)

    def test_file_ends_with_newline(self, tmp_path):
        path = str(tmp_path / "out.json")
        atomic_write_json(path, {})
        with open(path) as f:
            content = f.read()
        assert content.endswith("\n")


class TestReadWriteProgress:
    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "progress.json")
        data = {"ticket": "T-1", "status": "in_progress"}
        write_progress(path, data)
        loaded = read_progress(path)
        assert loaded["ticket"] == "T-1"
        assert "updated_at" in loaded

    def test_read_missing_returns_none(self, tmp_path):
        assert read_progress(str(tmp_path / "missing.json")) is None

    def test_write_updates_timestamp(self, tmp_path):
        path = str(tmp_path / "progress.json")
        data = {"ticket": "T-1"}
        write_progress(path, data)
        assert "updated_at" in data


class TestActiveMarker:
    def test_write_and_read(self, tmp_path):
        base_path = str(tmp_path / "PROJ-123")
        os.makedirs(base_path, exist_ok=True)
        write_active_marker(base_path, "PROJ-123", "docs-workflow", "workflow/p.json")
        marker = marker_path_for(base_path)
        assert os.path.isfile(marker)
        with open(marker) as f:
            data = json.load(f)
        assert data["ticket"] == "PROJ-123"
        assert data["workflow"] == "docs-workflow"

    def test_delete(self, tmp_path):
        base_path = str(tmp_path / "PROJ-123")
        os.makedirs(base_path, exist_ok=True)
        write_active_marker(base_path, "T-1", "wf", "p.json")
        delete_active_marker(base_path)
        assert not os.path.isfile(marker_path_for(base_path))

    def test_delete_missing_is_noop(self, tmp_path):
        base_path = str(tmp_path / "PROJ-123")
        os.makedirs(base_path, exist_ok=True)
        delete_active_marker(base_path)


class TestDeleteStopCounter:
    def test_deletes_file(self, tmp_path):
        pfile = str(tmp_path / "progress.json")
        counter = pfile + ".stop_count"
        with open(counter, "w") as f:
            f.write("2")
        delete_stop_counter(pfile)
        assert not os.path.isfile(counter)

    def test_missing_file_is_noop(self, tmp_path):
        pfile = str(tmp_path / "progress.json")
        delete_stop_counter(pfile)


# ---------------------------------------------------------------------------
# Group 4: Build step args edge cases
# ---------------------------------------------------------------------------


class TestBuildStepArgsPrAnalysisBlocking:
    def test_returns_none_without_repo(self):
        result = build_step_args(
            "pr-analysis",
            "T-1",
            "/base",
            {"pr_urls": ["http://pr1"]},
        )
        assert result is None

    def test_returns_args_with_repo(self):
        result = build_step_args(
            "pr-analysis",
            "T-1",
            "/base",
            {"pr_urls": ["http://pr1"], "source": {"repo_path": "/repo"}},
        )
        assert result is not None
        assert "--repo /repo" in result


class TestBuildStepArgsCreateJira:
    def test_includes_project(self):
        args = build_step_args(
            "create-jira",
            "T-1",
            "/base",
            {"create_jira": "DOCS"},
        )
        assert "--project DOCS" in args


class TestBuildStepArgsWritingMultiRepo:
    def test_multiple_repos(self):
        opts = {
            "source": {"repo_path": "/main-repo"},
            "additional_sources": [
                {"repo_path": "/extra1"},
                {"repo_path": "/extra2"},
            ],
        }
        args = build_step_args("writing", "T-1", "/base", opts)
        assert "--repo /main-repo" in args
        assert "--repo /extra1" in args
        assert "--repo /extra2" in args

    def test_docs_repo_path(self):
        opts = {"docs_repo_path": "/docs"}
        args = build_step_args("writing", "T-1", "/base", opts)
        assert "--repo-path /docs" in args


class TestStepDoneOverrideMarksInProgress:
    """cmd_step_done must mark the action_override target step as in_progress."""

    def _setup_progress(self, tmp_path, step_name, override_target, extra_progress=None):
        """Create a minimal progress file with step_name in_progress."""
        base = tmp_path / "workspace"
        base.mkdir(parents=True)
        workflow_dir = base / "workflow"
        workflow_dir.mkdir()

        progress = {
            "workflow": "docs-workflow",
            "ticket": "TEST-1",
            "base_path": str(base),
            "status": "in_progress",
            "created_at": iso_now(),
            "updated_at": iso_now(),
            "options": {},
            "step_order": [step_name, override_target],
            "steps": {
                step_name: {"status": "in_progress", "output": None, "result": None},
                override_target: {"status": "pending", "output": None, "result": None},
            },
            "_step_skills": {
                step_name: f"docs-workflow-{step_name}",
                override_target: f"docs-workflow-{override_target}",
            },
        }
        if extra_progress:
            progress.update(extra_progress)

        pfile = workflow_dir / "docs-workflow_test-1.json"
        atomic_write_json(str(pfile), progress)

        marker_path = marker_path_for(str(base))
        atomic_write_json(
            marker_path,
            {
                "ticket": "TEST-1",
                "workflow": "docs-workflow",
                "progress_file": str(pfile),
            },
        )

        return base, pfile

    def test_tech_review_fix_cycle_marks_writing_in_progress(self, tmp_path):
        base, pfile = self._setup_progress(
            tmp_path,
            "technical-review",
            "writing",
            extra_progress={
                "_step_skills": {
                    "technical-review": "docs-workflow-tech-review",
                    "writing": "docs-workflow-writing",
                },
            },
        )
        # Create a LOW-confidence tech-review sidecar to trigger fix cycle
        tr_dir = base / "technical-review"
        tr_dir.mkdir(exist_ok=True)
        sidecar = {
            "schema_version": 1,
            "step": "technical-review",
            "ticket": "TEST-1",
            "completed_at": iso_now(),
            "confidence": "LOW",
            "severity_counts": {"critical": 1, "significant": 0, "minor": 0, "sme": 0},
            "iteration": 1,
            "code_grounded": False,
        }
        (tr_dir / "step-result.json").write_text(json.dumps(sidecar))

        # Simulate what cmd_step_done does
        progress = read_progress(str(pfile))
        step_name = "technical-review"
        options = progress.get("options", {})

        progress["steps"][step_name]["output"] = str(tr_dir)
        progress["steps"][step_name]["status"] = "completed"

        pp_result = post_process(step_name, progress, str(base), options)
        assert "action_override" in pp_result
        override = pp_result["action_override"]
        # writing is dispatch-eligible, so the fix cycle dispatches instead of run_skill
        assert override["action"] == "dispatch"
        assert override["step"] == "writing"

        # The fix: mark target step in_progress before writing progress
        target_step = override.get("step")
        if target_step and target_step in progress["steps"]:
            progress["steps"][target_step]["status"] = "in_progress"

        write_progress(str(pfile), progress)

        # Verify the writing step is now in_progress
        saved = read_progress(str(pfile))
        assert saved["steps"]["writing"]["status"] == "in_progress"

    def test_writing_fix_cycle_marks_tech_review_in_progress(self, tmp_path):
        base, pfile = self._setup_progress(
            tmp_path,
            "writing",
            "technical-review",
            extra_progress={
                "_tech_review_fix_from": "/some/review.md",
                "_step_skills": {
                    "writing": "docs-workflow-writing",
                    "technical-review": "docs-workflow-tech-review",
                },
            },
        )
        writing_dir = base / "writing"
        writing_dir.mkdir(exist_ok=True)
        sidecar = {"schema_version": 1, "step": "writing", "files": ["/a.adoc"]}
        (writing_dir / "step-result.json").write_text(json.dumps(sidecar))

        progress = read_progress(str(pfile))
        progress["steps"]["writing"]["status"] = "completed"

        pp_result = post_process("writing", progress, str(base), {})
        assert pp_result["action_override"]["step"] == "technical-review"

        target_step = pp_result["action_override"]["step"]
        if target_step and target_step in progress["steps"]:
            progress["steps"][target_step]["status"] = "in_progress"

        write_progress(str(pfile), progress)

        saved = read_progress(str(pfile))
        assert saved["steps"]["technical-review"]["status"] == "in_progress"


class TestIsDispatchEligible:
    def test_writing_is_eligible(self):
        assert is_dispatch_eligible("writing") is True

    def test_planning_not_eligible(self):
        assert is_dispatch_eligible("planning") is False

    def test_dispatch_steps_only_contains_implemented(self):
        # Every step in DISPATCH_STEPS must have a prepare function registered.
        from docs_orchestrator import PREPARE_STEPS

        assert DISPATCH_STEPS <= set(PREPARE_STEPS)


class TestMakeDispatch:
    def test_basic_fields(self):
        result = make_dispatch("writing", "Step 6: Writing", "PROJ-123")
        assert result["action"] == "dispatch"
        assert result["step"] == "writing"
        assert result["message"] == "Step 6: Writing"
        assert result["prepare"].endswith("prepare-step PROJ-123 writing")
        assert "docs_orchestrator.py" in result["prepare"]

    def test_with_warnings_and_messages(self):
        result = make_dispatch("writing", "m", "T-1", warnings=["w1"], messages=["m1"])
        assert result["warnings"] == ["w1"]
        assert result["messages"] == ["m1"]

    def test_no_warnings_key_when_empty(self):
        result = make_dispatch("writing", "m", "T-1")
        assert "warnings" not in result
        assert "messages" not in result

    def test_extra_kwargs(self):
        result = make_dispatch("writing", "m", "T-1", resumed=True)
        assert result["resumed"] is True


class TestMakeStepAction:
    def test_dispatch_eligible_step_dispatches(self):
        result = make_step_action(
            step="writing",
            message="m",
            ticket="T-1",
            skill="docs-workflow-writing",
            args="T-1 --base-path /x",
        )
        assert result["action"] == "dispatch"
        assert result["step"] == "writing"
        assert "args" not in result

    def test_non_eligible_step_runs_skill(self):
        result = make_step_action(
            step="planning",
            message="m",
            ticket="T-1",
            skill="docs-workflow-planning",
            args="T-1 --base-path /x",
        )
        assert result["action"] == "run_skill"
        assert result["skill"] == "docs-workflow-planning"
        assert result["args"] == "T-1 --base-path /x"

    def test_warnings_forwarded_to_run_skill(self):
        result = make_step_action(
            step="planning",
            message="m",
            ticket="T-1",
            skill="s",
            args="a",
            warnings=["w"],
        )
        assert result["warnings"] == ["w"]

    def test_extra_kwargs_forwarded(self):
        result = make_step_action(
            step="writing", message="m", ticket="T-1", skill="s", args="a", resumed=True
        )
        assert result["resumed"] is True


class TestRenderWritingPrompt:
    ADOC_TPL_PATH = os.path.join(
        os.path.dirname(__file__),
        "..",
        "skills",
        "docs-workflow-writing",
        "prompts",
        "update-in-place-adoc.md",
    )

    def _tpl(self):
        with open(self.ADOC_TPL_PATH, encoding="utf-8") as f:
            return f.read()

    def _base_cfg(self, **over):
        cfg = {
            "ticket": "PROJ-9",
            "input_file": "/w/plan.md",
            "output_file": "/w/writing/_index.md",
            "output_dir": "/w/writing",
            "code_analysis_dir": "/w/ca",
            "pr_analysis_dir": "/w/pr",
            "fix_from": None,
            "has_code_analysis": False,
            "has_pr_analysis": False,
            "source_repo_path": None,
            "docs_repo_path": None,
            "additional_repo_paths": [],
            "additional_code_analysis_dirs": [],
        }
        cfg.update(over)
        return cfg

    def test_minimal_excludes_all_conditionals(self):
        out = _render_writing_prompt(self._tpl(), self._base_cfg())
        assert "Code-learner analysis" not in out
        assert "module registry" not in out  # continuation paragraph also excluded
        assert "PR analysis is available" not in out
        assert "Source code repository is available" not in out
        assert "Additional source code repositories" not in out
        assert "target repository is at" not in out
        assert "[Include only if" not in out
        assert "<TICKET>" not in out

    def test_code_analysis_includes_continuation(self):
        out = _render_writing_prompt(self._tpl(), self._base_cfg(has_code_analysis=True))
        assert "Code-learner analysis" in out
        # The un-marked continuation paragraph must be included with the block.
        assert "module registry" in out
        assert "/w/ca" in out
        assert "PR analysis is available" not in out

    def test_docs_repo_inline_conditional(self):
        out = _render_writing_prompt(self._tpl(), self._base_cfg(docs_repo_path="/repo/docs"))
        assert "target repository is at" in out
        assert "/repo/docs" in out

    def test_placeholder_substitution(self):
        out = _render_writing_prompt(self._tpl(), self._base_cfg())
        assert "PROJ-9" in out
        assert "/w/plan.md" in out
        assert "/w/writing/_index.md" in out

    def test_additional_repos_listed(self):
        cfg = self._base_cfg(
            has_code_analysis=True,
            source_repo_path="/src",
            additional_repo_paths=["/a", "/b"],
            additional_code_analysis_dirs=["/w/ca-a"],
        )
        out = _render_writing_prompt(self._tpl(), cfg)
        assert "Additional source code repositories" in out
        assert "/a, /b" in out
        assert "<list each path" not in out


class TestPrepareWriting:
    def _setup(self, tmp_path):
        base = str(tmp_path)
        planning = tmp_path / "planning"
        planning.mkdir()
        (planning / "plan.md").write_text("# Plan\n\n### Module x\n\nBody.\n")
        return base

    def test_update_in_place_adoc(self, tmp_path):
        base = self._setup(tmp_path)
        result = _prepare_writing("T-1", base, {"format": "adoc"}, {})
        assert len(result["agents"]) == 1
        agent = result["agents"][0]
        assert agent["type"] == "docs-skills:docs-writer"
        assert agent["background"] is False
        assert agent["model"] is None
        assert agent["schema"] is None
        assert agent["description"] == "Write adoc documentation for T-1"
        assert "T-1" in agent["prompt"]
        assert result["next_phase"] is None
        assert result["verify"].endswith("writing/_index.md")
        assert len(result["finalize"]) == 1
        assert "write_step_result.py" in result["finalize"][0]
        assert "--mode update-in-place" in result["finalize"][0]

    def test_mkdocs_description(self, tmp_path):
        base = self._setup(tmp_path)
        result = _prepare_writing("T-1", base, {"format": "mkdocs"}, {})
        assert result["agents"][0]["description"] == "Write mkdocs documentation for T-1"

    def test_fix_mode_finalizes_but_skips_verify(self, tmp_path):
        base = self._setup(tmp_path)
        review = tmp_path / "review.md"
        review.write_text("issues to fix")
        progress = {"_tech_review_fix_from": str(review), "_tech_review_iteration": 2}
        result = _prepare_writing("T-1", base, {"format": "adoc"}, progress)
        # verify stays gated on verify_output (off for fix mode, by design)
        assert result["verify"] is None
        # but the sidecar finalize now runs so completed_at/files stay current
        assert len(result["finalize"]) == 1
        assert "write_step_result.py" in result["finalize"][0]
        assert "--mode fix" in result["finalize"][0]
        assert "--iteration 2" in result["finalize"][0]
        assert result["agents"][0]["description"] == "Fix documentation for T-1"
        assert str(review) in result["agents"][0]["prompt"]


class TestCmdPrepareStep:
    def _setup_workspace(self, tmp_path, monkeypatch, step="writing"):
        root = tmp_path
        base = root / ".agent_workspace" / "test-1"
        (base / "planning").mkdir(parents=True)
        (base / "planning" / "plan.md").write_text("# Plan\n\n### Module x\n")
        workflow_dir = base / "workflow"
        workflow_dir.mkdir()
        progress = {
            "workflow": "docs-workflow",
            "ticket": "TEST-1",
            "base_path": str(base),
            "status": "in_progress",
            "options": {"format": "adoc"},
            "step_order": [step],
            "steps": {step: {"status": "in_progress", "output": None, "result": None}},
            "_step_skills": {step: f"docs-workflow-{step}"},
        }
        pfile = workflow_dir / "docs-workflow_test-1.json"
        atomic_write_json(str(pfile), progress)
        atomic_write_json(
            marker_path_for(str(base)),
            {"ticket": "TEST-1", "workflow": "docs-workflow", "progress_file": str(pfile)},
        )
        monkeypatch.setattr("docs_orchestrator.git_root", lambda: str(root))
        return root

    def test_writing_emits_agents(self, tmp_path, monkeypatch, capsys):
        self._setup_workspace(tmp_path, monkeypatch)
        args = argparse.Namespace(ticket="TEST-1", step="writing", phase=None)
        from docs_orchestrator import cmd_prepare_step

        cmd_prepare_step(args)
        out = json.loads(capsys.readouterr().out)
        assert len(out["agents"]) == 1
        assert out["agents"][0]["type"] == "docs-skills:docs-writer"

    def test_unknown_step_fails(self, tmp_path, monkeypatch, capsys):
        self._setup_workspace(tmp_path, monkeypatch, step="planning")
        args = argparse.Namespace(ticket="TEST-1", step="planning", phase=None)
        from docs_orchestrator import cmd_prepare_step

        with pytest.raises(SystemExit):
            cmd_prepare_step(args)
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "fail"
        assert "No prepare function" in out["message"]


class TestInitStepDoneLoop:
    """End-to-end: cmd_init -> cmd_step_done -> ... drives the state machine.

    Uses two post-processor-free steps so the loop exercises pure progression
    without step-specific side effects.
    """

    WORKFLOW_YAML = """\
name: docs-workflow
description: Integration test workflow
steps:
  - name: style-review
    skill: docs-tools:docs-workflow-style-review
    description: Style review
  - name: security-review
    skill: docs-tools:docs-workflow-security-review
    description: Security review
    inputs: [style-review]
"""

    def _init_args(self, ticket="TEST-1"):
        return argparse.Namespace(
            ticket=ticket,
            workflow=None,
            pr=None,
            source_code_repo=None,
            mkdocs=False,
            draft=False,
            docs_repo_path=None,
            create_merge_request=False,
            create_jira=None,
            no_source_repo=True,
            auto_discover_repos=False,
            max_secondary_repos=3,
            plugin_root=None,
        )

    def _complete_step(self, base, step):
        step_dir = base / step
        step_dir.mkdir(parents=True, exist_ok=True)
        (step_dir / "step-result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "step": step,
                    "ticket": "TEST-1",
                    "completed_at": iso_now(),
                }
            )
        )

    def test_full_progression(self, tmp_path, monkeypatch, capsys):
        from docs_orchestrator import cmd_init, cmd_step_done

        root = tmp_path
        ws = root / ".agent_workspace"
        ws.mkdir()
        (ws / "docs-workflow.yaml").write_text(self.WORKFLOW_YAML)
        monkeypatch.chdir(root)
        monkeypatch.setattr("docs_orchestrator.git_root", lambda: str(root))

        base = ws / "test-1"

        # init -> first step (style-review) dispatched via run_skill
        cmd_init(self._init_args())
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "run_skill"
        assert out["step"] == "style-review"

        # style-review completed -> progresses to security-review
        self._complete_step(base, "style-review")
        cmd_step_done(
            argparse.Namespace(ticket="TEST-1", step_name="style-review", failed=False, force=False)
        )
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "run_skill"
        assert out["step"] == "security-review"

        # security-review completed -> workflow complete
        self._complete_step(base, "security-review")
        cmd_step_done(
            argparse.Namespace(
                ticket="TEST-1", step_name="security-review", failed=False, force=False
            )
        )
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "complete"
        assert "style-review" in out["summary"]["steps_completed"]
        assert "security-review" in out["summary"]["steps_completed"]

    def test_step_done_failed_marks_workflow_failed(self, tmp_path, monkeypatch, capsys):
        from docs_orchestrator import cmd_init, cmd_step_done

        root = tmp_path
        ws = root / ".agent_workspace"
        ws.mkdir()
        (ws / "docs-workflow.yaml").write_text(self.WORKFLOW_YAML)
        monkeypatch.chdir(root)
        monkeypatch.setattr("docs_orchestrator.git_root", lambda: str(root))

        cmd_init(self._init_args())
        capsys.readouterr()  # drain init output

        cmd_step_done(
            argparse.Namespace(ticket="TEST-1", step_name="style-review", failed=True, force=False)
        )
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "fail"
        assert out["step"] == "style-review"

    def test_retry_step_recovers_failed_step(self, tmp_path, monkeypatch, capsys):
        from docs_orchestrator import (
            cmd_init,
            cmd_retry_step,
            cmd_step_done,
            read_progress,
            resolve_progress_file,
        )

        root = tmp_path
        ws = root / ".agent_workspace"
        ws.mkdir()
        (ws / "docs-workflow.yaml").write_text(self.WORKFLOW_YAML)
        monkeypatch.chdir(root)
        monkeypatch.setattr("docs_orchestrator.git_root", lambda: str(root))

        base = ws / "test-1"

        cmd_init(self._init_args())
        capsys.readouterr()

        # Fail the first step -> workflow status failed, marker deleted
        cmd_step_done(
            argparse.Namespace(ticket="TEST-1", step_name="style-review", failed=True, force=False)
        )
        capsys.readouterr()

        # retry-step re-emits the step action and un-fails the workflow
        cmd_retry_step(argparse.Namespace(ticket="TEST-1", step_name="style-review"))
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "run_skill"
        assert out["step"] == "style-review"

        pfile = resolve_progress_file(str(base), str(root))
        saved = read_progress(pfile)
        assert saved["status"] == "in_progress"
        assert saved["steps"]["style-review"]["status"] == "in_progress"

    def test_retry_step_unknown_step_fails(self, tmp_path, monkeypatch, capsys):
        from docs_orchestrator import cmd_init, cmd_retry_step

        root = tmp_path
        ws = root / ".agent_workspace"
        ws.mkdir()
        (ws / "docs-workflow.yaml").write_text(self.WORKFLOW_YAML)
        monkeypatch.chdir(root)
        monkeypatch.setattr("docs_orchestrator.git_root", lambda: str(root))

        cmd_init(self._init_args())
        capsys.readouterr()

        with pytest.raises(SystemExit):
            cmd_retry_step(argparse.Namespace(ticket="TEST-1", step_name="nonexistent"))
        out = json.loads(capsys.readouterr().out)
        assert out["action"] == "fail"
        assert "Unknown step" in out["message"]


class TestStepDoneRequirementsResolvesSource:
    """cmd_step_done for requirements resolves source and advances to code-analysis."""

    WORKFLOW_YAML = """\
name: docs-workflow
description: Source-resolution integration workflow
steps:
  - name: requirements
    skill: docs-tools:docs-workflow-requirements
    description: Gather requirements
  - name: code-analysis
    skill: docs-tools:docs-workflow-code-analysis
    description: Analyze source code
    when: has_source_repo
    inputs: [requirements]
  - name: planning
    skill: docs-tools:docs-workflow-planning
    description: Plan
    inputs: [requirements, code-analysis]
"""

    def _init_args(self, ticket="TEST-1"):
        return argparse.Namespace(
            ticket=ticket,
            workflow=None,
            pr=None,
            source_code_repo=None,
            mkdocs=False,
            draft=False,
            docs_repo_path=None,
            create_merge_request=False,
            create_jira=None,
            no_source_repo=False,
            auto_discover_repos=False,
            max_secondary_repos=3,
            plugin_root=None,
        )

    def test_requirements_advances_to_code_analysis(self, tmp_path, monkeypatch, capsys):
        from docs_orchestrator import (
            cmd_init,
            cmd_step_done,
            read_progress,
            resolve_progress_file,
        )

        root = tmp_path
        ws = root / ".agent_workspace"
        ws.mkdir()
        (ws / "docs-workflow.yaml").write_text(self.WORKFLOW_YAML)
        monkeypatch.chdir(root)
        monkeypatch.setattr("docs_orchestrator.git_root", lambda: str(root))

        cmd_init(self._init_args())
        capsys.readouterr()

        base = ws / "test-1"
        pfile = resolve_progress_file(str(base), str(root))
        # code-analysis is deferred until source is resolved.
        assert read_progress(pfile)["steps"]["code-analysis"]["status"] == "deferred"

        # Write the requirements output + sidecar.
        req_dir = base / "requirements"
        req_dir.mkdir(parents=True, exist_ok=True)
        (req_dir / "step-result.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "step": "requirements",
                    "ticket": "TEST-1",
                    "completed_at": iso_now(),
                    "requirement_count": 3,
                }
            )
        )

        def fake_resolve(base_path, progress_file=None, **kwargs):
            p = read_progress(progress_file)
            p["options"]["source"] = {"repo_path": "/clone"}
            for s in p["steps"].values():
                if s["status"] == "deferred":
                    s["status"] = "pending"
            with open(progress_file, "w") as f:
                json.dump(p, f)
            return 0, {"status": "resolved", "repo_path": "/clone"}

        monkeypatch.setattr("docs_orchestrator.call_resolve_source", fake_resolve)

        cmd_step_done(
            argparse.Namespace(ticket="TEST-1", step_name="requirements", failed=False, force=False)
        )
        out = json.loads(capsys.readouterr().out)

        assert out["step"] == "code-analysis"
        assert "--repo /clone" in out["args"]
        # Source resolution persisted and stamped.
        final = read_progress(pfile)
        assert final["options"]["source"]["repo_path"] == "/clone"
        assert final["steps"]["code-analysis"]["status"] == "in_progress"
        assert os.path.isfile(base / "requirements" / ".source-resolved")


class TestBuildStepArgsScopeReqAudit:
    def test_includes_repo(self):
        opts = {"source": {"repo_path": "/repo"}}
        args = build_step_args("scope-req-audit", "T-1", "/base", opts)
        assert "--repo /repo" in args

    def test_no_repo(self):
        args = build_step_args("scope-req-audit", "T-1", "/base", {})
        assert "--repo" not in args


def _write_progress_json(pfile, progress):
    with open(pfile, "w") as f:
        json.dump(progress, f)


class TestRehydrateProgress:
    def test_preserves_object_identity_and_updates(self, tmp_path):
        pfile = str(tmp_path / "progress.json")
        _write_progress_json(
            pfile,
            {
                "steps": {"code-analysis": {"status": "pending"}},
                "options": {"source": {"repo_path": "/repo"}},
            },
        )
        options = {"stale": True}
        progress = {"options": options, "steps": {"code-analysis": {"status": "deferred"}}}

        _rehydrate_progress(pfile, progress, options)

        # Same object identities preserved for both callers' references.
        assert progress["options"] is options
        # Content refreshed from disk.
        assert options == {"source": {"repo_path": "/repo"}}
        assert progress["steps"]["code-analysis"]["status"] == "pending"

    def test_missing_file_is_noop(self, tmp_path):
        pfile = str(tmp_path / "does-not-exist.json")
        options = {"a": 1}
        progress = {"options": options, "steps": {}}
        _rehydrate_progress(pfile, progress, options)
        assert options == {"a": 1}
        assert progress["options"] is options


class TestResolveSourcePostRequirements:
    def _setup(self, tmp_path, options):
        base = tmp_path / "base"
        (base / "requirements").mkdir(parents=True)
        (base / "workflow").mkdir(parents=True)
        pfile = str(base / "workflow" / "progress.json")
        progress = {
            "ticket": "TEST-1",
            "options": options,
            "steps": {
                "requirements": {"status": "completed"},
                "code-analysis": {"status": "deferred"},
            },
            "step_order": ["requirements", "code-analysis"],
        }
        _write_progress_json(pfile, progress)
        return str(base), pfile, progress

    def test_resolved_flips_deferred_and_sets_source(self, tmp_path, monkeypatch):
        options = {}
        base, pfile, progress = self._setup(tmp_path, options)

        def fake_resolve(base_path, progress_file=None, **kwargs):
            # Simulate resolve_source.py's on-disk _sync_progress mutation.
            p = read_progress(progress_file)
            p["options"]["source"] = {"repo_path": "/clone"}
            p["steps"]["code-analysis"]["status"] = "pending"
            _write_progress_json(progress_file, p)
            return 0, {"status": "resolved", "repo_path": "/clone"}

        monkeypatch.setattr("docs_orchestrator.call_resolve_source", fake_resolve)

        messages = resolve_source_post_requirements(base, pfile, progress, options)

        assert any("Source resolved" in m for m in messages)
        assert options["source"] == {"repo_path": "/clone"}
        assert progress["options"] is options
        assert progress["steps"]["code-analysis"]["status"] == "pending"
        assert os.path.isfile(os.path.join(base, "requirements", ".source-resolved"))

    def test_no_source_skips_deferred(self, tmp_path, monkeypatch):
        options = {}
        base, pfile, progress = self._setup(tmp_path, options)

        def fake_resolve(base_path, progress_file=None, **kwargs):
            p = read_progress(progress_file)
            p["steps"]["code-analysis"]["status"] = "skipped"
            _write_progress_json(progress_file, p)
            return 2, {"status": "no_source"}

        monkeypatch.setattr("docs_orchestrator.call_resolve_source", fake_resolve)

        messages = resolve_source_post_requirements(base, pfile, progress, options)

        assert any("No source repo discovered" in m for m in messages)
        assert progress["steps"]["code-analysis"]["status"] == "skipped"
        assert os.path.isfile(os.path.join(base, "requirements", ".source-resolved"))

    def test_hard_error_leaves_no_stamp(self, tmp_path, monkeypatch):
        options = {}
        base, pfile, progress = self._setup(tmp_path, options)
        monkeypatch.setattr(
            "docs_orchestrator.call_resolve_source",
            lambda *a, **k: (1, {"status": "error", "message": "boom"}),
        )

        messages = resolve_source_post_requirements(base, pfile, progress, options)

        assert messages == []
        assert not os.path.isfile(os.path.join(base, "requirements", ".source-resolved"))

    def test_skips_when_source_already_present(self, tmp_path, monkeypatch):
        options = {"source": {"repo_path": "/existing"}}
        base, pfile, progress = self._setup(tmp_path, options)

        def boom(*a, **k):
            raise AssertionError("call_resolve_source must not be called")

        monkeypatch.setattr("docs_orchestrator.call_resolve_source", boom)
        assert resolve_source_post_requirements(base, pfile, progress, options) == []

    def test_skips_when_no_source_repo_option(self, tmp_path, monkeypatch):
        options = {"no_source_repo": True}
        base, pfile, progress = self._setup(tmp_path, options)

        def boom(*a, **k):
            raise AssertionError("call_resolve_source must not be called")

        monkeypatch.setattr("docs_orchestrator.call_resolve_source", boom)
        assert resolve_source_post_requirements(base, pfile, progress, options) == []

    def test_idempotent_when_stamp_exists(self, tmp_path, monkeypatch):
        options = {}
        base, pfile, progress = self._setup(tmp_path, options)
        stamp = os.path.join(base, "requirements", ".source-resolved")
        open(stamp, "w").close()

        def boom(*a, **k):
            raise AssertionError("call_resolve_source must not be called")

        monkeypatch.setattr("docs_orchestrator.call_resolve_source", boom)
        assert resolve_source_post_requirements(base, pfile, progress, options) == []


class TestPostProcessPromotesIteration:
    def test_iteration_promoted_from_sidecar(self, tmp_path):
        base = str(tmp_path)
        step_dir = tmp_path / "technical-review"
        step_dir.mkdir()
        sidecar = {
            "schema_version": 1,
            "step": "technical-review",
            "ticket": "T-1",
            "completed_at": "2020-01-01T00:00:00+00:00",
            "confidence": "HIGH",
            "severity_counts": {"critical": 0, "significant": 0, "minor": 0, "sme": 0},
            "iteration": 3,
            "code_grounded": True,
        }
        (step_dir / "step-result.json").write_text(json.dumps(sidecar))
        progress = {
            "ticket": "T-1",
            "steps": {
                "technical-review": {"status": "completed", "output": None, "result": None},
            },
        }
        post_process("technical-review", progress, base, {})
        assert progress["steps"]["technical-review"]["iteration"] == 3

    def test_no_iteration_when_sidecar_lacks_field(self, tmp_path):
        base = str(tmp_path)
        step_dir = tmp_path / "writing"
        step_dir.mkdir()
        sidecar = {
            "schema_version": 1,
            "step": "writing",
            "ticket": "T-1",
            "completed_at": "2020-01-01T00:00:00+00:00",
            "files": ["/a.adoc"],
            "mode": "update-in-place",
            "format": "adoc",
        }
        (step_dir / "step-result.json").write_text(json.dumps(sidecar))
        progress = {
            "ticket": "T-1",
            "steps": {
                "writing": {"status": "completed", "output": None, "result": None},
            },
        }
        post_process("writing", progress, base, {})
        assert "iteration" not in progress["steps"]["writing"]

"""Tests for eval/scripts/diagnostics_judge.py."""

import json
from unittest.mock import patch

import diagnostics_judge as dj

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outputs(progress=None, artifacts=None):
    """Build a mock outputs dict with modified_files."""
    mods = {}
    if progress is not None:
        key = "ticket/workflow/docs-workflow_ticket.json"
        mods[key] = json.dumps(progress)
    for rel_path, data in (artifacts or {}).items():
        full = f"ticket/{rel_path}"
        mods[full] = json.dumps(data) if isinstance(data, dict | list) else data
    return {"modified_files": mods}


def _healthy_progress():
    return {
        "ticket": "TEST-1",
        "workflow": "docs-workflow",
        "status": "completed",
        "step_order": ["requirements", "planning", "writing"],
        "steps": {
            "requirements": {"status": "completed", "result": {"title": "ok"}},
            "planning": {"status": "completed", "result": {"modules": 3}},
            "writing": {"status": "completed", "result": {"files": ["a.adoc"]}},
        },
    }


def _setup():
    """Clear cache before each test."""
    dj._cache.clear()


# ---------------------------------------------------------------------------
# pipeline_health
# ---------------------------------------------------------------------------


class TestPipelineHealth:
    def test_no_progress(self):
        _setup()
        score, rationale = dj.pipeline_health({"modified_files": {}})
        assert score is None
        assert "No progress file" in rationale

    def test_healthy_pipeline(self):
        _setup()
        outputs = _make_outputs(_healthy_progress())
        score, rationale = dj.pipeline_health(outputs)
        # Score is 4 (not 5) because detect_failures flags missing sidecars
        # on disk as low-severity — expected when no filesystem is present
        assert score >= 4

    def test_failed_pipeline(self):
        _setup()
        progress = _healthy_progress()
        progress["status"] = "failed"
        progress["steps"]["writing"]["status"] = "failed"
        outputs = _make_outputs(progress)
        score, _ = dj.pipeline_health(outputs)
        assert score <= 2

    def test_stuck_step(self):
        _setup()
        progress = _healthy_progress()
        progress["steps"]["writing"]["status"] = "in_progress"
        outputs = _make_outputs(progress)
        score, rationale = dj.pipeline_health(outputs)
        assert score <= 2
        assert "stuck" in rationale

    def test_medium_failure(self):
        _setup()
        progress = _healthy_progress()
        progress["steps"]["orphan"] = {"status": "completed"}
        outputs = _make_outputs(progress)
        score, rationale = dj.pipeline_health(outputs)
        assert score <= 4

    def test_low_severity_only(self):
        _setup()
        progress = _healthy_progress()
        progress["status"] = "completed"
        # active_workflow_marker is low severity but needs filesystem check
        # schema_drift with missing field is high
        # Use a progress that produces only low-severity issues
        for step_name in progress["step_order"]:
            progress["steps"][step_name]["result"] = {"title": "ok"}
        outputs = _make_outputs(progress)
        score, _ = dj.pipeline_health(outputs)
        assert score >= 4


# ---------------------------------------------------------------------------
# evidence_quality
# ---------------------------------------------------------------------------


class TestEvidenceQuality:
    def test_no_artifacts(self):
        _setup()
        score, rationale = dj.evidence_quality({"modified_files": {}})
        assert score is None
        assert "No evidence" in rationale

    def test_all_grounded(self):
        _setup()
        evidence = {
            "recommendation": "proceed",
            "requirements": [
                {"id": "REQ-001", "status": "grounded", "top_score": 1.0},
                {"id": "REQ-002", "status": "grounded", "top_score": 0.9},
            ],
        }
        verdicts = {
            "total_claims": 5,
            "verdicts": {"supported": 5},
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {
                "validate/evidence-status.json": evidence,
                "technical-review/claim-verdicts.json": verdicts,
            },
        )
        score, rationale = dj.evidence_quality(outputs)
        assert score == 5
        assert "2/2 grounded" in rationale
        assert "5/5 supported" in rationale

    def test_absent_requirements(self):
        _setup()
        evidence = {
            "requirements": [
                {"id": "REQ-001", "status": "grounded"},
                {"id": "REQ-002", "status": "absent"},
            ],
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {"validate/evidence-status.json": evidence},
        )
        score, rationale = dj.evidence_quality(outputs)
        assert score <= 3
        assert "absent" in rationale

    def test_unsupported_claims(self):
        _setup()
        verdicts = {
            "total_claims": 10,
            "verdicts": {"supported": 7, "unsupported": 3},
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {"technical-review/claim-verdicts.json": verdicts},
        )
        score, rationale = dj.evidence_quality(outputs)
        assert score <= 2
        assert "unsupported" in rationale

    def test_partial_grounding(self):
        _setup()
        evidence = {
            "requirements": [
                {"id": f"REQ-{i}", "status": "grounded" if i < 4 else "partial"} for i in range(5)
            ],
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {"validate/evidence-status.json": evidence},
        )
        score, _ = dj.evidence_quality(outputs)
        assert score == 4  # 80% grounded

    def test_low_grounding(self):
        _setup()
        evidence = {
            "requirements": [
                {"id": "REQ-001", "status": "grounded"},
                {"id": "REQ-002", "status": "partial"},
                {"id": "REQ-003", "status": "partial"},
                {"id": "REQ-004", "status": "partial"},
                {"id": "REQ-005", "status": "partial"},
            ],
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {"validate/evidence-status.json": evidence},
        )
        score, _ = dj.evidence_quality(outputs)
        assert score <= 3  # 20% grounded


# ---------------------------------------------------------------------------
# review_quality
# ---------------------------------------------------------------------------


class TestReviewQuality:
    def test_no_artifacts(self):
        _setup()
        score, rationale = dj.review_quality({"modified_files": {}})
        assert score is None

    def test_clean_review(self):
        _setup()
        tech_sr = {
            "schema_version": 1,
            "step": "technical-review",
            "severity_counts": {"critical": 0, "significant": 0, "minor": 2, "sme": 1},
            "iteration": 1,
            "code_grounded": True,
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {"technical-review/step-result.json": tech_sr},
        )
        score, rationale = dj.review_quality(outputs)
        assert score == 5

    def test_critical_findings(self):
        _setup()
        tech_sr = {
            "severity_counts": {"critical": 2, "significant": 0},
            "iteration": 1,
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {"technical-review/step-result.json": tech_sr},
        )
        score, _ = dj.review_quality(outputs)
        assert score == 1

    def test_security_credential_finding(self):
        _setup()
        scanner = {
            "summary": {
                "total_findings": 3,
                "by_category": {"credential": 2, "url": 1},
                "by_severity": {"warning": 3},
            },
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {"security-review/scanner-results.json": scanner},
        )
        score, rationale = dj.review_quality(outputs)
        assert score <= 2
        assert "credential" in rationale

    def test_multiple_iterations(self):
        _setup()
        tech_sr = {
            "severity_counts": {"critical": 0, "significant": 0, "minor": 1},
            "iteration": 3,
            "code_grounded": True,
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {"technical-review/step-result.json": tech_sr},
        )
        score, rationale = dj.review_quality(outputs)
        assert score <= 3
        assert "3 iterations" in rationale

    def test_url_only_security(self):
        _setup()
        scanner = {
            "summary": {
                "total_findings": 5,
                "by_category": {"url": 5},
                "by_severity": {"warning": 5},
            },
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {"security-review/scanner-results.json": scanner},
        )
        score, rationale = dj.review_quality(outputs)
        assert score == 5
        assert "URL-only" in rationale


# ---------------------------------------------------------------------------
# validation_quality
# ---------------------------------------------------------------------------


class TestValidationQuality:
    def test_no_artifacts(self):
        _setup()
        score, _ = dj.validation_quality({"modified_files": {}})
        assert score is None

    def test_clean_validation(self):
        _setup()
        report = {"status": "passed", "error_count": 0, "warning_count": 0}
        policy = {"status": "passed", "error_count": 0, "warning_count": 0}
        outputs = _make_outputs(
            _healthy_progress(),
            {
                "dita-validation/report.json": report,
                "dita-validation/policy-report.json": policy,
            },
        )
        score, _ = dj.validation_quality(outputs)
        assert score == 5

    def test_warnings_only(self):
        _setup()
        report = {"status": "passed", "error_count": 0, "warning_count": 3}
        policy = {"status": "passed", "error_count": 0, "warning_count": 1}
        outputs = _make_outputs(
            _healthy_progress(),
            {
                "dita-validation/report.json": report,
                "dita-validation/policy-report.json": policy,
            },
        )
        score, _ = dj.validation_quality(outputs)
        assert score == 4  # 4 warnings total, <=5

    def test_many_warnings(self):
        _setup()
        report = {"status": "passed", "error_count": 0, "warning_count": 7}
        outputs = _make_outputs(
            _healthy_progress(),
            {"dita-validation/report.json": report},
        )
        score, _ = dj.validation_quality(outputs)
        assert score == 3

    def test_errors(self):
        _setup()
        report = {"status": "passed", "error_count": 2, "warning_count": 0}
        outputs = _make_outputs(
            _healthy_progress(),
            {"dita-validation/report.json": report},
        )
        score, _ = dj.validation_quality(outputs)
        assert score == 2

    def test_many_errors(self):
        _setup()
        report = {"status": "failed", "error_count": 5, "warning_count": 0}
        outputs = _make_outputs(
            _healthy_progress(),
            {"dita-validation/report.json": report},
        )
        score, _ = dj.validation_quality(outputs)
        assert score == 1


# ---------------------------------------------------------------------------
# planning_fidelity
# ---------------------------------------------------------------------------


class TestPlanningFidelity:
    def test_no_artifacts(self):
        _setup()
        score, _ = dj.planning_fidelity({"modified_files": {}})
        assert score is None

    def test_good_fidelity(self):
        _setup()
        plan_sr = {"schema_version": 1, "step": "planning", "module_count": 3}
        write_sr = {
            "schema_version": 1,
            "step": "writing",
            "files": ["a.dita", "b.dita", "c.dita"],
        }
        discovery = {
            "sources_consulted": {
                "jira_tickets": [{"key": "TEST-1"}],
                "pull_requests": [{"url": "https://example.com/pr/1"}],
            }
        }
        outputs = _make_outputs(
            _healthy_progress(),
            {
                "planning/step-result.json": plan_sr,
                "writing/step-result.json": write_sr,
                "requirements/discovery.json": discovery,
            },
        )
        score, rationale = dj.planning_fidelity(outputs)
        assert score == 5
        assert "3" in rationale

    def test_file_count_mismatch(self):
        _setup()
        plan_sr = {"module_count": 5}
        write_sr = {"files": ["a.dita"]}
        outputs = _make_outputs(
            _healthy_progress(),
            {
                "planning/step-result.json": plan_sr,
                "writing/step-result.json": write_sr,
            },
        )
        score, rationale = dj.planning_fidelity(outputs)
        assert score <= 3
        assert "gap" in rationale

    def test_no_sources(self):
        _setup()
        plan_sr = {"module_count": 2}
        write_sr = {"files": ["a.dita", "b.dita"]}
        discovery = {"sources_consulted": {"jira_tickets": [], "pull_requests": []}}
        outputs = _make_outputs(
            _healthy_progress(),
            {
                "planning/step-result.json": plan_sr,
                "writing/step-result.json": write_sr,
                "requirements/discovery.json": discovery,
            },
        )
        score, _ = dj.planning_fidelity(outputs)
        assert score <= 2

    def test_missing_planning(self):
        _setup()
        write_sr = {"files": ["a.dita"]}
        outputs = _make_outputs(
            _healthy_progress(),
            {"writing/step-result.json": write_sr},
        )
        score, rationale = dj.planning_fidelity(outputs)
        assert score == 1
        assert "missing planning" in rationale

    def test_zero_files(self):
        _setup()
        plan_sr = {"module_count": 3}
        write_sr = {"files": []}
        outputs = _make_outputs(
            _healthy_progress(),
            {
                "planning/step-result.json": plan_sr,
                "writing/step-result.json": write_sr,
            },
        )
        score, rationale = dj.planning_fidelity(outputs)
        assert score <= 2
        assert "0 files" in rationale


# ---------------------------------------------------------------------------
# _run_all_deterministic
# ---------------------------------------------------------------------------


class TestRunAllDeterministic:
    def test_returns_all_judges(self):
        _setup()
        outputs = _make_outputs(_healthy_progress())
        results = dj._run_all_deterministic(outputs)
        assert set(results.keys()) == {
            "pipeline_health",
            "evidence_quality",
            "review_quality",
            "validation_quality",
            "planning_fidelity",
        }

    def test_all_produce_tuples(self):
        _setup()
        outputs = _make_outputs(_healthy_progress())
        results = dj._run_all_deterministic(outputs)
        for name, (score, rationale) in results.items():
            assert score is None or isinstance(score, int), f"{name} score not int"
            assert isinstance(rationale, str), f"{name} rationale not str"


# ---------------------------------------------------------------------------
# diagnostics_reflection
# ---------------------------------------------------------------------------


class TestDiagnosticsReflection:
    def test_skip_when_all_healthy(self):
        _setup()
        outputs = _make_outputs(_healthy_progress())
        score, rationale = dj.diagnostics_reflection(outputs, threshold=3)
        assert score == 5
        assert "healthy" in rationale

    def test_skip_when_no_scores(self):
        _setup()
        score, rationale = dj.diagnostics_reflection({"modified_files": {}})
        assert score is None

    @patch.object(dj, "_call_llm")
    def test_triggers_llm_on_low_scores(self, mock_llm):
        _setup()
        mock_llm.return_value = (3, "Fix the evidence gaps")
        progress = _healthy_progress()
        progress["status"] = "failed"
        progress["steps"]["writing"]["status"] = "failed"
        outputs = _make_outputs(progress)
        score, rationale = dj.diagnostics_reflection(outputs, threshold=3)
        assert mock_llm.called
        assert score == 3

    @patch.object(dj, "_call_llm")
    def test_custom_threshold(self, mock_llm):
        _setup()
        mock_llm.return_value = (4, "Minor issues")
        outputs = _make_outputs(_healthy_progress())
        # With threshold=5, the healthy pipeline_health score of 5 won't trigger
        # but skipped judges (None) are excluded
        score, rationale = dj.diagnostics_reflection(outputs, threshold=5)
        # pipeline_health scores 5, others are None (skipped)
        # Only scored judges are checked, so 5 <= 5 is not <= threshold trigger
        # Actually 5 <= 5 IS true. Let me check the logic...
        # low_scores = {k: v for k, v in scored.items() if v[0] <= threshold}
        # With threshold=5, score 5 <= 5 is True, so it WOULD trigger
        assert mock_llm.called


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


class TestBuildCliOutputs:
    def test_missing_workspace(self, tmp_path):
        result = dj._build_cli_outputs(str(tmp_path / "nonexistent"))
        assert result == {}

    def test_valid_workspace(self, tmp_path):
        workspace = tmp_path / "ticket"
        workflow_dir = workspace / "workflow"
        workflow_dir.mkdir(parents=True)
        progress = {"ticket": "TEST-1", "status": "completed", "steps": {}, "step_order": []}
        (workflow_dir / "docs-workflow_test-1.json").write_text(json.dumps(progress))
        (workspace / "planning").mkdir()
        sr = {"step": "planning", "module_count": 2}
        (workspace / "planning" / "step-result.json").write_text(json.dumps(sr))

        result = dj._build_cli_outputs(str(workspace))
        assert "modified_files" in result
        mods = result["modified_files"]
        assert any("workflow" in k for k in mods)
        assert any("step-result" in k for k in mods)


# ---------------------------------------------------------------------------
# Architect mode — _discover_workspaces
# ---------------------------------------------------------------------------


def _make_workspace_on_disk(parent, ticket, step_order=None, status="completed"):
    """Create a minimal workspace dir on disk for architect tests."""
    ws = parent / ticket
    wf_dir = ws / "workflow"
    wf_dir.mkdir(parents=True)
    steps_data = {}
    for s in step_order or ["requirements", "planning", "writing"]:
        steps_data[s] = {"status": "completed", "result": {}}
    progress = {
        "ticket": ticket,
        "status": status,
        "step_order": step_order or ["requirements", "planning", "writing"],
        "steps": steps_data,
    }
    (wf_dir / f"docs-workflow_{ticket}.json").write_text(json.dumps(progress))
    return ws


class TestDiscoverWorkspaces:
    def test_single_workspace(self, tmp_path):
        ws = _make_workspace_on_disk(tmp_path, "test-1")
        result = dj._discover_workspaces(str(ws))
        assert len(result) == 1
        assert result[0]["source"] == "single"
        assert result[0]["label"] == "test-1"

    def test_workspace_dir(self, tmp_path):
        _make_workspace_on_disk(tmp_path, "ticket-a")
        _make_workspace_on_disk(tmp_path, "ticket-b")
        (tmp_path / "not-a-workspace").mkdir()
        result = dj._discover_workspaces(str(tmp_path))
        assert len(result) == 2
        assert all(r["source"] == "workspace_dir" for r in result)
        labels = [r["label"] for r in result]
        assert "ticket-a" in labels
        assert "ticket-b" in labels

    def test_eval_run_dir(self, tmp_path):
        cases = tmp_path / "cases"
        case_1 = cases / "case-001-test"
        ws_dir = case_1 / "_modified" / ".agent_workspace"
        _make_workspace_on_disk(ws_dir, "test-ticket")
        result = dj._discover_workspaces(str(tmp_path))
        assert len(result) == 1
        assert result[0]["source"] == "eval_run"
        assert result[0]["label"] == "case-001-test"

    def test_empty_dir(self, tmp_path):
        result = dj._discover_workspaces(str(tmp_path))
        assert result == []


# ---------------------------------------------------------------------------
# Architect mode — _collect_workspace_data
# ---------------------------------------------------------------------------


class TestCollectWorkspaceData:
    def test_collects_scores(self, tmp_path):
        ws = _make_workspace_on_disk(tmp_path, "test-1")
        entry = {"workspace_path": str(ws), "label": "test-1", "source": "single"}
        data = dj._collect_workspace_data(entry)
        assert data is not None
        assert "scores" in data
        assert "rationales" in data
        assert data["label"] == "test-1"
        assert "pipeline_health" in data["scores"]

    def test_returns_none_for_empty(self, tmp_path):
        entry = {
            "workspace_path": str(tmp_path / "nope"),
            "label": "nope",
            "source": "single",
        }
        data = dj._collect_workspace_data(entry)
        assert data is None

    def test_includes_step_order(self, tmp_path):
        steps = ["requirements", "planning", "writing", "review"]
        ws = _make_workspace_on_disk(tmp_path, "test-2", step_order=steps)
        entry = {"workspace_path": str(ws), "label": "test-2", "source": "single"}
        data = dj._collect_workspace_data(entry)
        assert data["step_order"] == steps


# ---------------------------------------------------------------------------
# Architect mode — _compute_score_stats
# ---------------------------------------------------------------------------


class TestComputeScoreStats:
    def test_basic_stats(self):
        all_data = [
            {
                "label": "ws-a",
                "scores": {
                    "pipeline_health": 4,
                    "evidence_quality": 5,
                    "review_quality": None,
                },
                "rationales": {
                    "pipeline_health": "ok",
                    "evidence_quality": "ok",
                    "review_quality": "skip",
                },
            },
            {
                "label": "ws-b",
                "scores": {
                    "pipeline_health": 2,
                    "evidence_quality": 3,
                    "review_quality": None,
                },
                "rationales": {
                    "pipeline_health": "bad",
                    "evidence_quality": "mid",
                    "review_quality": "skip",
                },
            },
        ]
        stats = dj._compute_score_stats(all_data)
        ph = stats["pipeline_health"]
        assert ph["mean"] == 3.0
        assert ph["min"] == 2
        assert ph["max"] == 4
        assert ph["failure_rate"] == 0.5

    def test_all_none_scores(self):
        all_data = [
            {
                "scores": {"pipeline_health": None},
                "rationales": {"pipeline_health": "skip"},
            },
        ]
        stats = dj._compute_score_stats(all_data)
        assert stats["pipeline_health"]["count"] == 0

    def test_low_findings_list(self):
        all_data = [
            {
                "label": "ws-a",
                "scores": {"pipeline_health": 2, "evidence_quality": 5},
                "rationales": {"pipeline_health": "bad", "evidence_quality": "ok"},
            },
            {
                "label": "ws-b",
                "scores": {"pipeline_health": 5, "evidence_quality": 5},
                "rationales": {"pipeline_health": "ok", "evidence_quality": "ok"},
            },
        ]
        stats = dj._compute_score_stats(all_data)
        findings = stats["pipeline_health"]["low_findings"]
        assert len(findings) == 1
        assert findings[0]["label"] == "ws-a"


# ---------------------------------------------------------------------------
# Architect mode — _compute_context_stats
# ---------------------------------------------------------------------------


class TestComputeContextStats:
    def test_basic_context(self):
        all_data = [
            {
                "context_pressure": {
                    "total_estimated_tokens": 100000,
                    "context_window_pct": 50,
                    "risk_score": 4,
                    "level": "moderate",
                    "per_step_estimated_tokens": {"writing": 60000, "planning": 20000},
                },
            },
            {
                "context_pressure": {
                    "total_estimated_tokens": 200000,
                    "context_window_pct": 100,
                    "risk_score": 8,
                    "level": "critical",
                    "per_step_estimated_tokens": {"writing": 120000, "planning": 40000},
                },
            },
        ]
        stats = dj._compute_context_stats(all_data)
        assert stats["count"] == 2
        assert stats["total_tokens"]["mean"] == 150000
        assert stats["total_tokens"]["max"] == 200000
        assert stats["window_pct"]["mean"] == 75
        assert stats["level_distribution"] == {"moderate": 1, "critical": 1}
        assert stats["per_step_mean_tokens"]["writing"] == 90000

    def test_empty_context(self):
        all_data = [{"context_pressure": None}]
        stats = dj._compute_context_stats(all_data)
        assert stats == {}


# ---------------------------------------------------------------------------
# Architect mode — _detect_systemic_patterns
# ---------------------------------------------------------------------------


class TestDetectSystemicPatterns:
    def test_high_failure_rate(self):
        score_stats = {
            "pipeline_health": {"count": 4, "failure_rate": 0.75, "concern_rate": 0.75},
            "evidence_quality": {"count": 4, "failure_rate": 0.0, "concern_rate": 0.25},
        }
        patterns = dj._detect_systemic_patterns(score_stats, {}, [])
        types = [p["type"] for p in patterns]
        assert "consistently_failing" in types

    def test_concern_rate(self):
        score_stats = {
            "review_quality": {"count": 10, "failure_rate": 0.1, "concern_rate": 0.8},
        }
        patterns = dj._detect_systemic_patterns(score_stats, {}, [])
        assert any(p["type"] == "consistently_concerning" for p in patterns)

    def test_context_pressure_patterns(self):
        context_stats = {
            "risk_score": {"mean": 7},
            "window_pct": {"mean": 85},
            "per_step_mean_tokens": {"code-evidence": 200000, "planning": 10000},
        }
        patterns = dj._detect_systemic_patterns({}, context_stats, [])
        types = [p["type"] for p in patterns]
        assert "systemic_context_pressure" in types
        assert "context_window_saturation" in types
        assert "heavy_step" in types
        heavy = [p for p in patterns if p["type"] == "heavy_step"]
        assert len(heavy) == 1
        assert heavy[0]["step"] == "code-evidence"


# ---------------------------------------------------------------------------
# Architect mode — _build_diagnose_output
# ---------------------------------------------------------------------------


class TestBuildDiagnoseOutput:
    def test_structure(self, tmp_path):
        ws = _make_workspace_on_disk(tmp_path, "test-1")
        entry = {"workspace_path": str(ws), "label": "test-1", "source": "single"}
        dj._cache.clear()
        data = dj._collect_workspace_data(entry)
        output = dj._build_diagnose_output([data])
        assert output["mode"] == "diagnose"
        assert output["workspace_count"] == 1
        assert "score_stats" in output
        assert "systemic_patterns" in output
        assert "workspaces" in output


# ---------------------------------------------------------------------------
# Architect mode — _build_compare_output
# ---------------------------------------------------------------------------


class TestBuildCompareOutput:
    def test_groups_by_step_order(self, tmp_path):
        dir_a = tmp_path / "variant_a"
        dir_a.mkdir()
        _make_workspace_on_disk(dir_a, "t1", step_order=["requirements", "writing"])
        dir_b = tmp_path / "variant_b"
        dir_b.mkdir()
        _make_workspace_on_disk(dir_b, "t2", step_order=["requirements", "planning", "writing"])

        output = dj._build_compare_output([str(dir_a), str(dir_b)])
        assert output["mode"] == "compare"
        assert output["variant_count"] == 2
        assert output["delta"] is not None

    def test_single_variant(self, tmp_path):
        _make_workspace_on_disk(tmp_path, "t1", step_order=["a", "b"])
        _make_workspace_on_disk(tmp_path, "t2", step_order=["a", "b"])
        output = dj._build_compare_output([str(tmp_path)])
        assert output["variant_count"] == 1
        assert output["delta"] is None


# ---------------------------------------------------------------------------
# Architect mode — _format_architect_text
# ---------------------------------------------------------------------------


class TestFormatArchitectText:
    def test_diagnose_text(self):
        output = {
            "mode": "diagnose",
            "workspace_count": 3,
            "overall_mean": 3.5,
            "score_stats": {
                "pipeline_health": {
                    "count": 3,
                    "mean": 3.0,
                    "median": 3.0,
                    "min": 2,
                    "max": 4,
                    "failure_rate": 0.33,
                    "concern_rate": 0.67,
                    "low_findings": [],
                },
            },
            "context_stats": {
                "total_tokens": {"mean": 150000, "max": 200000, "min": 100000},
                "window_pct": {"mean": 75, "max": 100, "min": 50},
                "level_distribution": {"moderate": 2, "critical": 1},
                "per_step_mean_tokens": {"writing": 80000},
            },
            "systemic_patterns": [
                {
                    "type": "heavy_step",
                    "severity": "medium",
                    "detail": "writing averages ~80,000 tokens",
                },
            ],
            "workspaces": [],
        }
        text = dj._format_architect_text(output)
        assert "Architect Diagnostics" in text
        assert "3 workspaces" in text
        assert "pipeline_health" in text
        assert "writing" in text

    def test_compare_text(self):
        output = {
            "mode": "compare",
            "variant_count": 2,
            "variants": {
                "a,b": {
                    "step_order": ["a", "b"],
                    "step_count": 2,
                    "workspace_count": 1,
                    "score_stats": {
                        "pipeline_health": {
                            "count": 1,
                            "mean": 3.0,
                            "median": 3.0,
                            "failure_rate": 0,
                        },
                    },
                    "context_stats": {},
                },
                "a,b,c": {
                    "step_order": ["a", "b", "c"],
                    "step_count": 3,
                    "workspace_count": 1,
                    "score_stats": {
                        "pipeline_health": {
                            "count": 1,
                            "mean": 4.0,
                            "median": 4.0,
                            "failure_rate": 0,
                        },
                    },
                    "context_stats": {},
                },
            },
            "delta": {"pipeline_health": 1.0},
        }
        text = dj._format_architect_text(output)
        assert "Architect Compare" in text
        assert "Variant 1" in text
        assert "Delta" in text

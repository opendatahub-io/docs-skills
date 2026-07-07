"""Tests for pipeline_diagnostics.py.

Fixture-based deterministic tests following the autofix dry-run pattern:
build synthetic .agent_workspace/ trees with crafted progress JSON and
step-result sidecars, then assert that the analysis functions produce
the expected diagnostics.
"""

import json
import os
from datetime import datetime, timezone

from pipeline_diagnostics import (
    analyze,
    build_recommendations,
    build_sidecar,
    derive_base_path,
    derive_pipeline_status,
    detect_bottlenecks,
    detect_failures,
    detect_loop_groups,
    estimate_context_pressure,
    find_progress_files,
    orchestrator_health,
    parse_iso,
    resolve_output_path,
    scan_dir,
)

# ── Fixture helpers ──────────────────────────────────────────────────────────


STEP_ORDER = [
    "requirements",
    "code-analysis",
    "scope-req-audit",
    "pr-analysis",
    "planning",
    "writing",
    "technical-review",
    "style-review",
    "security-review",
    "quality-gate",
    "resolve-feedback",
    "create-merge-request",
]


def _make_progress(
    tmp_path,
    ticket="TEST-123",
    steps=None,
    step_order=None,
    status="completed",
    workflow="docs-workflow",
):
    """Build a synthetic .agent_workspace/<ticket>/ tree with a progress file."""
    base = tmp_path / ticket.lower()
    workflow_dir = base / "workflow"
    workflow_dir.mkdir(parents=True)

    if step_order is None:
        step_order = STEP_ORDER

    if steps is None:
        steps = {}

    progress = {
        "ticket": ticket,
        "base_path": str(base),
        "step_order": step_order,
        "steps": steps,
        "status": status,
        "workflow": workflow,
        "created_at": "2026-06-01T10:00:00Z",
        "updated_at": "2026-06-01T12:00:00Z",
    }

    progress_path = workflow_dir / f"{workflow}_{ticket.lower()}.json"
    progress_path.write_text(json.dumps(progress, indent=2))
    return str(progress_path), str(base)


def _make_step_dir(base_path, step_name, sidecar=None, files=None):
    """Create a step output directory with optional sidecar and files."""
    step_dir = os.path.join(base_path, step_name)
    os.makedirs(step_dir, exist_ok=True)

    if sidecar is not None:
        sidecar_path = os.path.join(step_dir, "step-result.json")
        with open(sidecar_path, "w") as f:
            json.dump(sidecar, f)

    if files:
        for name, content in files.items():
            fpath = os.path.join(step_dir, name)
            os.makedirs(os.path.dirname(fpath), exist_ok=True) if "/" in name else None
            with open(fpath, "w") as f:
                f.write(content)

    return step_dir


def _completed_step(output=None, result=None):
    """Shorthand for a completed step dict."""
    s = {"status": "completed"}
    if output:
        s["output"] = output
    if result:
        s["result"] = result
    return s


# ── parse_iso ────────────────────────────────────────────────────────────────


class TestParseIso:
    def test_none(self):
        assert parse_iso(None) is None

    def test_empty(self):
        assert parse_iso("") is None

    def test_basic_format(self):
        dt = parse_iso("2026-06-01T10:30:00")
        assert dt == datetime(2026, 6, 1, 10, 30, 0, tzinfo=timezone.utc)

    def test_with_microseconds(self):
        dt = parse_iso("2026-06-01T10:30:00.123456")
        assert dt.microsecond == 123456

    def test_z_suffix_stripped(self):
        dt = parse_iso("2026-06-01T10:30:00Z")
        assert dt == datetime(2026, 6, 1, 10, 30, 0, tzinfo=timezone.utc)

    def test_utc_offset_stripped(self):
        dt = parse_iso("2026-06-01T10:30:00+00:00")
        assert dt == datetime(2026, 6, 1, 10, 30, 0, tzinfo=timezone.utc)

    def test_unparseable_returns_none(self):
        assert parse_iso("not-a-date") is None


# ── scan_dir / DirStats ──────────────────────────────────────────────────────


class TestScanDir:
    def test_empty_dir(self, tmp_path):
        stats = scan_dir(str(tmp_path))
        assert stats.size_kb == 0
        assert stats.file_count == 0
        assert stats.earliest_mtime is None

    def test_missing_dir(self, tmp_path):
        stats = scan_dir(str(tmp_path / "nope"))
        assert stats.file_count == 0

    def test_counts_files_and_size(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world!")
        stats = scan_dir(str(tmp_path))
        assert stats.file_count == 2
        assert stats.size_kb > 0

    def test_records_mtimes(self, tmp_path):
        (tmp_path / "file.txt").write_text("data")
        stats = scan_dir(str(tmp_path))
        assert stats.earliest_mtime is not None
        assert stats.latest_mtime is not None
        assert stats.earliest_mtime <= stats.latest_mtime

    def test_cache_hit(self, tmp_path):
        (tmp_path / "file.txt").write_text("data")
        cache = {}
        stats1 = scan_dir(str(tmp_path), cache)
        stats2 = scan_dir(str(tmp_path), cache)
        assert stats1 is stats2

    def test_recursive(self, tmp_path):
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        (sub / "deep.txt").write_text("nested")
        (tmp_path / "top.txt").write_text("top")
        stats = scan_dir(str(tmp_path))
        assert stats.file_count == 2


# ── estimate_context_pressure ────────────────────────────────────────────────


class TestEstimateContextPressure:
    def test_low_pressure(self, tmp_path):
        steps = {
            "requirements": _completed_step(),
            "code-analysis": _completed_step(),
            "planning": _completed_step(),
        }
        for s in steps:
            _make_step_dir(str(tmp_path), s, files={"out.md": "x" * 100})

        result = estimate_context_pressure(STEP_ORDER, steps, str(tmp_path))
        assert result["level"] == "low"
        assert result["risk_score"] < 3
        assert result["completed_steps"] == 3

    def test_moderate_pressure_from_step_count(self, tmp_path):
        step_names = STEP_ORDER[:6]
        steps = {s: _completed_step() for s in step_names}
        for s in step_names:
            _make_step_dir(str(tmp_path), s, files={"out.md": "x" * 100})

        result = estimate_context_pressure(STEP_ORDER, steps, str(tmp_path))
        assert result["risk_score"] >= 2

    def test_high_pressure_from_many_steps(self, tmp_path):
        step_names = STEP_ORDER[:8]
        steps = {s: _completed_step() for s in step_names}
        for s in step_names:
            _make_step_dir(str(tmp_path), s, files={"out.md": "x" * 1024 * 100})

        result = estimate_context_pressure(STEP_ORDER, steps, str(tmp_path))
        assert result["risk_score"] >= 4

    def test_iteration_overhead_adds_to_score(self, tmp_path):
        steps = {
            "requirements": _completed_step(),
            "technical-review": _completed_step(result={"iteration": 3}),
        }
        for s in steps:
            _make_step_dir(str(tmp_path), s, files={"out.md": "small"})

        result = estimate_context_pressure(STEP_ORDER, steps, str(tmp_path))
        assert result["iteration_overhead"] == 2
        assert any("iteration" in rf for rf in result["risk_factors"])

    def test_large_artifacts_add_to_score(self, tmp_path):
        steps = {"requirements": _completed_step()}
        _make_step_dir(
            str(tmp_path),
            "requirements",
            files={"big.md": "x" * 1024 * 600},
        )

        result = estimate_context_pressure(STEP_ORDER, steps, str(tmp_path))
        assert result["total_artifact_kb"] > 500
        assert any("artifact" in rf.lower() for rf in result["risk_factors"])

    def test_skipped_steps_excluded_from_total(self, tmp_path):
        steps = {
            "requirements": _completed_step(),
            "pr-analysis": {"status": "skipped"},
        }
        _make_step_dir(str(tmp_path), "requirements", files={"out.md": "x"})

        result = estimate_context_pressure(STEP_ORDER, steps, str(tmp_path))
        assert result["completed_steps"] == 1
        assert result["total_active_steps"] < len(STEP_ORDER)

    def test_weighted_load_calculation(self, tmp_path):
        steps = {
            "writing": _completed_step(),
            "technical-review": _completed_step(),
        }
        for s in steps:
            _make_step_dir(str(tmp_path), s, files={"out.md": "x"})

        result = estimate_context_pressure(STEP_ORDER, steps, str(tmp_path))
        assert result["weighted_context_load"] == 3.8  # 2.0 + 1.8


# ── detect_failures ──────────────────────────────────────────────────────────


class TestDetectFailures:
    def test_no_failures(self, tmp_path):
        steps = {"requirements": _completed_step()}
        _make_step_dir(
            str(tmp_path),
            "requirements",
            sidecar={
                "schema_version": 1,
                "step": "requirements",
            },
        )
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        assert failures == []

    def test_step_failed(self, tmp_path):
        steps = {"requirements": {"status": "failed"}}
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        assert len(failures) == 1
        assert failures[0]["type"] == "step_failed"
        assert failures[0]["severity"] == "high"

    def test_missing_output_dir(self, tmp_path):
        steps = {
            "requirements": _completed_step(output=str(tmp_path / "requirements" / "nonexistent")),
        }
        _make_step_dir(
            str(tmp_path),
            "requirements",
            sidecar={
                "schema_version": 1,
                "step": "requirements",
            },
        )
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        missing = [f for f in failures if f["type"] == "missing_output"]
        assert len(missing) == 1

    def test_missing_sidecar(self, tmp_path):
        steps = {"requirements": _completed_step()}
        os.makedirs(os.path.join(str(tmp_path), "requirements"))
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        sidecars = [f for f in failures if f["type"] == "missing_sidecar"]
        assert len(sidecars) == 1

    def test_step_deferred(self, tmp_path):
        steps = {"security-review": {"status": "deferred"}}
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        deferred = [f for f in failures if f["type"] == "step_deferred"]
        assert len(deferred) == 1
        assert deferred[0]["severity"] == "medium"

    def test_low_confidence(self, tmp_path):
        steps = {
            "technical-review": _completed_step(result={"confidence": "LOW", "iteration": 2}),
        }
        _make_step_dir(
            str(tmp_path),
            "technical-review",
            sidecar={
                "schema_version": 1,
                "step": "technical-review",
            },
        )
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        low_conf = [f for f in failures if f["type"] == "low_confidence"]
        assert len(low_conf) == 1

    def test_high_severity_count(self, tmp_path):
        steps = {
            "technical-review": _completed_step(
                result={"severity_counts": {"critical": 3, "significant": 2}}
            ),
        }
        _make_step_dir(
            str(tmp_path),
            "technical-review",
            sidecar={
                "schema_version": 1,
                "step": "technical-review",
            },
        )
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        high_sev = [f for f in failures if f["type"] == "high_severity_count"]
        assert len(high_sev) == 1

    def test_quality_gate_low(self, tmp_path):
        steps = {
            "quality-gate": _completed_step(result={"intent_alignment": 2}),
        }
        _make_step_dir(
            str(tmp_path),
            "quality-gate",
            sidecar={
                "schema_version": 1,
                "step": "quality-gate",
            },
        )
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        gate = [f for f in failures if f["type"] == "quality_gate_low"]
        assert len(gate) == 1

    def test_quality_gate_passing(self, tmp_path):
        steps = {
            "quality-gate": _completed_step(result={"intent_alignment": 4}),
        }
        _make_step_dir(
            str(tmp_path),
            "quality-gate",
            sidecar={
                "schema_version": 1,
                "step": "quality-gate",
            },
        )
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        gate = [f for f in failures if f["type"] == "quality_gate_low"]
        assert gate == []

    def test_empty_plan(self, tmp_path):
        steps = {
            "planning": _completed_step(result={"module_count": 0}),
        }
        _make_step_dir(
            str(tmp_path),
            "planning",
            sidecar={
                "schema_version": 1,
                "step": "planning",
            },
        )
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        empty = [f for f in failures if f["type"] == "empty_plan"]
        assert len(empty) == 1

    def test_no_files_written(self, tmp_path):
        steps = {
            "writing": _completed_step(result={"files": []}),
        }
        _make_step_dir(
            str(tmp_path),
            "writing",
            sidecar={
                "schema_version": 1,
                "step": "writing",
            },
        )
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        no_files = [f for f in failures if f["type"] == "no_files_written"]
        assert len(no_files) == 1

    def test_multiple_failures_combined(self, tmp_path):
        steps = {
            "requirements": {"status": "failed"},
            "planning": _completed_step(result={"module_count": 0}),
            "security-review": {"status": "deferred"},
        }
        _make_step_dir(
            str(tmp_path),
            "planning",
            sidecar={
                "schema_version": 1,
                "step": "planning",
            },
        )
        failures = detect_failures(STEP_ORDER, steps, str(tmp_path))
        types = {f["type"] for f in failures}
        assert "step_failed" in types
        assert "empty_plan" in types
        assert "step_deferred" in types


# ── detect_bottlenecks ───────────────────────────────────────────────────────


class TestDetectBottlenecks:
    def test_no_bottlenecks(self):
        timeline = [
            {"step": "requirements", "duration_s": 120},
            {"step": "planning", "duration_s": 100},
            {"step": "writing", "duration_s": 130},
        ]
        bottlenecks = detect_bottlenecks(timeline)
        assert bottlenecks == []

    def test_high_ratio_bottleneck(self):
        timeline = [
            {"step": "requirements", "duration_s": 60},
            {"step": "planning", "duration_s": 60},
            {"step": "writing", "duration_s": 900},
        ]
        bottlenecks = detect_bottlenecks(timeline)
        assert len(bottlenecks) >= 1
        assert bottlenecks[0]["step"] == "writing"

    def test_absolute_threshold(self):
        timeline = [
            {"step": "requirements", "duration_s": 500},
            {"step": "writing", "duration_s": 700},
        ]
        bottlenecks = detect_bottlenecks(timeline)
        assert any(b["step"] == "writing" for b in bottlenecks)

    def test_expected_duration_overrun(self):
        timeline = [
            {"step": "requirements", "duration_s": 400},
            {"step": "planning", "duration_s": 400},
        ]
        bottlenecks = detect_bottlenecks(timeline)
        planning = [b for b in bottlenecks if b["step"] == "planning"]
        assert len(planning) == 1
        assert "expected_s" in planning[0]

    def test_sorted_by_duration(self):
        timeline = [
            {"step": "requirements", "duration_s": 60},
            {"step": "planning", "duration_s": 800},
            {"step": "writing", "duration_s": 1200},
        ]
        bottlenecks = detect_bottlenecks(timeline)
        assert len(bottlenecks) >= 2
        assert bottlenecks[0]["duration_s"] >= bottlenecks[1]["duration_s"]

    def test_empty_timeline(self):
        assert detect_bottlenecks([]) == []

    def test_null_durations_skipped(self):
        timeline = [
            {"step": "requirements", "duration_s": None},
            {"step": "planning", "duration_s": 100},
        ]
        bottlenecks = detect_bottlenecks(timeline)
        assert all(b["step"] != "requirements" for b in bottlenecks)


# ── build_recommendations ────────────────────────────────────────────────────


class TestBuildRecommendations:
    def test_healthy_pipeline(self):
        recs = build_recommendations(
            failures=[],
            bottlenecks=[],
            context_pressure={
                "level": "low",
                "iteration_overhead": 0,
                "total_artifact_kb": 100,
            },
        )
        assert len(recs) == 1
        assert "No significant issues" in recs[0]

    def test_high_severity_failures(self):
        recs = build_recommendations(
            failures=[{"severity": "high", "step": "writing", "type": "step_failed"}],
            bottlenecks=[],
            context_pressure={
                "level": "low",
                "iteration_overhead": 0,
                "total_artifact_kb": 100,
            },
        )
        assert any("Fix high-severity" in r for r in recs)

    def test_high_context_pressure(self):
        recs = build_recommendations(
            failures=[],
            bottlenecks=[],
            context_pressure={
                "level": "high",
                "iteration_overhead": 0,
                "total_artifact_kb": 100,
            },
        )
        assert any("Context pressure" in r for r in recs)

    def test_iteration_overhead(self):
        recs = build_recommendations(
            failures=[],
            bottlenecks=[],
            context_pressure={
                "level": "low",
                "iteration_overhead": 2,
                "total_artifact_kb": 100,
            },
        )
        assert any("iteration" in r for r in recs)

    def test_code_analysis_bottleneck(self):
        recs = build_recommendations(
            failures=[],
            bottlenecks=[{"step": "code-analysis", "duration_s": 700}],
            context_pressure={
                "level": "low",
                "iteration_overhead": 0,
                "total_artifact_kb": 100,
            },
        )
        assert any("code-analysis" in r for r in recs)

    def test_missing_sidecars(self):
        recs = build_recommendations(
            failures=[
                {"type": "missing_sidecar", "step": "writing", "severity": "low"},
            ],
            bottlenecks=[],
            context_pressure={
                "level": "low",
                "iteration_overhead": 0,
                "total_artifact_kb": 100,
            },
        )
        assert any("sidecar" in r.lower() for r in recs)

    def test_large_total_artifacts(self):
        recs = build_recommendations(
            failures=[],
            bottlenecks=[],
            context_pressure={
                "level": "low",
                "iteration_overhead": 0,
                "total_artifact_kb": 2500,
            },
        )
        assert any("2500" in r for r in recs)


# ── resolve_output_path ──────────────────────────────────────────────────────


class TestResolveOutputPath:
    def test_absolute_path(self, tmp_path):
        d = tmp_path / "step"
        d.mkdir()
        assert resolve_output_path(str(d), str(tmp_path)) == str(d)

    def test_relative_path_exists_cwd(self, tmp_path, monkeypatch):
        d = tmp_path / "step"
        d.mkdir()
        monkeypatch.chdir(tmp_path)
        result = resolve_output_path("step", str(tmp_path))
        assert os.path.isabs(result)
        assert result.endswith("step")

    def test_relative_resolved_via_base_path(self, tmp_path):
        base = tmp_path / "workspace"
        step_dir = base / "writing"
        step_dir.mkdir(parents=True)
        result = resolve_output_path(".agent_workspace/test/writing", str(base))
        assert result == str(step_dir)

    def test_nonexistent_returned_as_is(self, tmp_path):
        result = resolve_output_path("nonexistent", str(tmp_path))
        assert result == "nonexistent"


# ── derive_base_path ─────────────────────────────────────────────────────────


class TestDeriveBasePath:
    def test_explicit_base_path(self, tmp_path):
        base = tmp_path / "workspace"
        base.mkdir()
        progress = {"base_path": str(base)}
        result = derive_base_path("dummy.json", progress)
        assert result == str(base)

    def test_derived_from_file_location(self, tmp_path):
        base = tmp_path / "workspace"
        workflow_dir = base / "workflow"
        workflow_dir.mkdir(parents=True)
        progress_path = str(workflow_dir / "progress.json")
        result = derive_base_path(progress_path, {"base_path": ""})
        assert result == str(base)

    def test_derived_from_step_output(self, tmp_path):
        step_dir = tmp_path / "writing"
        step_dir.mkdir()
        progress = {
            "base_path": "",
            "steps": {
                "writing": {"output": str(step_dir)},
            },
        }
        result = derive_base_path("/some/other/path.json", progress)
        assert result == str(tmp_path)

    def test_fallback_to_empty(self):
        result = derive_base_path("/nonexistent/path.json", {"base_path": ""})
        assert result == ""


# ── find_progress_files ──────────────────────────────────────────────────────


class TestFindProgressFiles:
    def test_finds_by_ticket(self, tmp_path):
        ticket_dir = tmp_path / "test-123" / "workflow"
        ticket_dir.mkdir(parents=True)
        (ticket_dir / "docs-workflow_test-123.json").write_text("{}")
        files = find_progress_files("TEST-123", str(tmp_path))
        assert len(files) == 1

    def test_finds_all(self, tmp_path):
        for ticket in ["abc-1", "def-2"]:
            d = tmp_path / ticket / "workflow"
            d.mkdir(parents=True)
            (d / f"wf_{ticket}.json").write_text("{}")
        files = find_progress_files(None, str(tmp_path))
        assert len(files) == 2

    def test_skips_stop_count_files(self, tmp_path):
        d = tmp_path / "test-1" / "workflow"
        d.mkdir(parents=True)
        (d / "wf.json").write_text("{}")
        (d / "wf.stop_count").write_text("3")
        files = find_progress_files(None, str(tmp_path))
        assert len(files) == 1
        assert files[0].endswith("wf.json")

    def test_skips_non_progress_files(self, tmp_path):
        # load_workflow.py writes steps.json/options.json alongside the progress
        # file; steps.json has a list-valued "steps" and must not be parsed as one.
        d = tmp_path / "test-1" / "workflow"
        d.mkdir(parents=True)
        (d / "docs-workflow_test-1.json").write_text("{}")
        (d / "steps.json").write_text('{"steps": []}')
        (d / "options.json").write_text("{}")
        files = find_progress_files(None, str(tmp_path))
        assert len(files) == 1
        assert files[0].endswith("docs-workflow_test-1.json")

    def test_malformed_progress_file_does_not_crash(self, tmp_path):
        # A stray file that slips through (top-level list) degrades to an error
        # entry rather than crashing the whole run.
        assert analyze  # imported below in TestAnalyze; ensure name is available
        d = tmp_path / "test-1" / "workflow"
        d.mkdir(parents=True)
        bad = d / "docs-workflow_test-1.json"
        bad.write_text("[1, 2, 3]")
        try:
            analyze(str(bad))
            raised = False
        except ValueError:
            raised = True
        assert raised

    def test_missing_workspace(self, tmp_path):
        files = find_progress_files(None, str(tmp_path / "nope"))
        assert files == []

    def test_skips_dotdirs(self, tmp_path):
        d = tmp_path / ".hidden" / "workflow"
        d.mkdir(parents=True)
        (d / "wf.json").write_text("{}")
        files = find_progress_files(None, str(tmp_path))
        assert files == []


# ── detect_loop_groups ───────────────────────────────────────────────────────


class TestDetectLoopGroups:
    def test_no_loops_when_single_iteration(self, tmp_path):
        steps = {
            "technical-review": _completed_step(result={"iteration": 1}),
        }
        timeline = [
            {"step": "technical-review", "completed_at": "2026-06-01T11:00:00"},
        ]
        groups = detect_loop_groups(STEP_ORDER, steps, str(tmp_path), timeline)
        assert groups == []

    def test_detects_tech_review_loop(self, tmp_path):
        steps = {
            "style-review": _completed_step(),
            "technical-review": _completed_step(result={"iteration": 2}),
        }
        _make_step_dir(str(tmp_path), "technical-review", files={"review.md": "x"})

        timeline = [
            {"step": "style-review", "completed_at": "2026-06-01T11:00:00"},
            {"step": "technical-review", "completed_at": "2026-06-01T11:30:00"},
        ]
        groups = detect_loop_groups(STEP_ORDER, steps, str(tmp_path), timeline)
        assert len(groups) == 1
        assert groups[0]["name"] == "technical-review-loop"
        assert groups[0]["iterations"] == 2

    def test_detects_quality_gate_loop(self, tmp_path):
        steps = {
            "style-review": _completed_step(),
            "quality-gate": _completed_step(result={"iteration": 3}),
        }
        _make_step_dir(str(tmp_path), "quality-gate", files={"gate.md": "x"})

        timeline = [
            {"step": "style-review", "completed_at": "2026-06-01T11:00:00"},
            {"step": "quality-gate", "completed_at": "2026-06-01T11:30:00"},
        ]
        groups = detect_loop_groups(STEP_ORDER, steps, str(tmp_path), timeline)
        assert len(groups) == 1
        assert groups[0]["name"] == "quality-gate-loop"
        assert "quality-gate" in groups[0]["steps"]

    def test_loop_has_step_breakdown(self, tmp_path):
        steps = {
            "style-review": _completed_step(),
            "technical-review": _completed_step(result={"iteration": 2}),
        }
        _make_step_dir(str(tmp_path), "technical-review", files={"review.md": "x"})

        timeline = [
            {"step": "style-review", "completed_at": "2026-06-01T11:00:00"},
            {"step": "technical-review", "completed_at": "2026-06-01T11:30:00"},
        ]
        groups = detect_loop_groups(STEP_ORDER, steps, str(tmp_path), timeline)
        assert "step_breakdown" in groups[0]
        assert len(groups[0]["step_breakdown"]) == 1
        assert groups[0]["step_breakdown"][0]["step"] == "technical-review"


# ── analyze (full integration) ───────────────────────────────────────────────


class TestAnalyze:
    def test_clean_run(self, tmp_path):
        steps = {
            "requirements": _completed_step(),
            "planning": _completed_step(),
            "writing": _completed_step(),
        }
        for s in steps:
            _make_step_dir(
                str(tmp_path / "test-1"),
                s,
                sidecar={
                    "schema_version": 1,
                    "step": s,
                    "completed_at": "2026-06-01T11:00:00Z",
                },
                files={"out.md": "content"},
            )

        progress_path, _ = _make_progress(
            tmp_path,
            ticket="TEST-1",
            steps=steps,
        )
        result = analyze(progress_path)

        assert result["summary"]["ticket"] == "TEST-1"
        assert result["summary"]["workflow"] == "docs-workflow"
        assert result["summary"]["status"] == "completed"
        assert isinstance(result["timeline"], list)
        assert isinstance(result["failures"], list)
        assert isinstance(result["bottlenecks"], list)
        assert isinstance(result["context_pressure"], dict)
        assert isinstance(result["recommendations"], list)

    def test_failed_run(self, tmp_path):
        steps = {
            "requirements": {"status": "failed"},
        }
        progress_path, _ = _make_progress(
            tmp_path,
            ticket="TEST-2",
            steps=steps,
            status="failed",
        )
        result = analyze(progress_path)
        assert result["summary"]["status"] == "failed"
        assert any(f["type"] == "step_failed" for f in result["failures"])
        assert any("Fix high-severity" in r for r in result["recommendations"])

    def test_run_with_iterations(self, tmp_path):
        steps = {
            "requirements": _completed_step(),
            "planning": _completed_step(),
            "writing": _completed_step(),
            "technical-review": _completed_step(result={"iteration": 2}),
            "quality-gate": _completed_step(result={"iteration": 3}),
            "resolve-feedback": _completed_step(),
        }
        for s in steps:
            _make_step_dir(
                str(tmp_path / "test-3"),
                s,
                sidecar={
                    "schema_version": 1,
                    "step": s,
                    "completed_at": "2026-06-01T11:00:00Z",
                    "iteration": steps[s].get("result", {}).get("iteration", 1),
                },
                files={"out.md": "content"},
            )

        progress_path, _ = _make_progress(
            tmp_path,
            ticket="TEST-3",
            steps=steps,
        )
        result = analyze(progress_path)
        assert result["context_pressure"]["iteration_overhead"] == 3
        assert len(result["loop_groups"]) >= 1

    def test_derive_base_path_when_missing(self, tmp_path):
        steps = {"requirements": _completed_step()}
        base = tmp_path / "test-4"
        workflow_dir = base / "workflow"
        workflow_dir.mkdir(parents=True)
        _make_step_dir(
            str(base),
            "requirements",
            sidecar={
                "schema_version": 1,
                "step": "requirements",
            },
            files={"out.md": "x"},
        )

        progress = {
            "ticket": "TEST-4",
            "base_path": "",
            "step_order": STEP_ORDER,
            "steps": steps,
            "status": "completed",
            "workflow": "docs-workflow",
            "created_at": "2026-06-01T10:00:00Z",
            "updated_at": "2026-06-01T12:00:00Z",
        }
        progress_path = workflow_dir / "wf_test-4.json"
        progress_path.write_text(json.dumps(progress))

        result = analyze(str(progress_path))
        assert result["summary"]["base_path"] == str(base)

    def test_output_structure(self, tmp_path):
        progress_path, _ = _make_progress(tmp_path, ticket="TEST-5", steps={})
        result = analyze(progress_path)
        expected_keys = {
            "summary",
            "timeline",
            "loop_groups",
            "workarounds",
            "failures",
            "bottlenecks",
            "context_pressure",
            "orchestrator_health",
            "recommendations",
        }
        assert set(result.keys()) == expected_keys
        summary_keys = {
            "ticket",
            "workflow",
            "status",
            "started_at",
            "finished_at",
            "total_duration_s",
            "total_duration_min",
            "timing_source",
            "progress_file",
            "base_path",
        }
        assert set(result["summary"].keys()) == summary_keys


# ── orchestrator_health ──────────────────────────────────────────────────────


class TestOrchestratorHealth:
    def _run(self, tmp_path, steps, status="completed", workflow="docs-workflow"):
        progress_path, base = _make_progress(
            tmp_path, steps=steps, status=status, workflow=workflow
        )
        with open(progress_path) as f:
            progress = json.load(f)
        step_order = list(steps.keys())
        health = orchestrator_health(progress, step_order, steps, base, [], [])
        return {h["check"] for h in health}, health

    def test_clean_run_when_sidecars_present(self, tmp_path):
        _, base = _make_progress(tmp_path, steps={})
        steps = {"requirements": _completed_step(result={"requirement_count": 3})}
        _make_step_dir(base, "requirements", sidecar={"step": "requirements"})
        progress = {
            "ticket": "T",
            "status": "in_progress",
            "workflow": "docs-workflow",
            "step_order": ["requirements"],
            "steps": steps,
        }
        health = orchestrator_health(progress, ["requirements"], steps, base, [], [])
        assert health == []

    def test_missing_sidecar(self, tmp_path):
        steps = {"writing": _completed_step(result={"files": []})}
        checks, _ = self._run(tmp_path, steps)
        assert "missing_sidecar" in checks

    def test_null_result(self, tmp_path):
        _, base = _make_progress(tmp_path, steps={})
        steps = {"technical-review": {"status": "completed", "result": None}}
        _make_step_dir(base, "technical-review", sidecar={"step": "technical-review"})
        progress = {
            "ticket": "T",
            "status": "completed",
            "workflow": "docs-workflow",
            "step_order": ["technical-review"],
            "steps": steps,
        }
        checks = {
            h["check"]
            for h in orchestrator_health(progress, ["technical-review"], steps, base, [], [])
        }
        assert "null_result" in checks
        assert "missing_sidecar" not in checks

    def test_stuck_in_progress(self, tmp_path):
        steps = {"writing": {"status": "in_progress"}}
        checks, health = self._run(tmp_path, steps)
        assert "stuck_in_progress" in checks
        assert any(h["severity"] == "high" for h in health if h["check"] == "stuck_in_progress")

    def test_deferred_unresolved(self, tmp_path):
        steps = {"quality-gate": {"status": "deferred"}}
        checks, _ = self._run(tmp_path, steps)
        assert "deferred_unresolved" in checks

    def test_workarounds_applied(self, tmp_path):
        _, base = _make_progress(tmp_path, steps={})
        progress = {
            "ticket": "T",
            "status": "completed",
            "workflow": "docs-workflow",
            "step_order": [],
            "steps": {},
        }
        workarounds = [{"step": "writing", "issue": "x", "action": "y"}]
        checks = {h["check"] for h in orchestrator_health(progress, [], {}, base, [], workarounds)}
        assert "workarounds_applied" in checks

    def test_active_marker_left(self, tmp_path):
        _, base = _make_progress(tmp_path, steps={})
        # marker lives one level up from base_path (the workspace root)
        marker = os.path.join(os.path.dirname(base), ".active-workflow")
        with open(marker, "w") as f:
            f.write("")
        progress = {
            "ticket": "T",
            "status": "completed",
            "workflow": "docs-workflow",
            "step_order": [],
            "steps": {},
        }
        checks = {h["check"] for h in orchestrator_health(progress, [], {}, base, [], [])}
        assert "active_marker_left" in checks

    def test_active_marker_not_flagged_when_in_progress(self, tmp_path):
        _, base = _make_progress(tmp_path, steps={})
        marker = os.path.join(os.path.dirname(base), ".active-workflow")
        with open(marker, "w") as f:
            f.write("")
        progress = {
            "ticket": "T",
            "status": "in_progress",
            "workflow": "docs-workflow",
            "step_order": [],
            "steps": {},
        }
        checks = {h["check"] for h in orchestrator_health(progress, [], {}, base, [], [])}
        assert "active_marker_left" not in checks

    def test_schema_drift_null_required_field(self, tmp_path):
        _, base = _make_progress(tmp_path, steps={})
        progress = {
            "ticket": None,
            "status": "completed",
            "workflow": "docs-workflow",
            "step_order": [],
            "steps": {},
        }
        checks = {h["check"] for h in orchestrator_health(progress, [], {}, base, [], [])}
        assert "schema_drift" in checks

    def test_timestamp_gap(self, tmp_path):
        _, base = _make_progress(tmp_path, steps={})
        progress = {
            "ticket": "T",
            "status": "completed",
            "workflow": "docs-workflow",
            "step_order": ["writing"],
            "steps": {"writing": {"status": "completed"}},
        }
        timeline = [{"step": "writing", "status": "completed", "duration_s": 900}]
        checks = {
            h["check"]
            for h in orchestrator_health(
                progress, ["writing"], progress["steps"], base, timeline, []
            )
        }
        assert "timestamp_gap" in checks


# ── build_sidecar / --emit-sidecar ───────────────────────────────────────────


class TestBuildSidecar:
    def test_sidecar_is_schema_conformant(self, tmp_path):
        steps = {
            "requirements": _completed_step(result={"requirement_count": 8}),
            "quality-gate": {"status": "deferred"},
        }
        progress_path, base = _make_progress(
            tmp_path, steps=steps, step_order=["requirements", "quality-gate"]
        )
        _make_step_dir(base, "requirements", sidecar={"step": "requirements"})
        analysis = analyze(progress_path)
        sidecar = build_sidecar(analysis)
        expected = {
            "schema_version",
            "step",
            "ticket",
            "completed_at",
            "pipeline_status",
            "context_pressure_level",
            "context_pressure_score",
            "failure_count",
            "high_severity_failure_count",
            "bottleneck_count",
            "orchestrator_issue_count",
            "workaround_count",
            "recommendation_count",
            "total_duration_min",
        }
        assert set(sidecar.keys()) == expected
        assert sidecar["schema_version"] == 1
        assert sidecar["step"] == "pipeline-diagnostics"
        assert sidecar["pipeline_status"] == "completed"
        # completed_at is a real wall-clock timestamp, not the synthetic progress value
        assert sidecar["completed_at"] != "2026-06-01T12:00:00Z"
        assert isinstance(sidecar["orchestrator_issue_count"], int)

    def test_counts_reflect_analysis(self, tmp_path):
        progress_path, base = _make_progress(
            tmp_path,
            steps={"writing": _completed_step(result={"files": []})},
            step_order=["writing"],
        )
        # writing completed with 0 files -> a failure; no sidecar -> orchestrator issue
        analysis = analyze(progress_path)
        sidecar = build_sidecar(analysis)
        assert sidecar["failure_count"] == len(analysis["failures"])
        assert sidecar["orchestrator_issue_count"] == len(analysis["orchestrator_health"])
        assert sidecar["workaround_count"] == 0


# ---------------------------------------------------------------------------
# derive_pipeline_status
# ---------------------------------------------------------------------------
class TestDerivePipelineStatus:
    ORDER = ["writing", "technical-review"]

    def test_all_completed_overrides_in_progress(self):
        steps = {
            "writing": {"status": "completed"},
            "technical-review": {"status": "completed"},
        }
        result = derive_pipeline_status(steps, self.ORDER, "in_progress")
        assert result == "completed"

    def test_mixed_completed_and_skipped(self):
        steps = {
            "writing": {"status": "completed"},
            "technical-review": {"status": "skipped"},
        }
        result = derive_pipeline_status(steps, self.ORDER, "in_progress")
        assert result == "completed"

    def test_any_failed_returns_failed(self):
        steps = {
            "writing": {"status": "completed"},
            "technical-review": {"status": "failed"},
        }
        result = derive_pipeline_status(steps, self.ORDER, "in_progress")
        assert result == "failed"

    def test_pending_step_preserves_raw_status(self):
        steps = {
            "writing": {"status": "completed"},
            "technical-review": {"status": "pending"},
        }
        result = derive_pipeline_status(steps, self.ORDER, "in_progress")
        assert result == "in_progress"

    def test_already_completed_passes_through(self):
        steps = {"writing": {"status": "completed"}}
        result = derive_pipeline_status(steps, ["writing"], "completed")
        assert result == "completed"

    def test_already_failed_passes_through(self):
        steps = {"writing": {"status": "completed"}}
        result = derive_pipeline_status(steps, ["writing"], "failed")
        assert result == "failed"

    def test_unknown_raw_status_derives(self):
        steps = {
            "writing": {"status": "completed"},
            "technical-review": {"status": "completed"},
        }
        result = derive_pipeline_status(steps, self.ORDER, "unknown")
        assert result == "completed"

    def test_empty_step_order_returns_raw(self):
        result = derive_pipeline_status({}, [], "in_progress")
        assert result == "in_progress"

    def test_missing_step_treated_as_pending(self):
        steps = {"writing": {"status": "completed"}}
        order = ["writing", "missing-step"]
        result = derive_pipeline_status(steps, order, "in_progress")
        assert result == "in_progress"

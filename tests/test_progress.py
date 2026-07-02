"""Tests for progress.py — progress-file init and rewind state transitions."""

import json
import subprocess
import sys
from pathlib import Path

from progress import build_progress, progress_path_for, rewind_progress

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "docs-orchestrator"
    / "scripts"
    / "progress.py"
)


def _steps():
    return [
        {"name": "requirements", "status": "pending"},
        {"name": "code-analysis", "status": "deferred"},
        {"name": "writing", "status": "pending"},
        {"name": "create-merge-request", "status": "skipped"},
    ]


# ── build_progress ───────────────────────────────────────────────────────────


class TestBuildProgress:
    def test_shape(self):
        p = build_progress("PROJ-1", "docs-workflow", "/abs/proj-1", _steps(), {"draft": False})
        assert p["ticket"] == "PROJ-1"
        assert p["workflow"] == "docs-workflow"
        assert p["status"] == "in_progress"
        assert p["base_path"] == "/abs/proj-1"
        assert p["options"] == {"draft": False}
        assert p["workarounds"] == []
        assert p["created_at"] and p["updated_at"]

    def test_step_order_and_statuses(self):
        p = build_progress("PROJ-1", "docs-workflow", "/abs/proj-1", _steps(), {})
        assert p["step_order"] == [
            "requirements",
            "code-analysis",
            "writing",
            "create-merge-request",
        ]
        assert p["steps"]["code-analysis"]["status"] == "deferred"
        assert p["steps"]["create-merge-request"]["status"] == "skipped"
        assert p["steps"]["requirements"] == {"status": "pending", "output": None, "result": None}

    def test_path_for_lowercases_ticket(self):
        path = progress_path_for("/abs/PROJ-1", "docs-workflow", "PROJ-1")
        assert path.endswith("/abs/PROJ-1/workflow/docs-workflow_proj-1.json")


# ── rewind_progress ──────────────────────────────────────────────────────────


def _completed_progress(base_path):
    p = build_progress("PROJ-1", "docs-workflow", base_path, _steps(), {})
    # mark requirements, code-analysis, writing completed with output/result
    for name in ("requirements", "code-analysis", "writing"):
        p["steps"][name]["status"] = "completed"
        p["steps"][name]["output"] = f"{base_path}/{name}"
        p["steps"][name]["result"] = {"done": True}
    return p


class TestRewindProgress:
    def test_no_reset_when_all_outputs_present(self, tmp_path):
        base = str(tmp_path)
        for name in ("requirements", "code-analysis", "writing"):
            (tmp_path / name).mkdir()
        p = _completed_progress(base)
        summary = rewind_progress(p, base)
        assert summary["rewound_from"] is None
        assert summary["reset_steps"] == []
        assert p["steps"]["writing"]["status"] == "completed"

    def test_missing_output_resets_step_and_downstream_completed(self, tmp_path):
        base = str(tmp_path)
        # code-analysis output is missing; requirements and writing dirs exist
        (tmp_path / "requirements").mkdir()
        (tmp_path / "writing").mkdir()
        p = _completed_progress(base)
        summary = rewind_progress(p, base)
        assert summary["rewound_from"] == "code-analysis"
        assert summary["reset_steps"] == ["code-analysis", "writing"]
        # stale + downstream completed reset to pending, cleared
        assert p["steps"]["code-analysis"]["status"] == "pending"
        assert p["steps"]["code-analysis"]["result"] is None
        assert p["steps"]["writing"]["status"] == "pending"
        # upstream completed untouched
        assert p["steps"]["requirements"]["status"] == "completed"
        # skipped step stays skipped, not reset to pending
        assert p["steps"]["create-merge-request"]["status"] == "skipped"

    def test_rewind_updates_timestamp(self, tmp_path):
        base = str(tmp_path)
        (tmp_path / "requirements").mkdir()
        p = _completed_progress(base)
        p["updated_at"] = "2000-01-01T00:00:00Z"
        rewind_progress(p, base)
        assert p["updated_at"] != "2000-01-01T00:00:00Z"


# ── CLI ──────────────────────────────────────────────────────────────────────


def _run(args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


class TestCli:
    def test_init_writes_file(self, tmp_path):
        steps_file = tmp_path / "steps.json"
        steps_file.write_text(json.dumps({"steps": _steps()}))
        base = tmp_path / "proj-1"
        result = _run(
            [
                "init",
                "--base-path",
                str(base),
                "--ticket",
                "PROJ-1",
                "--workflow",
                "docs-workflow",
                "--steps",
                str(steps_file),
            ]
        )
        assert result.returncode == 0, result.stderr
        pf = base / "workflow" / "docs-workflow_proj-1.json"
        assert pf.is_file()
        data = json.loads(pf.read_text())
        assert data["step_order"][0] == "requirements"

    def test_init_refuses_overwrite_without_force(self, tmp_path):
        steps_file = tmp_path / "steps.json"
        steps_file.write_text(json.dumps({"steps": _steps()}))
        base = tmp_path / "proj-1"
        args = [
            "init",
            "--base-path",
            str(base),
            "--ticket",
            "PROJ-1",
            "--workflow",
            "docs-workflow",
            "--steps",
            str(steps_file),
        ]
        assert _run(args).returncode == 0
        # second run without --force fails
        assert _run(args).returncode != 0
        # with --force succeeds
        assert _run(args + ["--force"]).returncode == 0

    def test_rewind_cli_emits_summary(self, tmp_path):
        base = tmp_path / "proj-1"
        (base / "requirements").mkdir(parents=True)
        pf = base / "workflow" / "docs-workflow_proj-1.json"
        pf.parent.mkdir(parents=True)
        p = _completed_progress(str(base))
        pf.write_text(json.dumps(p))
        result = _run(["rewind", "--progress-file", str(pf)])
        assert result.returncode == 0, result.stderr
        summary = json.loads(result.stdout)
        assert summary["rewound_from"] == "code-analysis"
        # file was mutated on disk
        assert json.loads(pf.read_text())["steps"]["writing"]["status"] == "pending"

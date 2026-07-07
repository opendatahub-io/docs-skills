"""Tests for metadata extractor scripts: count_modules, parse_review_meta, parse_manifest."""

import json
import os
import subprocess

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")


def run_script(name, args):
    result = subprocess.run(  # noqa: S603
        ["python3", os.path.join(SCRIPTS_DIR, name)] + args,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result


class TestCountModules:
    def test_counts_module_headings(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(
            "# Plan\n\n"
            "### Module: Installing the operator\n\n"
            "Content here.\n\n"
            "### Module: Configuring TLS\n\n"
            "More content.\n\n"
            "### Module: Upgrading\n\n"
            "Final content.\n"
        )
        result = run_script("count_modules.py", [str(plan)])
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["module_count"] == 3

    def test_ignores_code_blocks(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(
            "### Module: Real module\n\n"
            "```\n"
            "### Module: Fake module in code block\n"
            "```\n\n"
            "### Module: Another real module\n"
        )
        result = run_script("count_modules.py", [str(plan)])
        data = json.loads(result.stdout)
        assert data["module_count"] == 2

    def test_empty_plan(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Empty plan\n\nNo modules here.\n")
        result = run_script("count_modules.py", [str(plan)])
        data = json.loads(result.stdout)
        assert data["module_count"] == 0

    def test_missing_file(self):
        result = run_script("count_modules.py", ["/nonexistent/plan.md"])
        assert result.returncode == 1


class TestParseReviewMeta:
    def test_extracts_confidence_and_severity(self, tmp_path):
        review = tmp_path / "review.md"
        review.write_text(
            "# Technical Review\n\n"
            "Overall technical confidence: MEDIUM\n\n"
            "Severity counts: critical=1 significant=2 minor=3 sme=4\n"
        )
        result = run_script("parse_review_meta.py", [str(review)])
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["confidence"] == "MEDIUM"
        assert data["severity_counts"]["critical"] == 1
        assert data["severity_counts"]["significant"] == 2
        assert data["severity_counts"]["minor"] == 3
        assert data["severity_counts"]["sme"] == 4

    def test_confidence_only(self, tmp_path):
        review = tmp_path / "review.md"
        review.write_text("Overall technical confidence: HIGH\n")
        result = run_script("parse_review_meta.py", [str(review)])
        data = json.loads(result.stdout)
        assert data["confidence"] == "HIGH"
        assert data["severity_counts"]["critical"] == 0

    def test_no_confidence(self, tmp_path):
        review = tmp_path / "review.md"
        review.write_text("No confidence line here.\n")
        result = run_script("parse_review_meta.py", [str(review)])
        data = json.loads(result.stdout)
        assert data["confidence"] is None

    def test_iteration_and_code_grounded(self, tmp_path):
        review = tmp_path / "review.md"
        review.write_text("Overall technical confidence: LOW\n")
        result = run_script("parse_review_meta.py", [str(review), "3", "true"])
        data = json.loads(result.stdout)
        assert data["iteration"] == 3
        assert data["code_grounded"] is True

    def test_missing_file(self):
        result = run_script("parse_review_meta.py", ["/nonexistent/review.md"])
        assert result.returncode == 1


class TestParseManifest:
    def test_extracts_absolute_paths(self, tmp_path):
        manifest = tmp_path / "_index.md"
        manifest.write_text(
            "# Writing manifest\n\n"
            "| File | Type |\n"
            "|---|---|\n"
            "| /home/user/docs/proc-install.adoc | procedure |\n"
            "| /home/user/docs/con-overview.adoc | concept |\n"
            "| /home/user/docs/nav.adoc | navigation |\n"
        )
        result = run_script(
            "parse_manifest.py", [str(manifest), "--mode", "update-in-place", "--format", "adoc"]
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data["files"]) == 3
        assert data["mode"] == "update-in-place"
        assert data["format"] == "adoc"

    def test_extracts_from_list_items(self, tmp_path):
        manifest = tmp_path / "_index.md"
        manifest.write_text("# Files\n\n- `/home/user/docs/a.adoc`\n- `/home/user/docs/b.adoc`\n")
        result = run_script("parse_manifest.py", [str(manifest)])
        data = json.loads(result.stdout)
        assert len(data["files"]) == 2

    def test_empty_manifest(self, tmp_path):
        manifest = tmp_path / "_index.md"
        manifest.write_text("# Empty manifest\n\nNo files written.\n")
        result = run_script("parse_manifest.py", [str(manifest)])
        data = json.loads(result.stdout)
        assert data["files"] == []

    def test_deduplicates(self, tmp_path):
        manifest = tmp_path / "_index.md"
        manifest.write_text("| /home/a.adoc | new |\n| /home/a.adoc | modified |\n")
        result = run_script("parse_manifest.py", [str(manifest)])
        data = json.loads(result.stdout)
        assert len(data["files"]) == 1

    def test_missing_file(self):
        result = run_script("parse_manifest.py", ["/nonexistent/_index.md"])
        assert result.returncode == 1


class TestWriteStepResult:
    def test_writes_sidecar(self, tmp_path):
        result = run_script(
            "write_step_result.py",
            [
                "--step",
                "planning",
                "--ticket",
                "PROJ-123",
                "--output-dir",
                str(tmp_path),
                "--data",
                '{"module_count": 5}',
            ],
        )
        assert result.returncode == 0

        sidecar_path = tmp_path / "step-result.json"
        assert sidecar_path.exists()

        data = json.loads(sidecar_path.read_text())
        assert data["schema_version"] == 1
        assert data["step"] == "planning"
        assert data["ticket"] == "PROJ-123"
        assert data["module_count"] == 5
        assert "completed_at" in data

    def test_no_extra_data(self, tmp_path):
        result = run_script(
            "write_step_result.py",
            [
                "--step",
                "style-review",
                "--ticket",
                "T-1",
                "--output-dir",
                str(tmp_path),
            ],
        )
        assert result.returncode == 0
        data = json.loads((tmp_path / "step-result.json").read_text())
        assert data["step"] == "style-review"
        assert data["schema_version"] == 1

    def test_invalid_json_data(self, tmp_path):
        result = run_script(
            "write_step_result.py",
            [
                "--step",
                "x",
                "--ticket",
                "T-1",
                "--output-dir",
                str(tmp_path),
                "--data",
                "not-json",
            ],
        )
        assert result.returncode == 1

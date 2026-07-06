"""Tests for docs-workflow-tech-review/scripts/prepare_review.py."""

import json
import os
import subprocess
import sys

SCRIPT = os.path.join(
    os.path.dirname(__file__),
    "..",
    "skills",
    "docs-workflow-tech-review",
    "scripts",
    "prepare_review.py",
)


def run_prepare(tmp_path, extra_args=None):
    """Run prepare_review.py and return parsed JSON output."""
    base = str(tmp_path / "workspace")
    cmd = [sys.executable, SCRIPT, "PROJ-123", "--base-path", base]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return json.loads(result.stdout)


class TestPrepareReview:
    def test_basic_output(self, tmp_path):
        config = run_prepare(tmp_path)
        assert config["ticket"] == "PROJ-123"
        assert config["has_repo"] is False
        assert config["has_code_analysis"] is False
        assert config["iteration"] == 1

    def test_iteration_default(self, tmp_path):
        config = run_prepare(tmp_path)
        assert config["iteration"] == 1

    def test_iteration_explicit(self, tmp_path):
        config = run_prepare(tmp_path, ["--iteration", "2"])
        assert config["iteration"] == 2

    def test_iteration_3(self, tmp_path):
        config = run_prepare(tmp_path, ["--iteration", "3"])
        assert config["iteration"] == 3

    def test_repo_path(self, tmp_path):
        repo = tmp_path / "my-repo"
        repo.mkdir()
        config = run_prepare(tmp_path, ["--repo", str(repo)])
        assert config["has_repo"] is True
        assert config["repo_path"] == str(repo)

    def test_code_analysis_detected(self, tmp_path):
        base = tmp_path / "workspace"
        ca_dir = base / "code-analysis"
        ca_dir.mkdir(parents=True)
        (ca_dir / "ONBOARDING.md").write_text("# Onboarding")
        config = run_prepare(tmp_path)
        assert config["has_code_analysis"] is True

    def test_writing_sidecar_update_in_place(self, tmp_path):
        base = tmp_path / "workspace"
        writing_dir = base / "writing"
        writing_dir.mkdir(parents=True)
        sidecar = {
            "mode": "update-in-place",
            "files": ["modules/foo.adoc", "modules/bar.adoc"],
        }
        (writing_dir / "step-result.json").write_text(json.dumps(sidecar))
        config = run_prepare(tmp_path)
        assert "modules/foo.adoc" in config["source_files_block"]
        assert "modules/bar.adoc" in config["source_files_block"]

    def test_prior_validation_detected(self, tmp_path):
        base = tmp_path / "workspace"
        tr_dir = base / "technical-review"
        tr_dir.mkdir(parents=True)
        (tr_dir / "claim-validation.json").write_text("{}")
        config = run_prepare(tmp_path)
        assert config["has_prior_validation"] is True

    def test_output_dirs_created(self, tmp_path):
        config = run_prepare(tmp_path)
        assert os.path.isdir(config["output_dir"])

    def test_missing_ticket_fails(self, tmp_path):
        base = str(tmp_path / "workspace")
        cmd = [sys.executable, SCRIPT, "--base-path", base]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        assert result.returncode != 0

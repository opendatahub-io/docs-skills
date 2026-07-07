"""Tests for docs-workflow-tech-review/scripts/prepare_review.py."""

import json
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "skills",
    "docs-workflow-tech-review",
    "scripts",
)
SCRIPT = os.path.join(SCRIPTS_DIR, "prepare_review.py")

sys.path.insert(0, SCRIPTS_DIR)

from prepare_review import extract_prior_findings  # noqa: E402

SAMPLE_REVIEW = """\
## Technical Review — install.adoc

**Doc type detected:** Procedure
**Reviewer lens applied:** Developer
**Overall technical confidence:** MEDIUM — gaps in prerequisites

### Critical issues (must fix before publication)
- **Location**: Step 3
  **Issue**: The `oc apply` command is missing `-f`.
  **Impact**: The command fails.
  **Suggestion**: Add `-f manifest.yaml`.

### Significant issues (should fix)
None identified.

### Minor issues (consider fixing)
- **Location**: Introduction
  **Issue**: No verification step after install.
  **Impact**: The reader cannot confirm success.
  **Suggestion**: Add `oc get pods`.

### SME verification needed
None identified.

### Strengths
Clear structure and good examples.

Severity counts: critical=1 significant=0 minor=1 sme=0
"""


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

    def test_prior_findings_null_iteration_1(self, tmp_path):
        config = run_prepare(tmp_path)
        assert config["prior_findings_file"] is None

    def test_prior_findings_null_when_no_review(self, tmp_path):
        # Iteration 2 but no prior review.md present.
        config = run_prepare(tmp_path, ["--iteration", "2"])
        assert config["prior_findings_file"] is None

    def test_prior_findings_extracted_iteration_2(self, tmp_path):
        base = tmp_path / "workspace"
        tr_dir = base / "technical-review"
        tr_dir.mkdir(parents=True)
        (tr_dir / "review.md").write_text(SAMPLE_REVIEW)

        config = run_prepare(tmp_path, ["--iteration", "2"])

        pf = config["prior_findings_file"]
        assert pf is not None
        assert pf.endswith("prior-findings-iter-1.md")
        assert os.path.isfile(pf)
        content = open(pf).read()
        assert "Prior confidence: MEDIUM" in content
        assert "critical=1 significant=0 minor=1 sme=0" in content
        # Kept sections with real findings.
        assert "## Critical" in content
        assert "manifest.yaml" in content
        assert "## Minor" in content
        # Dropped "None identified." sections and Strengths.
        assert "## Significant" not in content
        assert "## SME verification" not in content
        assert "Strengths" not in content


class TestExtractPriorFindings:
    def test_extracts_sections_and_header(self, tmp_path):
        review = tmp_path / "review.md"
        review.write_text(SAMPLE_REVIEW)
        out = tmp_path / "prior.md"

        extract_prior_findings(str(review), str(out), 1)

        content = out.read_text()
        assert content.startswith("# Prior findings (iteration 1)")
        assert "Prior confidence: MEDIUM" in content
        assert "## Critical" in content
        assert "## Minor" in content
        assert "None identified" not in content

    def test_all_clean_review(self, tmp_path):
        review = tmp_path / "review.md"
        review.write_text(
            "**Overall technical confidence:** HIGH — solid\n\n"
            "### Critical issues\nNone identified.\n\n"
            "### Significant issues\nNone identified.\n\n"
            "### Minor issues\nNone identified.\n\n"
            "### SME verification needed\nNone identified.\n\n"
            "Severity counts: critical=0 significant=0 minor=0 sme=0\n"
        )
        out = tmp_path / "prior.md"

        extract_prior_findings(str(review), str(out), 2)

        content = out.read_text()
        assert "Prior confidence: HIGH" in content
        assert "No outstanding findings were recorded" in content

"""Tests for the writing and planning write_step_result.py helpers.

Both scripts share the module name ``write_step_result`` and cannot both be
imported by bare name, so they are loaded by file path.
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from schema_helpers import validate_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(rel_path, mod_name):
    path = REPO_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


writing_wsr = _load("skills/docs-workflow-writing/scripts/write_step_result.py", "writing_wsr")
planning_wsr = _load("skills/docs-workflow-planning/scripts/write_step_result.py", "planning_wsr")
code_analysis_wsr = _load(
    "skills/docs-workflow-code-analysis/scripts/write_step_result.py", "code_analysis_wsr"
)


def _make_analysis(base):
    """Build a minimal learn-code analysis tree under base."""
    (base / "module-registry").mkdir(parents=True)
    (base / "module-registry" / "registry.json").write_text(json.dumps([{"m": 1}, {"m": 2}]))
    (base / "relationships").mkdir()
    (base / "relationships" / "a.json").write_text("{}")
    (base / "relationships" / "b.json").write_text("{}")
    (base / "relationships" / "notes.txt").write_text("ignored")
    (base / "detection").mkdir()
    (base / "detection" / "detection.json").write_text(
        json.dumps({"language_counts": {"python": 10, "go": 3}, "primary_language": "python"})
    )


class TestCodeAnalysisMetrics:
    def test_module_count_is_array_length(self, tmp_path):
        _make_analysis(tmp_path)
        assert code_analysis_wsr._module_count(tmp_path) == 2

    def test_relationship_count_ignores_non_json(self, tmp_path):
        _make_analysis(tmp_path)
        assert code_analysis_wsr._relationship_count(tmp_path) == 2

    def test_languages_from_language_counts(self, tmp_path):
        _make_analysis(tmp_path)
        assert set(code_analysis_wsr._languages_detected(tmp_path)) == {"python", "go"}

    def test_languages_fallback_to_primary(self, tmp_path):
        (tmp_path / "detection").mkdir()
        (tmp_path / "detection" / "detection.json").write_text(
            json.dumps({"primary_language": "rust"})
        )
        assert code_analysis_wsr._languages_detected(tmp_path) == ["rust"]

    def test_missing_files_yield_zero_and_empty(self, tmp_path):
        assert code_analysis_wsr._module_count(tmp_path) == 0
        assert code_analysis_wsr._relationship_count(tmp_path) == 0
        assert code_analysis_wsr._languages_detected(tmp_path) == []

    def test_main_writes_schema_conformant_sidecar(self, tmp_path, monkeypatch):
        analysis = tmp_path / "analysis"
        analysis.mkdir()
        _make_analysis(analysis)
        repo = tmp_path / "repo"
        repo.mkdir()
        sidecar = tmp_path / "out" / "step-result.json"

        monkeypatch.setattr(
            "sys.argv",
            [
                "write_step_result.py",
                "--ticket",
                "TEST-1",
                "--repo",
                str(repo),
                "--analysis-path",
                str(analysis),
                "--sidecar",
                str(sidecar),
            ],
        )
        assert code_analysis_wsr.main() == 0

        data = json.loads(sidecar.read_text())
        # Counts must be integers, not string placeholders.
        assert data["module_count"] == 2
        assert data["relationship_count"] == 2
        assert isinstance(data["module_count"], int)
        validate_sidecar("code-analysis", data)


class TestWritingExtractFiles:
    def test_keeps_existing_paths_drops_phantoms(self, tmp_path):
        real = tmp_path / "master.adoc"
        real.write_text("= Doc")
        manifest = tmp_path / "_index.md"
        # Second row is a relative path; the regex would yield a phantom
        # /master.adoc that must be dropped because it doesn't exist.
        manifest.write_text(
            f"| File | Status |\n| {real} | new |\n| deploying-llmd/master.adoc | new |\n"
        )
        files = writing_wsr.extract_files(str(manifest))
        assert files == [str(real)]

    def test_all_phantoms_yields_empty(self, tmp_path):
        manifest = tmp_path / "_index.md"
        manifest.write_text("| a/nope.adoc | new |\n| b/gone.md | new |\n")
        assert writing_wsr.extract_files(str(manifest)) == []


class TestPlanningCountModules:
    def test_counts_module_and_update_headings(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(
            "## Module Specifications\n\n"
            "### Module: New concept\n\n"
            "### Update 1: Fix install doc\n\n"
            "### Update 2: Add a note\n"
        )
        assert planning_wsr.count_modules(str(plan)) == 3

    def test_ignores_code_blocks(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("### Update 1: real\n\n```\n### Update 2: fake\n```\n")
        assert planning_wsr.count_modules(str(plan)) == 1

"""Tests for the writing and planning write_step_result.py helpers.

Both scripts share the module name ``write_step_result`` and cannot both be
imported by bare name, so they are loaded by file path.
"""

import importlib.util
from pathlib import Path

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

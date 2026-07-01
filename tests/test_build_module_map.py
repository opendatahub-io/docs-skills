"""Tests for build_module_map.py — plan parsing, slugging, strategy decision."""

import json

from build_module_map import build_map, decide, parse_modules, slugify

PLAN_MANY = """# Documentation Plan

## New Docs

* Understanding the Operator (Concept)
    What the operator is and why it matters.
* Installing the Operator (Procedure)
    Steps to install from OperatorHub.
* Configuring the Operator (Procedure)
    How operators are configured after install.
* Operator configuration parameters (Reference)
    Table of all settings.
* Scaling workloads (Procedure)
    Autoscaling behavior.
* Monitoring the Operator (Concept)
    Metrics exposed.
* Uninstalling the Operator (Procedure)
    Clean removal.
* Troubleshooting the Operator (Reference)
    Common errors.
* Operator architecture (Concept)
    Control loop overview.

## Updated Docs

* existing-overview.adoc
    Add a link to the new install procedure.
"""

PLAN_FEW = """# Documentation Plan

## New Docs

* Understanding the Operator (Concept)
    Overview.
* Installing the Operator (Procedure)
    Steps.
"""


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert slugify("Configuring the Operator") == "configuring-the-operator"

    def test_strips_punctuation_and_collapses(self):
        assert slugify("Operator config: parameters!") == "operator-config-parameters"

    def test_strips_adoc_extension(self):
        assert slugify("existing-overview.adoc") == "existing-overview"


class TestParseModules:
    def test_parses_new_docs_title_and_type(self):
        mods = parse_modules(PLAN_MANY)
        first = mods[0]
        assert first["title"] == "Understanding the Operator"
        assert first["type"] == "concept"
        assert first["scope"] == "What the operator is and why it matters."
        assert first["anchor"] == "understanding-the-operator"

    def test_normalizes_type_to_lowercase_canonical(self):
        mods = parse_modules(PLAN_MANY)
        types = {m["type"] for m in mods}
        assert types <= {"concept", "procedure", "reference"}

    def test_includes_updated_docs_entries(self):
        mods = parse_modules(PLAN_MANY)
        titles = [m["title"] for m in mods]
        assert "existing-overview.adoc" in titles

    def test_empty_when_no_module_sections(self):
        assert parse_modules("# Documentation Plan\n\nNo modules here.\n") == []


class TestDecide:
    def test_fix_mode_is_single(self):
        strategy, reason = decide([{"x": 1}] * 20, 20, 8, "fix")
        assert strategy == "single"
        assert reason == "fix_mode"

    def test_at_or_below_threshold_is_single(self):
        strategy, reason = decide([{"x": 1}] * 8, 8, 8, "draft")
        assert strategy == "single"
        assert reason == "below_threshold"

    def test_above_threshold_with_modules_is_per_module(self):
        strategy, reason = decide([{"x": 1}] * 10, 10, 8, "draft")
        assert strategy == "per_module"
        assert reason is None

    def test_above_threshold_without_parseable_modules_falls_back(self):
        strategy, reason = decide([], 10, 8, "draft")
        assert strategy == "single"
        assert reason == "no_module_ids"


class TestBuildMap:
    def test_per_module_output_files_for_draft_adoc(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(PLAN_MANY)
        result = build_map(
            plan_path=str(plan),
            planning_result_path=None,
            output_dir="/work/writing",
            fmt="adoc",
            mode="draft",
            threshold=8,
        )
        assert result["writer_strategy"] == "per_module"
        assert result["module_count"] == 10
        files = [m["output_file"] for m in result["modules"]]
        assert "/work/writing/modules/configuring-the-operator.adoc" in files

    def test_mkdocs_extension_and_dir(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(PLAN_MANY)
        result = build_map(
            plan_path=str(plan),
            planning_result_path=None,
            output_dir="/work/writing",
            fmt="mkdocs",
            mode="draft",
            threshold=8,
        )
        files = [m["output_file"] for m in result["modules"]]
        assert "/work/writing/docs/configuring-the-operator.md" in files

    def test_module_count_from_sidecar_drives_threshold(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(PLAN_FEW)
        sidecar = tmp_path / "step-result.json"
        sidecar.write_text(json.dumps({"module_count": 12}))
        result = build_map(
            plan_path=str(plan),
            planning_result_path=str(sidecar),
            output_dir="/work/writing",
            fmt="adoc",
            mode="draft",
            threshold=8,
        )
        # sidecar says 12 (>8) but only 2 modules parse -> still per_module,
        # map reflects the 2 parseable modules.
        assert result["module_count"] == 12
        assert result["writer_strategy"] == "per_module"
        assert len(result["modules"]) == 2

    def test_below_threshold_is_single(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(PLAN_FEW)
        result = build_map(
            plan_path=str(plan),
            planning_result_path=None,
            output_dir="/work/writing",
            fmt="adoc",
            mode="draft",
            threshold=8,
        )
        assert result["writer_strategy"] == "single"
        assert result["fallback_reason"] == "below_threshold"

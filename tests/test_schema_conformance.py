"""Validate step-result sidecars conform to their JSON Schemas."""

from __future__ import annotations

import copy
import os
import sys

import pytest
from jsonschema import Draft202012Validator, ValidationError

sys.path.insert(0, os.path.dirname(__file__))

from schema_helpers import discover_schemas, load_schema

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

OUTPUT_SCHEMAS = discover_schemas("output")
INPUT_SCHEMAS = discover_schemas("input")

_TS = "2025-01-01T00:00:00+00:00"

# ---------------------------------------------------------------------------
# Golden output examples — one minimal valid dict per step
# ---------------------------------------------------------------------------

GOLDEN_EXAMPLES: dict[str, dict] = {
    "requirements": {
        "schema_version": 1,
        "step": "requirements",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "title": "Add install guide",
        "requirement_count": 3,
    },
    "code-analysis": {
        "schema_version": 1,
        "step": "code-analysis",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "module_count": 2,
        "relationship_count": 1,
        "languages_detected": ["go"],
        "repo_path": "/src/repo",
        "repo_analysis_path": "/tmp/analysis",
    },
    "scope-req-audit": {
        "schema_version": 1,
        "step": "scope-req-audit",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "recommendation": "proceed",
        "grounded": 3,
        "partial": 1,
        "absent": 0,
        "total": 4,
        "discovered_repos_count": 0,
        "secondary_repos_count": 0,
    },
    "pr-analysis": {
        "schema_version": 1,
        "step": "pr-analysis",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "pr_number": 42,
        "pr_url": "https://github.com/org/repo/pull/42",
        "modules_affected": 1,
        "platform": "github",
    },
    "planning": {
        "schema_version": 1,
        "step": "planning",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "module_count": 2,
    },
    "writing": {
        "schema_version": 1,
        "step": "writing",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "files": ["/docs/install.adoc"],
        "mode": "update-in-place",
        "format": "adoc",
    },
    "tech-review": {
        "schema_version": 1,
        "step": "technical-review",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "confidence": "HIGH",
        "severity_counts": {"critical": 0, "significant": 0, "minor": 1, "sme": 0},
        "iteration": 1,
        "code_grounded": True,
    },
    "style-review": {
        "schema_version": 1,
        "step": "style-review",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "fixes_applied": 2,
        "warnings": 1,
        "suggestions": 3,
    },
    "security-review": {
        "schema_version": 1,
        "step": "security-review",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "scanner_findings": 0,
        "critical_findings": 0,
        "agent_findings": 0,
        "categories": {
            "ip": 0,
            "email": 0,
            "credential": 0,
            "url": 0,
            "mac": 0,
            "internal_hostname": 0,
        },
        "context_size_bytes": 1024,
    },
    "quality-gate": {
        "schema_version": 1,
        "step": "quality-gate",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "doc_quality": 4,
        "intent_alignment": 4,
        "passed": True,
        "iteration": 1,
        "evidence_expected": False,
        "evidence_warning": None,
        "coverage_check": None,
        "gaps": [],
        "rationales": {
            "doc_quality": "Solid writing quality.",
            "intent_alignment": "All ACs addressed.",
        },
    },
    "pipeline-diagnostics": {
        "schema_version": 1,
        "step": "pipeline-diagnostics",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "pipeline_status": "completed",
        "context_pressure_level": "low",
        "context_pressure_score": 0,
        "failure_count": 0,
        "high_severity_failure_count": 0,
        "bottleneck_count": 0,
        "orchestrator_issue_count": 0,
        "workaround_count": 0,
        "recommendation_count": 0,
        "total_duration_min": 12.5,
    },
    "create-merge-request": {
        "schema_version": 1,
        "step": "create-merge-request",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "commit_sha": "abc1234",
        "branch": "docs/TEST-1",
        "pushed": True,
        "url": "https://github.com/org/repo/pull/99",
        "action": "created",
        "platform": "github",
        "skipped": False,
        "skip_reason": None,
    },
    "create-jira": {
        "schema_version": 1,
        "step": "create-jira",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "jira_url": "https://issues.redhat.com/browse/DOCS-456",
        "jira_key": "DOCS-456",
        "action": "created",
        "skipped": False,
        "skip_reason": None,
    },
    "jira-ready": {
        "query": "project = DOCS AND status = 'To Do'",
        "total_matched": 5,
        "filtered_out": 2,
        "ready": [],
    },
    "action-comments": {
        "schema_version": 1,
        "step": "action-comments",
        "ticket": "TEST-1",
        "completed_at": _TS,
        "ci_mode": False,
        "comments_resolved": 3,
        "comments_skipped": 0,
        "comments_outdated": 1,
        "comments_replied": 0,
        "files_modified": ["/docs/install.adoc"],
    },
}

# ---------------------------------------------------------------------------
# Golden input examples — one minimal valid dict per step
# ---------------------------------------------------------------------------

GOLDEN_INPUT_EXAMPLES: dict[str, dict] = {
    "requirements": {"ticket": "TEST-1", "base_path": "/docs"},
    "code-analysis": {"repo": "/src/repo", "ticket": "TEST-1", "output_dir": "/tmp/out"},
    "scope-req-audit": {"ticket": "TEST-1", "base_path": "/docs"},
    "pr-analysis": {
        "pr": "https://github.com/org/repo/pull/1",
        "ticket": "TEST-1",
        "output_dir": "/tmp/out",
        "repo": "/src/repo",
    },
    "planning": {"ticket": "TEST-1", "base_path": "/docs"},
    "writing": {"ticket": "TEST-1", "base_path": "/docs", "format": "adoc"},
    "tech-review": {"ticket": "TEST-1", "base_path": "/docs"},
    "style-review": {"ticket": "TEST-1", "base_path": "/docs", "format": "adoc"},
    "security-review": {"ticket": "TEST-1", "base_path": "/docs"},
    "quality-gate": {"ticket": "TEST-1", "base_path": "/docs"},
    "pipeline-diagnostics": {"ticket": "TEST-1", "base_path": "/docs"},
    "create-merge-request": {"ticket": "TEST-1", "base_path": "/docs"},
    "create-jira": {"ticket": "TEST-1", "base_path": "/docs", "project": "DOCS"},
    "jira-ready": {"jql": "project = DOCS"},
    "start": {"ticket": "TEST-1"},
}


# ===================================================================
# Layer A — Schema self-validity
# ===================================================================


class TestSchemaValidity:
    """Every schema file must be valid JSON and valid JSON Schema 2020-12."""

    @pytest.mark.parametrize(
        "step_name, schema_path",
        OUTPUT_SCHEMAS + INPUT_SCHEMAS,
        ids=[f"{n}:{p.name}" for n, p in OUTPUT_SCHEMAS + INPUT_SCHEMAS],
    )
    def test_schema_is_valid_json_schema(self, step_name, schema_path):
        schema = load_schema(schema_path)
        Draft202012Validator.check_schema(schema)

    @pytest.mark.parametrize(
        "step_name, schema_path",
        OUTPUT_SCHEMAS,
        ids=[f"{n}:{p.name}" for n, p in OUTPUT_SCHEMAS],
    )
    def test_output_schema_has_common_fields(self, step_name, schema_path):
        """Output schemas (except jira-ready) must require the four common sidecar fields."""
        if step_name == "jira-ready":
            pytest.skip("jira-ready uses a different output contract")
        schema = load_schema(schema_path)
        required = schema.get("required", [])
        for field in ("schema_version", "step", "ticket", "completed_at"):
            assert field in required, f"{schema_path.name} missing required field {field!r}"

    @pytest.mark.parametrize(
        "step_name, schema_path",
        OUTPUT_SCHEMAS + INPUT_SCHEMAS,
        ids=[f"{n}:{p.name}" for n, p in OUTPUT_SCHEMAS + INPUT_SCHEMAS],
    )
    def test_schema_closes_additional_properties(self, step_name, schema_path):
        schema = load_schema(schema_path)
        assert schema.get("additionalProperties") is False, (
            f"{schema_path.name} should set additionalProperties: false"
        )


# ===================================================================
# Layer B — Golden example validation
# ===================================================================


class TestGoldenOutputExamples:
    """Every output schema must accept its golden example."""

    @pytest.mark.parametrize(
        "step_name, schema_path",
        OUTPUT_SCHEMAS,
        ids=[n for n, _ in OUTPUT_SCHEMAS],
    )
    def test_golden_example_validates(self, step_name, schema_path):
        assert step_name in GOLDEN_EXAMPLES, f"Missing golden example for {step_name}"
        schema = load_schema(schema_path)
        Draft202012Validator(schema).validate(GOLDEN_EXAMPLES[step_name])


class TestGoldenInputExamples:
    """Every input schema must accept its golden example."""

    @pytest.mark.parametrize(
        "step_name, schema_path",
        INPUT_SCHEMAS,
        ids=[n for n, _ in INPUT_SCHEMAS],
    )
    def test_golden_example_validates(self, step_name, schema_path):
        assert step_name in GOLDEN_INPUT_EXAMPLES, f"Missing golden input example for {step_name}"
        schema = load_schema(schema_path)
        Draft202012Validator(schema).validate(GOLDEN_INPUT_EXAMPLES[step_name])


# ===================================================================
# Layer C — Required-field rejection
# ===================================================================


def _required_field_params():
    """Yield (step_name, schema_path, field) for each required field in output schemas."""
    for step_name, schema_path in OUTPUT_SCHEMAS:
        schema = load_schema(schema_path)
        for field in schema.get("required", []):
            yield pytest.param(step_name, schema_path, field, id=f"{step_name}:{field}")


class TestRequiredFieldRejection:
    """Removing any single required field from a golden example must fail validation."""

    @pytest.mark.parametrize("step_name, schema_path, field", _required_field_params())
    def test_missing_required_field_rejected(self, step_name, schema_path, field):
        if step_name not in GOLDEN_EXAMPLES:
            pytest.skip(f"No golden example for {step_name}")
        example = copy.deepcopy(GOLDEN_EXAMPLES[step_name])
        example.pop(field, None)
        schema = load_schema(schema_path)
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(example)


# ===================================================================
# Layer D — Extra-field rejection
# ===================================================================


class TestAdditionalPropertiesRejection:
    """Adding an unexpected field to a golden example must fail validation."""

    @pytest.mark.parametrize(
        "step_name, schema_path",
        OUTPUT_SCHEMAS,
        ids=[n for n, _ in OUTPUT_SCHEMAS],
    )
    def test_extra_field_rejected(self, step_name, schema_path):
        if step_name not in GOLDEN_EXAMPLES:
            pytest.skip(f"No golden example for {step_name}")
        example = copy.deepcopy(GOLDEN_EXAMPLES[step_name])
        example["_unexpected_field"] = "should fail"
        schema = load_schema(schema_path)
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(example)

    @pytest.mark.parametrize(
        "step_name, schema_path",
        INPUT_SCHEMAS,
        ids=[n for n, _ in INPUT_SCHEMAS],
    )
    def test_extra_field_rejected_input(self, step_name, schema_path):
        if step_name not in GOLDEN_INPUT_EXAMPLES:
            pytest.skip(f"No golden input example for {step_name}")
        example = copy.deepcopy(GOLDEN_INPUT_EXAMPLES[step_name])
        example["_unexpected_field"] = "should fail"
        schema = load_schema(schema_path)
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(example)

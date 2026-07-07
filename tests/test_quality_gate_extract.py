"""Tests for quality_gate.py extract-json: pulling and validating agent JSON.

The Agent tool has no schema-enforced output, so judge/coverage agents return
prose wrapping a JSON object. extract-json recovers and validates it.
"""

import argparse
import json

import pytest
from quality_gate import (
    cmd_extract_json,
    extract_json_value,
    validate_against_schema,
)

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "skills" / "docs-workflow-quality-gate" / "schema"


class TestExtractJsonValue:
    def test_extracts_fenced_json_object(self):
        text = 'Here it is:\n```json\n{"score": 4, "rationale": "ok"}\n```\nDone.'
        assert extract_json_value(text) == {"score": 4, "rationale": "ok"}

    def test_prefers_last_fence(self):
        # Agents sometimes echo the schema first, then the real answer.
        text = '```json\n{"score": 0}\n```\nActually:\n```json\n{"score": 5}\n```'
        assert extract_json_value(text) == {"score": 5}

    def test_bare_object_without_fence(self):
        text = 'Result: {"score": 3, "rationale": "meh"} end'
        assert extract_json_value(text) == {"score": 3, "rationale": "meh"}

    def test_bare_array(self):
        text = 'items: [{"id": "a"}, {"id": "b"}] done'
        assert extract_json_value(text) == [{"id": "a"}, {"id": "b"}]

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            extract_json_value("no json here at all")


class TestValidateAgainstSchema:
    def test_valid_doc_quality(self):
        schema = json.loads((SCHEMA_DIR / "doc-quality.json").read_text())
        assert validate_against_schema({"score": 4, "rationale": "ok"}, schema) == []

    def test_missing_required_key(self):
        schema = json.loads((SCHEMA_DIR / "doc-quality.json").read_text())
        errors = validate_against_schema({"score": 4}, schema)
        assert errors and any("rationale" in e for e in errors)

    def test_wrong_top_level_type(self):
        schema = json.loads((SCHEMA_DIR / "coverage.json").read_text())
        errors = validate_against_schema([1, 2, 3], schema)
        assert errors


class TestCmdExtractJson:
    def _run(self, tmp_path, raw, schema_name, key=None):
        raw_file = tmp_path / "raw.md"
        raw_file.write_text(raw)
        out_file = tmp_path / "out.json"
        args = argparse.Namespace(
            raw=str(raw_file),
            schema=str(SCHEMA_DIR / schema_name),
            out=str(out_file),
            key=key,
        )
        rc = cmd_extract_json(args)
        return rc, out_file

    def test_coverage_key_unwrap(self, tmp_path):
        raw = '```json\n{"items": [{"id": "R1", "covered": true, "quote": "x"}]}\n```'
        rc, out_file = self._run(tmp_path, raw, "coverage.json", key="items")
        assert rc == 0
        assert json.loads(out_file.read_text()) == [{"id": "R1", "covered": True, "quote": "x"}]

    def test_judge_object(self, tmp_path):
        raw = '```json\n{"score": 5, "rationale": "great"}\n```'
        rc, out_file = self._run(tmp_path, raw, "doc-quality.json")
        assert rc == 0
        assert json.loads(out_file.read_text()) == {"score": 5, "rationale": "great"}

    def test_schema_mismatch_returns_1(self, tmp_path):
        raw = '```json\n{"score": 5}\n```'  # missing rationale
        rc, out_file = self._run(tmp_path, raw, "doc-quality.json")
        assert rc == 1
        assert not out_file.exists()

    def test_no_json_returns_1(self, tmp_path):
        rc, out_file = self._run(tmp_path, "sorry, no json", "doc-quality.json")
        assert rc == 1
        assert not out_file.exists()

    def test_missing_key_returns_1(self, tmp_path):
        raw = '```json\n{"score": 5, "rationale": "x"}\n```'
        rc, out_file = self._run(tmp_path, raw, "doc-quality.json", key="items")
        assert rc == 1
        assert not out_file.exists()

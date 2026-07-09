"""Tests for quality_gate.py prompt generation.

The judge/coverage agents write their own JSON reply to a raw file (via the
Write tool) instead of the orchestrator relaying it through a bash heredoc.
Each generated prompt must therefore tell the agent where to write.
"""

import argparse
import json

from quality_gate import (
    COVERAGE_CHECK_PROMPT,
    DOC_QUALITY_PROMPT,
    INTENT_ALIGNMENT_PROMPT,
    cmd_prepare,
    cmd_verify,
)


class TestPromptTemplatesRequestFileWrite:
    def test_doc_quality_prompt_has_raw_file_slot(self):
        rendered = DOC_QUALITY_PROMPT.format(
            doc_content="doc", raw_file="/x/dq-raw.md", verified_claims_section=""
        )
        assert "/x/dq-raw.md" in rendered
        assert "Write" in rendered

    def test_intent_alignment_prompt_has_raw_file_slot(self):
        rendered = INTENT_ALIGNMENT_PROMPT.format(
            ticket_context="tc", doc_content="doc", raw_file="/x/ia-raw.md"
        )
        assert "/x/ia-raw.md" in rendered
        assert "Write" in rendered

    def test_coverage_prompt_has_raw_file_slot(self):
        rendered = COVERAGE_CHECK_PROMPT.format(
            ac_list="- [ID: R1_AC00] do a thing",
            doc_content="doc",
            raw_file="/x/coverage-raw.md",
        )
        assert "/x/coverage-raw.md" in rendered
        assert "Write" in rendered


def _setup_base(tmp_path, mode="draft"):
    base = tmp_path
    (base / "writing").mkdir()
    doc = base / "writing" / "guide.adoc"
    doc.write_text("= Guide\n\nBody text.\n")
    (base / "writing" / "step-result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "step": "writing",
                "ticket": "T-1",
                "completed_at": "2020-01-01T00:00:00+00:00",
                "files": [str(doc)],
                "mode": mode,
                "format": "adoc",
            }
        )
    )
    (base / "requirements").mkdir()
    (base / "requirements" / "discovery.json").write_text(
        json.dumps(
            {
                "ticket_summary": "Do the thing",
                "requirements": [
                    {
                        "id": "REQ-1",
                        "title": "T",
                        "one_line_summary": "s",
                        "acceptance_criteria": ["The thing is done"],
                    },
                ],
            }
        )
    )
    return base


class TestCmdPrepareEmbedsRawPaths:
    def test_judge_prompts_reference_their_raw_files(self, tmp_path):
        base = _setup_base(tmp_path)
        cmd_prepare(argparse.Namespace(ticket="T-1", base_path=str(base)))
        dq = (base / "quality-gate" / "dq-prompt.md").read_text()
        ia = (base / "quality-gate" / "ia-prompt.md").read_text()
        assert str(base / "quality-gate" / "dq-raw.md") in dq
        assert str(base / "quality-gate" / "ia-raw.md") in ia


class TestCmdVerifyPrepareEmbedsRawPath:
    def test_coverage_prompt_references_raw_file(self, tmp_path):
        base = _setup_base(tmp_path)
        cmd_verify(
            argparse.Namespace(
                ticket="T-1",
                base_path=str(base),
                prepare=True,
                classify=False,
            )
        )
        cov = (base / "quality-gate" / "coverage-prompt.md").read_text()
        assert str(base / "quality-gate" / "coverage-raw.md") in cov


class TestCmdPrepareInjectsClaimValidation:
    def test_verified_claims_injected_when_present(self, tmp_path):
        base = _setup_base(tmp_path)
        tr_dir = base / "technical-review"
        tr_dir.mkdir()
        cv_data = {
            "claims": [
                {
                    "id": "C1",
                    "text": "KV cache transfer config requires vLLM 0.22.0+",
                    "verdict": "supported",
                    "evidence": "found in config",
                    "file": "x.yaml",
                    "line": 158,
                },
                {
                    "id": "C2",
                    "text": "Access log filtering requires vLLM 0.16.0+",
                    "verdict": "supported",
                    "evidence": "found",
                    "file": "x.yaml",
                    "line": 50,
                },
                {
                    "id": "C3",
                    "text": "Nonexistent flag --foo",
                    "verdict": "unsupported",
                    "evidence": "not found",
                    "file": "x.yaml",
                    "line": None,
                },
            ],
            "summary": {
                "supported": 2,
                "partially_supported": 0,
                "unsupported": 1,
                "no_evidence_found": 0,
            },
        }
        (tr_dir / "claim-validation.json").write_text(json.dumps(cv_data))

        cmd_prepare(argparse.Namespace(ticket="T-1", base_path=str(base)))
        dq = (base / "quality-gate" / "dq-prompt.md").read_text()
        assert "Verified claims" in dq
        assert "KV cache transfer" in dq
        assert "Access log filtering" in dq
        # Unsupported claims must NOT appear in the verified list
        assert "--foo" not in dq

    def test_no_verified_claims_when_file_missing(self, tmp_path):
        base = _setup_base(tmp_path)
        cmd_prepare(argparse.Namespace(ticket="T-1", base_path=str(base)))
        dq = (base / "quality-gate" / "dq-prompt.md").read_text()
        assert "Verified claims" not in dq

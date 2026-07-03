"""Tests for the quality_gate.py `brief` subcommand — feedback-brief rendering."""

import json
import subprocess
import sys
from pathlib import Path

from quality_gate import render_brief

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "docs-workflow-quality-gate"
    / "scripts"
    / "quality_gate.py"
)


def _sidecar():
    return {
        "rationales": {
            "doc_quality": "DQ_RATIONALE_MARKER rationale prose",
            "intent_alignment": "IA_RATIONALE_MARKER rationale prose",
        },
        "gaps": [
            {
                "ac_item": "Document confidence scores",
                "judge": "intent_alignment",
                "evidence_status": "absent",
                "action": "document_as_unsupported",
                "file": "proc-deploying-model.adoc",
                "section": "After 'Verifying the deployment'",
            }
        ],
    }


def _coverage():
    return {
        "total": 3,
        "covered": 2,
        "uncovered": 1,
        "items": [
            {
                "ac_text": "Covered AC",
                "req_id": "REQ-1",
                "classification": "covered",
                "evidence_status": "grounded",
                "action": None,
            },
            {
                "ac_text": "Absent AC",
                "req_id": "REQ-1",
                "classification": "correctly_absent",
                "evidence_status": "absent",
                "action": "document_as_unsupported",
            },
            {
                "ac_text": "Unverified AC",
                "req_id": "REQ-2",
                "classification": "unverified",
                "evidence_status": "unknown",
                "action": "investigate",
            },
        ],
    }


# ── render_brief ─────────────────────────────────────────────────────────────


class TestRenderBrief:
    def test_header_has_ticket_and_iteration(self):
        md = render_brief("PROJ-1", 1, _sidecar(), None)
        assert "PROJ-1" in md
        assert "iteration 1" in md

    def test_rationales_included_verbatim(self):
        md = render_brief("PROJ-1", 1, _sidecar(), None)
        assert "IA_RATIONALE_MARKER" in md
        assert "DQ_RATIONALE_MARKER" in md

    def test_no_coverage_section_when_absent(self):
        md = render_brief("PROJ-1", 1, _sidecar(), None)
        assert "Coverage Check Results" not in md

    def test_coverage_section_when_present(self):
        md = render_brief("PROJ-1", 1, _sidecar(), _coverage())
        assert "Coverage Check Results" in md
        assert "2/3" in md  # covered/total
        # covered items are not listed as uncovered
        assert "Covered AC" not in md
        # uncovered items are listed
        assert "Absent AC" in md
        assert "Unverified AC" in md

    def test_no_doc_quality_section_when_null(self):
        sidecar = _sidecar()
        sidecar["rationales"]["doc_quality"] = None
        md = render_brief("PROJ-1", 1, sidecar, None)
        assert "Doc Quality Judge Assessment" not in md
        assert "Intent Alignment Judge Assessment" in md

    def test_unverified_note_rendered(self):
        md = render_brief("PROJ-1", 1, _sidecar(), _coverage())
        assert "could not be verified" in md.lower()

    def test_gap_action_instruction_rendered(self):
        md = render_brief("PROJ-1", 1, _sidecar(), None)
        assert "Document confidence scores" in md
        assert "not supported in this release" in md  # document_as_unsupported instruction

    def test_prior_attempts_only_when_iteration_gt_1(self):
        assert "Prior attempts" not in render_brief("PROJ-1", 1, _sidecar(), None)
        md2 = render_brief("PROJ-1", 2, _sidecar(), None)
        assert "Prior attempts" in md2
        assert "DIFFERENT approach" in md2


# ── CLI ──────────────────────────────────────────────────────────────────────


class TestCli:
    def test_brief_writes_file(self, tmp_path):
        qg = tmp_path / "quality-gate"
        qg.mkdir()
        (qg / "step-result.json").write_text(json.dumps(_sidecar()))
        (qg / "coverage-check.json").write_text(json.dumps(_coverage()))
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "brief",
                "--ticket",
                "PROJ-1",
                "--base-path",
                str(tmp_path),
                "--iteration",
                "2",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        brief = qg / "feedback-brief-2.md"
        assert brief.is_file()
        text = brief.read_text()
        assert "iteration 2" in text
        assert "Prior attempts" in text
        assert "Coverage Check Results" in text

    def test_brief_without_coverage(self, tmp_path):
        qg = tmp_path / "quality-gate"
        qg.mkdir()
        (qg / "step-result.json").write_text(json.dumps(_sidecar()))
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "brief",
                "--ticket",
                "PROJ-1",
                "--base-path",
                str(tmp_path),
                "--iteration",
                "1",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        text = (qg / "feedback-brief-1.md").read_text()
        assert "Coverage Check Results" not in text

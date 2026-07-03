"""Tests for iteration_decision.py — the orchestrator's review/gate loop decisions.

One test per row of the decision tables in
docs/superpowers/specs/2026-07-02-offload-orchestrator-gate-logic-to-scripts-design.md,
plus CLI/sidecar integration.
"""

import json
import subprocess
import sys
from pathlib import Path

from iteration_decision import decide_quality_gate, decide_tech_review

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "skills"
    / "docs-orchestrator"
    / "scripts"
    / "iteration_decision.py"
)


# ── tech-review decision table ───────────────────────────────────────────────


class TestDecideTechReview:
    def test_high_is_done(self):
        d = decide_tech_review("HIGH", critical=2, significant=2, iteration=1)
        assert d["decision"] == "done"

    def test_medium_clean_is_done(self):
        d = decide_tech_review("MEDIUM", critical=0, significant=0, iteration=1)
        assert d["decision"] == "done"

    def test_medium_with_critical_before_max_is_fix(self):
        d = decide_tech_review("MEDIUM", critical=1, significant=0, iteration=1)
        assert d["decision"] == "fix"

    def test_medium_with_significant_before_max_is_fix(self):
        d = decide_tech_review("MEDIUM", critical=0, significant=2, iteration=1)
        assert d["decision"] == "fix"

    def test_low_before_max_is_fix(self):
        d = decide_tech_review("LOW", critical=0, significant=0, iteration=1)
        assert d["decision"] == "fix"

    def test_medium_with_issues_at_max_is_proceed_with_warning(self):
        d = decide_tech_review("MEDIUM", critical=1, significant=3, iteration=2)
        assert d["decision"] == "proceed_with_warning"
        assert d["list_findings"] is True
        # warning names both counts
        assert "1 critical" in d["warning"]
        assert "3 significant" in d["warning"]

    def test_low_at_max_is_ask_user(self):
        d = decide_tech_review("LOW", critical=0, significant=0, iteration=2)
        assert d["decision"] == "ask_user"

    def test_high_at_max_is_done(self):
        d = decide_tech_review("HIGH", critical=5, significant=5, iteration=2)
        assert d["decision"] == "done"

    def test_clean_decisions_have_no_warning(self):
        d = decide_tech_review("HIGH", critical=0, significant=0, iteration=1)
        assert d["warning"] is None
        assert d["list_findings"] is False

    def test_case_insensitive_confidence(self):
        d = decide_tech_review("high", critical=0, significant=0, iteration=1)
        assert d["decision"] == "done"


# ── quality-gate decision table ──────────────────────────────────────────────


class TestDecideQualityGate:
    def test_ia_pass_is_done(self):
        d = decide_quality_gate(intent_alignment=4, doc_quality=5, iteration=1)
        assert d["decision"] == "done"
        assert d["secondary_warning"] is None

    def test_ia_pass_low_dq_sets_secondary_warning(self):
        d = decide_quality_gate(intent_alignment=5, doc_quality=3, iteration=1)
        assert d["decision"] == "done"
        assert d["secondary_warning"] is not None

    def test_ia_fail_before_max_is_fix(self):
        d = decide_quality_gate(intent_alignment=3, doc_quality=5, iteration=1)
        assert d["decision"] == "fix"

    def test_ia_low_before_max_is_fix(self):
        d = decide_quality_gate(intent_alignment=2, doc_quality=5, iteration=1)
        assert d["decision"] == "fix"

    def test_ia_three_at_max_is_accept_with_warning(self):
        d = decide_quality_gate(intent_alignment=3, doc_quality=5, iteration=2)
        assert d["decision"] == "accept_with_warning"

    def test_ia_below_three_at_max_is_ask_user(self):
        d = decide_quality_gate(intent_alignment=2, doc_quality=5, iteration=2)
        assert d["decision"] == "ask_user"

    def test_ia_pass_at_max_is_done(self):
        d = decide_quality_gate(intent_alignment=4, doc_quality=5, iteration=2)
        assert d["decision"] == "done"

    def test_none_doc_quality_no_secondary_warning(self):
        d = decide_quality_gate(intent_alignment=4, doc_quality=None, iteration=1)
        assert d["decision"] == "done"
        assert d["secondary_warning"] is None


# ── CLI / sidecar integration ────────────────────────────────────────────────


def _run(args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


class TestCli:
    def test_tech_review_reads_sidecar(self, tmp_path):
        sidecar = tmp_path / "step-result.json"
        sidecar.write_text(
            json.dumps(
                {
                    "confidence": "MEDIUM",
                    "severity_counts": {"critical": 0, "significant": 0},
                    "iteration": 1,
                }
            )
        )
        result = _run(["tech-review", "--sidecar", str(sidecar)])
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        assert out["decision"] == "done"

    def test_quality_gate_reads_sidecar(self, tmp_path):
        sidecar = tmp_path / "step-result.json"
        sidecar.write_text(json.dumps({"intent_alignment": 3, "doc_quality": 5, "iteration": 2}))
        result = _run(["quality-gate", "--sidecar", str(sidecar)])
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        assert out["decision"] == "accept_with_warning"

    def test_quality_gate_null_doc_quality(self, tmp_path):
        sidecar = tmp_path / "step-result.json"
        sidecar.write_text(json.dumps({"intent_alignment": 4, "doc_quality": None, "iteration": 1}))
        result = _run(["quality-gate", "--sidecar", str(sidecar)])
        assert result.returncode == 0, result.stderr
        out = json.loads(result.stdout)
        assert out["decision"] == "done"
        assert out["secondary_warning"] is None

    def test_missing_sidecar_errors(self, tmp_path):
        result = _run(["tech-review", "--sidecar", str(tmp_path / "nope.json")])
        assert result.returncode != 0

    def test_max_iter_override(self, tmp_path):
        sidecar = tmp_path / "step-result.json"
        sidecar.write_text(
            json.dumps(
                {
                    "confidence": "MEDIUM",
                    "severity_counts": {"critical": 1, "significant": 0},
                    "iteration": 1,
                }
            )
        )
        # with max-iter 1, iteration 1 is already at max → proceed_with_warning
        result = _run(["tech-review", "--sidecar", str(sidecar), "--max-iter", "1"])
        out = json.loads(result.stdout)
        assert out["decision"] == "proceed_with_warning"

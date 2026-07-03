"""Tests for fixes addressing open PR #24 review comments.

Covers:
  1. merge_verdicts: stale verdict file filtering
  2. incremental_claims: non-dict claim tolerance
  3. split_claims: non-dict claim rejection
  4. quality_gate.classify_gaps: non-dict missed_items tolerance
  5. write_step_result: regex anchoring
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills"
MERGE = SCRIPTS / "docs-workflow-tech-review" / "scripts" / "merge_verdicts.py"
INCR = SCRIPTS / "docs-workflow-tech-review" / "scripts" / "incremental_claims.py"
SPLIT = SCRIPTS / "docs-workflow-tech-review" / "scripts" / "split_claims.py"
WRITE_SR = SCRIPTS / "docs-workflow-tech-review" / "scripts" / "write_step_result.py"
QG = SCRIPTS / "docs-workflow-quality-gate" / "scripts" / "quality_gate.py"


# ---------------------------------------------------------------------------
# 1. merge_verdicts: stale verdict file filtering
# ---------------------------------------------------------------------------
class TestMergeVerdictsStaleFiles:
    """Verify that stale batch-verdict files from prior runs are skipped."""

    def test_stale_verdict_skipped(self, tmp_path):
        claims = [
            {"id": "c1", "text": "claim one", "file": "doc.adoc", "line": 1},
        ]
        (tmp_path / "claims-list.json").write_text(json.dumps(claims))

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # batch-claims file for this run's batch
        (output_dir / "batch-claims-doc.json").write_text(json.dumps(claims))
        # Current verdict (matches the batch-claims file)
        (output_dir / "batch-verdict-doc.json").write_text(
            json.dumps([{"claim_id": "c1", "verdict": "supported", "evidence": "ok"}])
        )
        # STALE verdict from a prior run (no matching batch-claims file)
        (output_dir / "batch-verdict-old-doc.json").write_text(
            json.dumps([{"claim_id": "c1", "verdict": "unsupported", "evidence": "stale"}])
        )

        claims_out = tmp_path / "claim-validation.json"
        summary_out = tmp_path / "validation-summary.md"

        result = subprocess.run(
            [
                sys.executable, str(MERGE),
                "--claims-list", str(tmp_path / "claims-list.json"),
                "--output-dir", str(output_dir),
                "--claims-file", str(claims_out),
                "--summary-file", str(summary_out),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "Skipping stale verdict file" in result.stderr

        validation = json.loads(claims_out.read_text())
        c1 = validation["claims"][0]
        assert c1["verdict"] == "supported", "Should use current verdict, not stale"

    def test_carryover_not_skipped(self, tmp_path):
        claims = [
            {"id": "c1", "text": "claim one", "file": "doc.adoc", "line": 1},
        ]
        (tmp_path / "claims-list.json").write_text(json.dumps(claims))

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # carryover verdict (from incremental_claims, no matching batch-claims)
        (output_dir / "batch-verdict-carryover.json").write_text(
            json.dumps([{"claim_id": "c1", "verdict": "supported", "evidence": "carried"}])
        )

        claims_out = tmp_path / "claim-validation.json"
        summary_out = tmp_path / "validation-summary.md"

        result = subprocess.run(
            [
                sys.executable, str(MERGE),
                "--claims-list", str(tmp_path / "claims-list.json"),
                "--output-dir", str(output_dir),
                "--claims-file", str(claims_out),
                "--summary-file", str(summary_out),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "Skipping stale" not in result.stderr

        validation = json.loads(claims_out.read_text())
        assert validation["claims"][0]["verdict"] == "supported"


# ---------------------------------------------------------------------------
# 2. incremental_claims: non-dict claim tolerance
# ---------------------------------------------------------------------------
class TestIncrementalClaimsNonDict:
    def test_non_dict_in_prior_claims_skipped(self, tmp_path):
        claims = [{"id": "c1", "text": "hello", "file": "doc.adoc"}]
        prior = {"claims": [
            {"file": "doc.adoc", "text": "hello", "verdict": "supported", "evidence": "ok"},
            "not-a-dict",
            42,
        ]}
        (tmp_path / "claims-list.json").write_text(json.dumps(claims))
        (tmp_path / "prior.json").write_text(json.dumps(prior))

        output_dir = tmp_path / "output"
        result = subprocess.run(
            [
                sys.executable, str(INCR),
                "--claims-list", str(tmp_path / "claims-list.json"),
                "--prior-validation", str(tmp_path / "prior.json"),
                "--output-dir", str(output_dir),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        counts = json.loads(result.stdout)
        assert counts["reused_count"] == 1

    def test_non_dict_in_fresh_claims_skipped(self, tmp_path):
        claims = [{"id": "c1", "text": "hello", "file": "doc.adoc"}, "bad-entry"]
        prior = {"claims": []}
        (tmp_path / "claims-list.json").write_text(json.dumps(claims))
        (tmp_path / "prior.json").write_text(json.dumps(prior))

        output_dir = tmp_path / "output"
        result = subprocess.run(
            [
                sys.executable, str(INCR),
                "--claims-list", str(tmp_path / "claims-list.json"),
                "--prior-validation", str(tmp_path / "prior.json"),
                "--output-dir", str(output_dir),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        counts = json.loads(result.stdout)
        assert counts["revalidate_count"] == 1


# ---------------------------------------------------------------------------
# 3. split_claims: non-dict claim rejection
# ---------------------------------------------------------------------------
class TestSplitClaimsNonDict:
    def test_non_dict_claim_rejected(self, tmp_path):
        claims = [{"id": "c1", "file": "doc.adoc", "text": "ok"}, "not-a-dict"]
        (tmp_path / "claims.json").write_text(json.dumps(claims))
        output_dir = tmp_path / "output"

        result = subprocess.run(
            [
                sys.executable, str(SPLIT),
                "--claims-list", str(tmp_path / "claims.json"),
                "--output-dir", str(output_dir),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "must be JSON objects" in result.stderr

    def test_all_dicts_succeeds(self, tmp_path):
        claims = [{"id": "c1", "file": "doc.adoc", "text": "ok"}]
        (tmp_path / "claims.json").write_text(json.dumps(claims))
        output_dir = tmp_path / "output"

        result = subprocess.run(
            [
                sys.executable, str(SPLIT),
                "--claims-list", str(tmp_path / "claims.json"),
                "--output-dir", str(output_dir),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# 4. quality_gate.classify_gaps: non-dict missed_items tolerance
# ---------------------------------------------------------------------------
class TestClassifyGapsNonDict:
    def test_non_dict_missed_item_skipped(self):
        sys.path.insert(0, str(QG.parent))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("quality_gate", QG)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            missed = [
                {"ac_item": "real gap", "id": "REQ-1"},
                "not-a-dict",
                42,
                None,
            ]
            gaps = mod.classify_gaps(missed, None)
            assert len(gaps) == 1
            assert gaps[0]["ac_item"] == "real gap"
        finally:
            sys.path.pop(0)


# ---------------------------------------------------------------------------
# 5. write_step_result: regex anchoring
# ---------------------------------------------------------------------------
class TestRegexAnchoring:
    def _load_regexes(self):
        sys.path.insert(0, str(WRITE_SR.parent))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("write_step_result", WRITE_SR)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.CONFIDENCE_RE, mod.SEVERITY_RE
        finally:
            sys.path.pop(0)

    def test_matches_plain_footer(self):
        conf_re, sev_re = self._load_regexes()
        text = (
            "Overall technical confidence: HIGH\n"
            "Severity counts: critical=1 significant=2 minor=3 sme=0"
        )
        assert conf_re.search(text).group(1) == "HIGH"
        m = sev_re.search(text)
        assert m and m.groups() == ("1", "2", "3", "0")

    def test_matches_bold_footer(self):
        conf_re, sev_re = self._load_regexes()
        text = (
            "**Overall technical confidence:** [MEDIUM]\n"
            "**Severity counts:** critical=0 significant=1 minor=0 sme=0"
        )
        assert conf_re.search(text).group(1) == "MEDIUM"
        m = sev_re.search(text)
        assert m and m.groups() == ("0", "1", "0", "0")

    def test_does_not_match_inline_example(self):
        conf_re, _ = self._load_regexes()
        text = "Example: Overall technical confidence: HIGH is the best rating"
        assert conf_re.search(text) is None, "Should not match when extra text follows on the line"

    def test_does_not_match_code_block_line(self):
        conf_re, _ = self._load_regexes()
        text = "    Overall technical confidence: HIGH  # in a code block"
        m = conf_re.search(text)
        # Leading whitespace is allowed (indented lines), but trailing text should not match
        assert m is None, "Should not match code-comment lines"

    def test_matches_with_leading_whitespace(self):
        conf_re, _ = self._load_regexes()
        text = "  Overall technical confidence: LOW"
        assert conf_re.search(text).group(1) == "LOW"

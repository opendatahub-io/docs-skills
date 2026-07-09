"""Tests for merge_verdicts.py expected-file derivation.

Regression coverage for the phantom carryover bug: on iteration 1 there is no
``batch-verdict-carryover.json`` (it is written by incremental_claims only on
iteration 2+), so it must not be reported as a missing verdict file nor inflate
the "expected" denominator.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "docs-workflow-tech-review" / "scripts" / "merge_verdicts.py"


def _run(tmp_path, output_dir):
    claims_list = tmp_path / "claims.json"
    claims_list.write_text(json.dumps([{"id": "c1", "text": "t", "file": "f", "line": 1}]))
    claims_file = tmp_path / "out-claims.json"
    summary_file = tmp_path / "out-summary.md"
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--claims-list",
            str(claims_list),
            "--output-dir",
            str(output_dir),
            "--claims-file",
            str(claims_file),
            "--summary-file",
            str(summary_file),
        ],
        capture_output=True,
        text=True,
    )


def _write_verdict(path, claim_id):
    path.write_text(json.dumps([{"claim_id": claim_id, "verdict": "supported", "evidence": "e"}]))


class TestMergeVerdictsExpectedFiles:
    def test_iteration_1_no_phantom_carryover(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "batch-claims-1.json").write_text(json.dumps([{"id": "c1"}]))
        _write_verdict(out / "batch-verdict-1.json", "c1")

        result = _run(tmp_path, out)

        assert result.returncode == 0, result.stderr
        # No phantom carryover reported as missing
        assert "batch-verdict-carryover.json" not in result.stderr
        assert "Missing verdict files" not in result.stderr
        # Denominator counts only the real batch, not the phantom carryover
        assert "Batch verdicts loaded: 1/1 expected" in result.stdout

    def test_iteration_2_carryover_expected_and_loaded(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "batch-claims-1.json").write_text(json.dumps([{"id": "c1"}]))
        _write_verdict(out / "batch-verdict-1.json", "c1")
        # Carryover present on iteration 2+
        _write_verdict(out / "batch-verdict-carryover.json", "c0")

        result = _run(tmp_path, out)

        assert result.returncode == 0, result.stderr
        assert "Missing verdict files" not in result.stderr
        assert "Batch verdicts loaded: 2/2 expected" in result.stdout

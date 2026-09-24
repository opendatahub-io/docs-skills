"""docs-plan --foundation: deliverables decided without a model call.

The gates are deterministic, so a default run spends nothing to decide what to
write. Every absence names its gate, because a maintainer reading a skip needs
to know whether to supply evidence or switch the gate off.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PLAN = _ROOT / "skills" / "docs-plan" / "scripts" / "plan.py"


def _artifacts(tmp_path, modules, edges=()):
    out = tmp_path / ".docs-gen"
    out.mkdir(parents=True)
    (out / "registry.json").write_text(json.dumps({"modules": modules}))
    (out / "dep-pairs.json").write_text(json.dumps({"pairs": list(edges)}))
    return out


def _run(out, repo, extra=()):
    return subprocess.run(
        [
            sys.executable,
            str(_PLAN),
            "--foundation",
            "--out",
            str(out),
            "--repo",
            str(repo),
            # `false` exits non-zero on every call, so a run reaching a model
            # fails loudly rather than passing this test by accident.
            "--llm-cmd",
            "false",
            *extra,
        ],
        capture_output=True,
        text=True,
    )


def test_a_foundation_run_spends_no_model_call(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {"kind": "library"}})
    done = _run(out, tmp_path)
    assert done.returncode == 0, done.stderr
    plan = json.loads((out / "plan.json").read_text())
    assert [item["path"] for item in plan["deliverables"]] == ["docs/README.md"]
    assert plan["deliverables"][0]["foundation"] == "readme"


def test_the_report_names_the_gate_behind_every_skip(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {"kind": "library"}})
    _run(out, tmp_path)
    report = json.loads((out / "foundation.json").read_text())
    gated = {entry["doc"]: entry["gate"] for entry in report["skipped"]}
    assert gated["docs/GET-STARTED.md"] == "no_entry_point"
    assert gated["docs/ARCHITECTURE.md"] == "graph_too_small"
    assert gated["docs/SECURITY.md"] == "no_security_surface"
    assert gated["docs/ROADMAP.md"] == "no_forward_marker"
    assert [entry["doc"] for entry in report["written"]] == ["docs/README.md"]


def test_every_document_skipped_is_exit_one(tmp_path):
    out = _artifacts(tmp_path, {})
    done = _run(out, tmp_path)
    assert done.returncode == 1, done.stderr
    report = json.loads((out / "foundation.json").read_text())
    assert report["written"] == []


def test_a_skip_flag_disables_a_document(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {"kind": "library"}})
    done = _run(out, tmp_path, ["--skip-doc", "readme"])
    assert done.returncode == 1, done.stderr
    report = json.loads((out / "foundation.json").read_text())
    assert any(entry["gate"] == "disabled" for entry in report["skipped"])


def test_an_unknown_skip_name_is_a_configuration_error(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {}})
    done = _run(out, tmp_path, ["--skip-doc", "raodmap"])
    assert done.returncode == 2, done.stdout
    assert "raodmap" in done.stderr

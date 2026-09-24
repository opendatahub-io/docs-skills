"""docs-plan: the foundation path reads what it uses and nothing else.

The selling point of the foundation set is that planning it costs nothing: no
model call, three committed artifacts read once. Building the per-module
evidence for a model call that is never made, then throwing it away, parsed
the whole grounding tier a second time on every run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs-plan" / "scripts"))

import plan  # noqa: E402
from lib.foundation import gates  # noqa: E402


def _artifacts(tmp_path, modules):
    out = tmp_path / ".docs-gen"
    (out / "modules").mkdir(parents=True)
    (out / "registry.json").write_text(json.dumps({"modules": modules}))
    (out / "dep-pairs.json").write_text(json.dumps({"pairs": []}))
    (out / "api-surface.json").write_text(json.dumps({"modules": {}}))
    return out


def test_a_foundation_run_never_builds_the_evidence_it_discards(tmp_path, monkeypatch):
    out = _artifacts(tmp_path, {"pkg/a": {"kind": "library"}})

    def fail(_out_dir):
        raise AssertionError("module_evidence ran on a foundation plan")

    monkeypatch.setattr(plan, "module_evidence", fail)
    code = plan.main(
        [
            "--repo",
            str(tmp_path),
            "--out",
            str(out),
            "--docs-dir",
            "docs",
            "--llm-cmd",
            "true",
            "--foundation",
        ]
    )
    assert code == 0
    assert (out / "plan.json").is_file()


def test_an_unknown_skip_name_is_still_a_configuration_error(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {"kind": "library"}})
    code = plan.main(
        [
            "--repo",
            str(tmp_path),
            "--out",
            str(out),
            "--docs-dir",
            "docs",
            "--llm-cmd",
            "true",
            "--foundation",
            "--skip-doc",
            "raodmap",
        ]
    )
    assert code == 2


def test_a_corrupt_registry_is_reported_once_in_one_wording(tmp_path):
    """The shape check lived in both the planner and the gates, with the same
    message in both, and two copies of a message drift."""
    out = tmp_path / ".docs-gen"
    out.mkdir()
    (out / "registry.json").write_text(json.dumps({"modules": ["pkg/a"]}))
    try:
        gates.registry_modules(out)
    except ValueError as exc:
        assert "must be an object keyed by module path" in str(exc)
    else:  # pragma: no cover - the check is the point of the test
        raise AssertionError("a list of modules was accepted")

    source = (_ROOT / "skills" / "docs-plan" / "scripts" / "plan.py").read_text()
    assert "must be an object keyed by module path" not in source

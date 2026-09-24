"""lib/foundation/gates: which of the five documents the evidence supports.

Nothing is scaffolded. A document this tool writes is grounded in extracted
evidence or it does not exist, and every absence names the gate behind it so a
maintainer can supply the evidence or switch the gate off.

The ROADMAP gate is the one most able to invent, so it takes only markers that
carry a commitment. A TODO comment is a note someone left themselves.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))

from lib.foundation import gates  # noqa: E402


def _artifacts(tmp_path, modules, edges=(), symbols=None):
    out = tmp_path / ".docs-gen"
    (out / "modules").mkdir(parents=True)
    (out / "registry.json").write_text(json.dumps({"modules": modules}))
    (out / "dep-pairs.json").write_text(json.dumps({"pairs": list(edges)}))
    (out / "api-surface.json").write_text(json.dumps({"modules": symbols or {}}))
    return out


def _stems(items, key):
    return sorted(entry[key].rsplit("/", 1)[-1] for entry in items)


def test_readme_writes_wherever_analysis_produced_anything(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {"kind": "library"}})
    written, _ = gates.evaluate(tmp_path, out, "docs")
    assert "README.md" in _stems(written, "path")


def test_get_started_needs_an_entry_point_and_a_manifest(tmp_path):
    out = _artifacts(tmp_path, {"cmd/x": {"kind": "cli"}})
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    assert {"GET-STARTED.md"} == {
        entry["doc"].rsplit("/", 1)[-1]
        for entry in skipped
        if entry["gate"] == "no_runnable_target"
    }

    (tmp_path / "Makefile").write_text("build: ## Compile\n\tgo build ./...\n")
    written, _ = gates.evaluate(tmp_path, out, "docs")
    assert "GET-STARTED.md" in _stems(written, "path")


def test_architecture_needs_three_modules_and_an_edge(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {}, "pkg/b": {}})
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    assert any(entry["gate"] == "graph_too_small" for entry in skipped)

    out = _artifacts(
        tmp_path / "big",
        {"pkg/a": {}, "pkg/b": {}, "pkg/c": {}},
        edges=[{"from": "pkg/a", "to": "pkg/b"}],
    )
    written, _ = gates.evaluate(tmp_path / "big", out, "docs")
    assert "ARCHITECTURE.md" in _stems(written, "path")


def test_security_needs_evidence_and_no_existing_policy(tmp_path):
    out = _artifacts(tmp_path, {"internal/tls": {"kind": "library"}})
    written, _ = gates.evaluate(tmp_path, out, "docs")
    assert "SECURITY.md" in _stems(written, "path")

    (tmp_path / "SECURITY.md").write_text("# Security policy\n")
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    assert any(entry["gate"] == "policy_exists" for entry in skipped)


def test_a_policy_in_any_location_github_reads_suppresses_security(tmp_path):
    out = _artifacts(tmp_path, {"internal/tls": {}})
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "security.md").write_text("# Policy\n")
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    assert any(entry["gate"] == "policy_exists" for entry in skipped)


def test_roadmap_accepts_a_deprecated_symbol(tmp_path):
    out = _artifacts(
        tmp_path,
        {"pkg/a": {}},
        symbols={"pkg/a": {"symbols": {"Old": {"doc": "Deprecated: use New instead."}}}},
    )
    written, _ = gates.evaluate(tmp_path, out, "docs")
    assert "ROADMAP.md" in _stems(written, "path")


def test_roadmap_accepts_an_alpha_api_version(tmp_path):
    out = _artifacts(tmp_path, {"apix/v1alpha2": {}})
    written, _ = gates.evaluate(tmp_path, out, "docs")
    assert "ROADMAP.md" in _stems(written, "path")


def test_roadmap_refuses_todo_comments_as_evidence(tmp_path):
    (tmp_path / "main.go").write_text("// TODO: rewrite this\n// FIXME: and this\n")
    out = _artifacts(tmp_path, {"pkg/a": {}})
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    assert any(entry["gate"] == "no_forward_marker" for entry in skipped)


def test_a_skipped_name_is_reported_as_configured(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {}})
    _, skipped = gates.evaluate(tmp_path, out, "docs", skip=("readme",))
    assert any(
        entry["gate"] == "disabled" and entry["doc"].endswith("README.md") for entry in skipped
    )


def test_an_unknown_skip_name_is_rejected(tmp_path):
    out = _artifacts(tmp_path, {"pkg/a": {}})
    try:
        gates.evaluate(tmp_path, out, "docs", skip=("raodmap",))
    except ValueError as exc:
        assert "raodmap" in str(exc)
    else:
        raise AssertionError("an unknown skip name must stop the run")

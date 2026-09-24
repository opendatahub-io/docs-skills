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


def test_tokens_split_acronym_runs_and_titlecase_boundaries():
    # A TitleCase boundary alone (AuthToken) is not the only shape a Go
    # identifier takes. An initialism run meeting a TitleCase word
    # (TLSConfig, RBACPolicy, JWTToken) is ordinary Go style, and it must
    # split into its own token rather than fusing with what follows.
    assert gates._tokens("TLSConfig") == ["tls", "config"]
    assert gates._tokens("RBACPolicy") == ["rbac", "policy"]
    assert gates._tokens("JWTToken") == ["jwt", "token"]
    assert gates._tokens("AuthToken") == ["auth", "token"]
    assert gates._tokens("auth_token") == ["auth", "token"]
    assert gates._tokens("my-auth-svc") == ["my", "auth", "svc"]
    assert gates._tokens("internal/tls") == ["internal", "tls"]
    assert gates._tokens("pkg/authz") == ["pkg", "authz"]
    # These merely contain a vocabulary word as a substring and must not
    # produce it as a separate token.
    assert gates._tokens("internal/authoring") == ["internal", "authoring"]
    assert gates._tokens("cmd/concert") == ["cmd", "concert"]
    assert gates._tokens("cmd/secretary") == ["cmd", "secretary"]


def test_security_gate_matches_every_true_positive_shape(tmp_path):
    for symbol in ("TLSConfig", "RBACPolicy", "JWTToken", "AuthToken"):
        out = _artifacts(
            tmp_path / symbol,
            {"pkg/a": {}},
            symbols={"pkg/a": {"symbols": {symbol: {"doc": ""}}}},
        )
        written, _ = gates.evaluate(tmp_path / symbol, out, "docs")
        assert "SECURITY.md" in _stems(written, "path"), symbol

    for module in ("internal/auth_token", "internal/AuthToken", "cmd/my-auth-svc"):
        out = _artifacts(tmp_path / module.replace("/", "_"), {module: {}})
        written, _ = gates.evaluate(tmp_path / module.replace("/", "_"), out, "docs")
        assert "SECURITY.md" in _stems(written, "path"), module

    out = _artifacts(tmp_path, {"internal/tls": {}, "pkg/authz": {}})
    written, _ = gates.evaluate(tmp_path, out, "docs")
    assert "SECURITY.md" in _stems(written, "path")


def test_security_gate_ignores_words_that_merely_contain_the_vocabulary(tmp_path):
    out = _artifacts(
        tmp_path,
        {"internal/authoring": {}, "cmd/concert": {}, "cmd/secretary": {}},
    )
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    assert any(
        entry["gate"] == "no_security_surface"
        for entry in skipped
        if entry["doc"].endswith("SECURITY.md")
    )


def test_roadmap_rationale_reflects_deprecations_from_every_module(tmp_path):
    out = _artifacts(
        tmp_path,
        {"pkg/a": {}, "pkg/b": {}},
        symbols={
            "pkg/a": {"symbols": {"Old": {"doc": "Deprecated: use New instead."}}},
            "pkg/b": {"symbols": {"Older": {"doc": "Deprecated: use Newer instead."}}},
        },
    )
    written, _ = gates.evaluate(tmp_path, out, "docs")
    roadmap = next(entry for entry in written if entry["path"].endswith("ROADMAP.md"))
    assert "pkg/a" in roadmap["rationale"]
    assert "pkg/b" in roadmap["rationale"]


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


def test_the_fixture_repository_passes_four_of_five_gates(tmp_path):
    """Every gate that can pass, against a repository that actually exists.

    SECURITY is the one that cannot: the fixture carries a policy file, which
    is the case llm-d-router demonstrated and the one most likely to regress,
    because the evidence half of that gate passes and only the suppression
    stops it.
    """
    import subprocess

    script = _ROOT / "tests" / "fixtures" / "make_python_fixture.sh"
    built = tmp_path / "repo"
    subprocess.run(["bash", str(script), str(built)], check=True, capture_output=True)

    written, skipped = gates.evaluate(built, built / ".docs-gen", "docs")

    assert sorted(item["path"].rsplit("/", 1)[-1] for item in written) == [
        "ARCHITECTURE.md",
        "GET-STARTED.md",
        "README.md",
        "ROADMAP.md",
    ]
    assert [entry["gate"] for entry in skipped] == ["policy_exists"]

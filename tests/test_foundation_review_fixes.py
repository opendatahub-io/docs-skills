"""Regressions in the foundation chain that a full test suite still passed.

Each test here stands for a run that produced no error and the wrong result:
a document that gated itself off on its second run, a sources list that grew
with the repository, a manifest shape that killed the writer, and an
allowlist that flagged the commands its own gate had opened on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))

from lib.foundation import commands, evidence, gates  # noqa: E402


def _artifacts(tmp_path, modules, edges=(), symbols=None):
    out = tmp_path / ".docs-gen"
    (out / "modules").mkdir(parents=True)
    (out / "registry.json").write_text(json.dumps({"modules": modules}))
    (out / "dep-pairs.json").write_text(json.dumps({"pairs": list(edges)}))
    (out / "api-surface.json").write_text(json.dumps({"modules": symbols or {}}))
    return out


def _paths(items):
    return {entry["path"] for entry in items}


def _gate_for(skipped, name):
    return next((entry["gate"] for entry in skipped if entry["doc"].endswith(name)), "")


# --------------------------------------------------------- the policy it owns


def test_the_security_document_does_not_gate_itself_off_on_the_second_run(tmp_path):
    """`docs/SECURITY.md` is both where GitHub reads a policy and where this
    writer puts one. Reading its own output as somebody else's policy skipped
    the page forever, and review then called it an orphan to delete."""
    out = _artifacts(tmp_path, {"internal/tls": {"kind": "library"}})
    written, _ = gates.evaluate(tmp_path, out, "docs")
    assert "docs/SECURITY.md" in _paths(written)

    target = tmp_path / "docs" / "SECURITY.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "---\ntitle: Security\nmanaged: generated\nfoundation: security\n---\n\nbody\n"
    )
    written, skipped = gates.evaluate(tmp_path, out, "docs")
    assert "docs/SECURITY.md" in _paths(written), _gate_for(skipped, "SECURITY.md")


def test_a_policy_somebody_else_wrote_still_gates_the_document(tmp_path):
    out = _artifacts(tmp_path, {"internal/tls": {"kind": "library"}})
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "SECURITY.md").write_text("report issues to security@example.com\n")
    _, skipped = gates.evaluate(tmp_path, out, "docs")
    assert _gate_for(skipped, "SECURITY.md") == "policy_exists"


# ------------------------------------------------------------- capped sources


def test_a_document_cites_a_bounded_number_of_modules(tmp_path):
    """`source_modules` ships in the page and `docs_meta.stale()` joins it, so
    an uncapped list both grew the page with the repository and re-queued the
    whole foundation set on any single-module change."""
    modules = {f"pkg/m{index:03d}": {"kind": "library"} for index in range(300)}
    edges = [{"from": "pkg/m000", "to": "pkg/m001"}]
    out = _artifacts(tmp_path, modules, edges)
    written, _ = gates.evaluate(tmp_path, out, "docs")
    for entry in written:
        assert len(entry["sources"]) <= gates.SOURCE_CAP, entry["path"]


def test_the_payload_cap_and_the_source_cap_are_one_number():
    assert evidence.MODULE_CAP == gates.SOURCE_CAP


def test_the_most_depended_on_modules_survive_the_cap(tmp_path):
    modules = {f"pkg/m{index:03d}": {"kind": "library"} for index in range(300)}
    edges = [{"from": f"pkg/m{index:03d}", "to": "pkg/m299"} for index in range(50)]
    out = _artifacts(tmp_path, modules, edges)
    written, _ = gates.evaluate(tmp_path, out, "docs")
    readme = next(entry for entry in written if entry["path"].endswith("README.md"))
    assert "pkg/m299" in readme["sources"]


# --------------------------------------------- manifests this tool did not write


def test_a_string_engines_field_does_not_kill_the_writer(tmp_path):
    """`run_plan` catches OSError, ValueError, RuntimeError and KeyError. An
    AttributeError out of here escaped it, so the process died before
    `write-report.json` existed and the caller then failed reading it."""
    (tmp_path / "package.json").write_text(json.dumps({"engines": "node"}))
    assert evidence._prerequisites(tmp_path) == {}


def test_a_package_json_that_is_an_array_does_not_kill_the_writer(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps([{"engines": {"node": ">=18"}}]))
    assert evidence._prerequisites(tmp_path) == {}


def test_a_well_formed_engines_block_is_still_read(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"engines": {"node": ">=18"}}))
    assert evidence._prerequisites(tmp_path) == {"node": ">=18"}


# ----------------------------------------------------------------- allowlist


def test_a_docker_only_repository_gets_an_allowlist(tmp_path):
    """`has_manifest` counts a Dockerfile, so the gate opens on one. An
    allowlist that contributed nothing for it handed the writer an empty list
    beside the rule that every command must come from it."""
    (tmp_path / "Dockerfile").write_text('FROM python:3.12\nCMD ["serve"]\n')
    declared = commands.declared_commands(tmp_path)
    assert commands.has_manifest(tmp_path)
    assert commands.allowlist(declared) >= {"docker build", "docker run"}


def test_a_repository_with_no_dockerfile_allows_no_docker_command(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\techo hi\n")
    assert "docker build" not in commands.allowlist(commands.declared_commands(tmp_path))


def test_a_makefile_allows_the_bare_default_target(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\techo hi\n")
    allowed = commands.allowlist(commands.declared_commands(tmp_path))
    assert {"make", "make build"} <= allowed


def test_package_scripts_allow_installing_them(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"dev": "vite"}}))
    allowed = commands.allowlist(commands.declared_commands(tmp_path))
    assert {"npm install", "npm ci", "npm run dev"} <= allowed


def test_an_interpreter_needs_no_manifest():
    """A tutorial runs interpreters and pipes output through utilities. No
    manifest declares those, and flagging them left correct pages failing."""
    assert {"python3", "pip", "node", "go", "grep", "tee", "sed"} <= commands.BUILTINS


def test_a_runner_taking_a_declared_target_is_not_a_builtin():
    """Otherwise `make deploy` passes without the Makefile having that target,
    which is the whole check."""
    assert not {"make", "npm"} & commands.BUILTINS

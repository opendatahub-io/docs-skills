"""Cross-platform plugin packaging tests."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import check_runtime_compatibility, sync_plugin_manifests

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_generated_manifests_are_current():
    assert sync_plugin_manifests.sync(REPO_ROOT, check=True) == []


def test_platform_manifests_share_identity_and_version():
    claude = json.loads((REPO_ROOT / ".claude-plugin/plugin.json").read_text())
    codex = json.loads((REPO_ROOT / ".codex-plugin/plugin.json").read_text())

    assert claude["name"] == codex["name"] == "docs-skills"
    assert claude["version"] == codex["version"]


def test_marketplaces_reference_the_repository_root():
    claude = json.loads((REPO_ROOT / ".claude-plugin/marketplace.json").read_text())
    codex = json.loads((REPO_ROOT / ".agents/plugins/marketplace.json").read_text())

    assert claude["plugins"][0]["source"] == "."
    assert codex["plugins"][0]["source"] == {"source": "local", "path": "."}


def test_platform_specific_skills_link_runtime_guidance():
    assert check_runtime_compatibility.process(REPO_ROOT / "skills", fix=False) == []


def test_shared_runtime_files_use_neutral_paths():
    assert check_runtime_compatibility.find_legacy_path_references(REPO_ROOT) == []

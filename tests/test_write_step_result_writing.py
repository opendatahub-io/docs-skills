"""Tests for the writing-specific write_step_result.py iteration tracking."""

import json
import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(__file__), "..", "skills", "docs-workflow-writing", "scripts"
    ),
)

from write_step_result import main


def _make_manifest(tmp_path, files=None):
    """Create a minimal _index.md manifest."""
    manifest = tmp_path / "writing" / "_index.md"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    if files:
        lines = ["| File | Status |", "| --- | --- |"]
        for f in files:
            lines.append(f"| {f} | new |")
        manifest.write_text("\n".join(lines))
    else:
        manifest.write_text("# Index\n\nNo files.\n")
    return str(manifest)


class TestIterationField:
    def test_default_iteration_is_1(self, tmp_path, monkeypatch):
        manifest = _make_manifest(tmp_path)
        sidecar = str(tmp_path / "writing" / "step-result.json")
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--ticket", "T-1", "--manifest", manifest,
             "--mode", "update-in-place", "--format", "adoc", "--sidecar", sidecar],
        )
        main()
        data = json.loads(open(sidecar).read())
        assert data["iteration"] == 1

    def test_explicit_iteration_arg(self, tmp_path, monkeypatch):
        manifest = _make_manifest(tmp_path)
        sidecar = str(tmp_path / "writing" / "step-result.json")
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--ticket", "T-1", "--manifest", manifest,
             "--mode", "update-in-place", "--format", "adoc", "--sidecar", sidecar,
             "--iteration", "3"],
        )
        main()
        data = json.loads(open(sidecar).read())
        assert data["iteration"] == 3

    def test_fix_mode_auto_increments_from_prior(self, tmp_path, monkeypatch):
        manifest = _make_manifest(tmp_path)
        sidecar_path = tmp_path / "writing" / "step-result.json"
        # Write a prior sidecar with iteration 1
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps({
            "schema_version": 1, "step": "writing", "ticket": "T-1",
            "completed_at": "2020-01-01T00:00:00+00:00",
            "files": [], "mode": "update-in-place", "format": "adoc",
            "iteration": 1,
        }))
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--ticket", "T-1", "--manifest", manifest,
             "--mode", "fix", "--format", "adoc", "--sidecar", str(sidecar_path)],
        )
        main()
        data = json.loads(sidecar_path.read_text())
        assert data["iteration"] == 2
        assert data["mode"] == "update-in-place"  # carried forward

    def test_fix_mode_no_prior_defaults_to_2(self, tmp_path, monkeypatch):
        manifest = _make_manifest(tmp_path)
        sidecar = str(tmp_path / "writing" / "step-result.json")
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--ticket", "T-1", "--manifest", manifest,
             "--mode", "fix", "--format", "adoc", "--sidecar", sidecar],
        )
        main()
        data = json.loads(open(sidecar).read())
        assert data["iteration"] == 2

    def test_fix_mode_explicit_iteration_overrides_auto(self, tmp_path, monkeypatch):
        manifest = _make_manifest(tmp_path)
        sidecar_path = tmp_path / "writing" / "step-result.json"
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps({
            "schema_version": 1, "step": "writing", "ticket": "T-1",
            "completed_at": "2020-01-01T00:00:00+00:00",
            "files": [], "mode": "update-in-place", "format": "adoc",
            "iteration": 1,
        }))
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--ticket", "T-1", "--manifest", manifest,
             "--mode", "fix", "--format", "adoc", "--sidecar", str(sidecar_path),
             "--iteration", "5"],
        )
        main()
        data = json.loads(sidecar_path.read_text())
        assert data["iteration"] == 5

"""docs: a configuration error reaches the caller as one.

The exit table in SKILL.md is the contract a CI job branches on. A typo in
`.docs-gen.yaml` that arrives as "a step failed" sends someone reading logs
for a failure that never happened.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs" / "scripts"))

import build  # noqa: E402
import pytest  # noqa: E402


def test_the_skill_documents_the_configuration_code():
    table = (_ROOT / "skills" / "docs" / "SKILL.md").read_text()
    assert "| 2 | Configuration error |" in table


def test_a_template_with_no_packages_line_is_a_configuration_error(tmp_path):
    """`seed_vale_config` read the template with `next` and `index`, which
    raised StopIteration and ValueError past the caller's own guard, and only
    on the second run in a repository where `.vale.ini` already exists."""
    template = tmp_path / "docs.ini"
    template.write_text("StylesPath = ../styles\n\n[*.md]\nBasedOnStyles = X\n")
    target = tmp_path / ".vale.ini"
    target.write_text("StylesPath = elsewhere\n")
    with pytest.raises(ValueError):
        build.seed_vale_config(template, target, tmp_path / "styles")


def test_a_template_with_no_markdown_section_is_a_configuration_error(tmp_path):
    template = tmp_path / "docs.ini"
    template.write_text("StylesPath = ../styles\nPackages = RedHat\n")
    target = tmp_path / ".vale.ini"
    target.write_text("StylesPath = elsewhere\n")
    with pytest.raises(ValueError):
        build.seed_vale_config(template, target, tmp_path / "styles")


def test_the_caller_reports_it_rather_than_raising(tmp_path, monkeypatch):
    template = tmp_path / "vale" / "docs.ini"
    template.parent.mkdir(parents=True)
    template.write_text("StylesPath = ../styles\n\n[*.md]\nBasedOnStyles = X\n")
    monkeypatch.setattr(build, "PACKAGE_ROOT", tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".vale.ini").write_text("StylesPath = elsewhere\n")
    assert build.sync_styles(tmp_path / ".docs-gen", repo) == 2


def test_a_well_formed_template_still_seeds(tmp_path):
    template = tmp_path / "docs.ini"
    template.write_text("StylesPath = ../styles\nPackages = RedHat\n\n[*.md]\nBasedOnStyles = X\n")
    target = tmp_path / ".vale.ini"
    target.write_text("StylesPath = elsewhere\n")
    build.seed_vale_config(template, target, tmp_path / "styles")
    text = target.read_text()
    assert "Packages = RedHat" in text
    assert "[*.md]" in text

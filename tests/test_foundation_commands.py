"""lib/foundation/commands: what a repository declares you may run.

A tutorial whose commands fail is worse than no tutorial, so the commands are
not the model's to choose. Only what a manifest declares reaches the writer,
and only what the manifest declares passes review.

A Makefile is mostly not targets. Variable assignments, pattern rules,
`.PHONY` and `include` all match a naive `^word:` and none of them is
something a reader can run.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))

from lib.foundation import commands  # noqa: E402


def test_make_targets_carry_their_help_text(tmp_path):
    (tmp_path / "Makefile").write_text(
        "build: ## Compile the binary\n\tgo build ./...\ntest: ## Run the suite\n\tgo test ./...\n"
    )
    found = commands.declared_commands(tmp_path)
    assert found["make"] == [
        {"target": "build", "help": "Compile the binary"},
        {"target": "test", "help": "Run the suite"},
    ]


def test_a_makefile_line_that_is_not_a_target_is_not_a_command(tmp_path):
    (tmp_path / "Makefile").write_text(
        ".PHONY: build test\n"
        "CC := gcc\n"
        "VERSION = 1.2.3\n"
        "include common.mk\n"
        "%.o: %.c\n\t$(CC) -c $<\n"
        "build: ## Compile\n\tgo build ./...\n"
    )
    found = commands.declared_commands(tmp_path)
    assert [entry["target"] for entry in found["make"]] == ["build"]


def test_package_scripts_and_project_scripts_are_commands(tmp_path):
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "vite", "lint": "eslint ."}}')
    (tmp_path / "pyproject.toml").write_text('[project.scripts]\nmytool = "pkg.cli:main"\n')
    found = commands.declared_commands(tmp_path)
    assert found["npm"] == ["dev", "lint"]
    assert found["python"] == ["mytool"]


def test_the_allowlist_is_full_command_strings(tmp_path):
    (tmp_path / "Makefile").write_text("build: ## Compile\n\tgo build ./...\n")
    (tmp_path / "package.json").write_text('{"scripts": {"dev": "vite"}}')
    allowed = commands.allowlist(commands.declared_commands(tmp_path))
    assert "make build" in allowed
    assert "npm run dev" in allowed


def test_a_repository_declaring_nothing_yields_an_empty_allowlist(tmp_path):
    assert commands.allowlist(commands.declared_commands(tmp_path)) == set()


def test_has_manifest_answers_the_get_started_gate(tmp_path):
    """The GET-STARTED gate asks whether anything is runnable at all.

    A Dockerfile entrypoint counts even though it contributes no allowlist
    entry, because it means the repository can be started.
    """
    assert commands.has_manifest(tmp_path) is False
    (tmp_path / "Dockerfile").write_text('FROM alpine\nENTRYPOINT ["/bin/app"]\n')
    assert commands.has_manifest(tmp_path) is True

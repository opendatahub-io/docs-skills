"""`build.py`, the chain's entry point, reached the way the extension reaches it.

There was an installed Python command in front of this, and the two front ends
resolved a different model per step and rendered their output differently. One
of them had to go. What these tests cover is the part that was never the
duplicate: seeding a repository's Vale config, and the step list the README
documents.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).parents[1]
BUILD = ROOT / "skills" / "docs" / "scripts" / "build.py"


def load_build():
    """Import `build.py` by path, which is how it is run."""
    spec = importlib.util.spec_from_file_location("docs_orc_build", BUILD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_build_entry_point_is_where_the_extension_looks():
    """`extensions/docs.ts` joins this path. A move breaks the command."""
    assert BUILD.is_file()
    joined = (ROOT / "extensions" / "docs.ts").read_text()
    assert '"skills", "docs", "scripts", "build.py"' in joined.replace("\n", "").replace(
        "  ", ""
    )


def test_help_comes_from_the_existing_parser(capsys):
    build = load_build()
    with pytest.raises(SystemExit) as stopped:
        build.main(["--help"])
    assert stopped.value.code == 0
    output = capsys.readouterr().out
    assert "Document a code repository" in output
    assert "--sync-styles" in output


def test_style_sync_writes_packages_and_default_config(tmp_path, monkeypatch):
    build = load_build()
    calls = []

    def run(argv):
        calls.append((argv, Path(argv[2]).read_text()))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        build.subprocess,
        "run",
        run,
    )
    repo = tmp_path / "docs"
    out_dir = repo / ".docs-gen"
    assert build.sync_styles(out_dir, repo) == 0

    config = out_dir / "vale-sync.ini"
    assert calls[0][0] == ["vale", "--config", str(config), "sync"]
    text = calls[0][1]
    assert f"StylesPath = {out_dir / 'vale-packages'}" in text
    assert "Packages = RedHat, Std" in text
    assert "BasedOnStyles" not in text
    assert not config.exists()
    project_config = (repo / ".vale.ini").read_text()
    assert "StylesPath = .docs-gen/vale-packages" in project_config
    assert "Packages = RedHat, Std" in project_config


def test_console_style_sync_initializes_an_empty_repository(tmp_path, monkeypatch):
    build = load_build()
    calls = []
    monkeypatch.setattr(
        build.subprocess,
        "run",
        lambda argv: calls.append(argv) or SimpleNamespace(returncode=0),
    )
    repo = tmp_path / "empty"

    assert build.main(["--repo", str(repo), "--sync-styles"]) == 0

    out_dir = repo / ".docs-gen"
    assert repo.is_dir()
    assert (repo / ".vale.ini").is_file()
    assert (out_dir / "vale-packages").is_dir()
    assert not (out_dir / "vale-sync.ini").exists()
    assert calls == [["vale", "--config", str(out_dir / "vale-sync.ini"), "sync"]]

def test_console_does_not_build_when_style_sync_fails(tmp_path, monkeypatch):
    build = load_build()
    monkeypatch.setattr(build, "sync_styles", lambda out_dir, repo: 2)
    monkeypatch.setattr(
        build,
        "build",
        lambda *args: pytest.fail("the build must not run after a failed style sync"),
    )

    assert build.main(["--repo", str(tmp_path), "--topic", "queues", "--sync-styles"]) == 2


def test_style_sync_removes_temporary_config_when_vale_is_missing(tmp_path, monkeypatch):
    build = load_build()

    def missing(_argv):
        raise FileNotFoundError

    monkeypatch.setattr(build.subprocess, "run", missing)
    out_dir = tmp_path / "docs" / ".docs-gen"

    assert build.sync_styles(out_dir) == 2
    assert not (out_dir / "vale-sync.ini").exists()


def test_style_sync_appends_defaults_to_an_existing_repository_config(tmp_path, monkeypatch):
    build = load_build()
    monkeypatch.setattr(
        build.subprocess,
        "run",
        lambda argv: SimpleNamespace(returncode=0),
    )
    repo = tmp_path / "docs"
    repo.mkdir()
    config = repo / ".vale.ini"
    config.write_text("existing config\n")

    assert build.sync_styles(repo / ".docs-gen", repo) == 0
    # Taken from the template rather than restated, so a rule added there is
    # a rule this test proves reaches the repository that syncs.
    template = (ROOT / "vale" / "docs.ini").read_text()
    markdown_block = template[template.index("[*.md]") :].strip()
    packages = next(line for line in template.splitlines() if line.startswith("Packages ="))
    expected = f"existing config\n\n{packages}\n\n{markdown_block}\n"
    assert config.read_text() == expected
    assert "RedHat.Headings = error" in config.read_text()
    assert "RedHat.NoGerundsInTitles = error" in config.read_text()

    assert build.sync_styles(repo / ".docs-gen", repo) == 0
    assert config.read_text() == expected


def test_the_readme_help_block_matches_the_parser():
    """The README prints `--help`. A drifted flag description is a wrong README.

    Pinned to 80 columns because argparse wraps to the terminal it finds, and
    the block in the README was written at that width.
    """
    env = {**os.environ, "COLUMNS": "80"}
    printed = subprocess.run(
        [sys.executable, str(BUILD), "--help"], capture_output=True, text=True, env=env
    ).stdout
    options = printed[printed.index("options:") :].rstrip("\n")
    readme = (ROOT / "README.md").read_text()
    assert options in readme, (
        f"README.md no longer prints what build.py prints. Regenerate the block:\n{options}"
    )

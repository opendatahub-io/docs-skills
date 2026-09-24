"""The command line the pi extension depends on.

The extension is nine lines of glue over `check.main`. What has to hold is the
contract between them: exit 0 and no output when clean, exit 1 and the
instruction when dirty, exit 2 and nothing on stdout when Vale cannot run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CHECK = _REPO_ROOT / "skills" / "docs-engine" / "scripts" / "lib" / "vale" / "check.py"


def run_check(args):
    return subprocess.run([sys.executable, str(_CHECK), *args], capture_output=True, text=True)


def scratch(tmp_path):
    style = tmp_path / "styles" / "Probe"
    style.mkdir(parents=True)
    (style / "Banned.yml").write_text(
        "extends: existence\nmessage: \"Banned: '%s'\"\nlevel: error\ntokens: ['utilize']\n"
    )
    config = tmp_path / "vale.ini"
    config.write_text(
        f"StylesPath = {tmp_path / 'styles'}\n"
        "MinAlertLevel = error\n"
        "\n"
        "[*.md]\n"
        "BasedOnStyles = Probe\n"
    )
    return config


def test_clean_file_exits_zero_and_says_nothing(tmp_path):
    config = scratch(tmp_path)
    page = tmp_path / "clean.md"
    page.write_text("We use a thing.\n")
    result = run_check([str(page), "--config", str(config)])
    assert result.returncode == 0
    assert result.stdout == ""


def test_dirty_file_exits_one_with_the_instruction(tmp_path):
    config = scratch(tmp_path)
    page = tmp_path / "dirty.md"
    page.write_text("We utilize a thing.\n")
    result = run_check([str(page), "--config", str(config)])
    assert result.returncode == 1
    assert "Probe.Banned" in result.stdout
    assert "Do not disable a rule to clear one." in result.stdout


def test_unusable_config_exits_two_with_a_clean_stdout(tmp_path):
    # The extension stays silent on this. A gate that reports its own problems
    # trains people to switch it off.
    page = tmp_path / "page.md"
    page.write_text("Text.\n")
    result = run_check([str(page), "--config", str(tmp_path / "missing.ini")])
    assert result.returncode == 2
    assert result.stdout == ""


def test_warning_level_is_opt_in(tmp_path):
    style = tmp_path / "styles" / "Probe"
    style.mkdir(parents=True)
    (style / "Soft.yml").write_text(
        "extends: existence\nmessage: 'Soft'\nlevel: warning\ntokens: ['utilize']\n"
    )
    config = tmp_path / "vale.ini"
    config.write_text(
        f"StylesPath = {tmp_path / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n[*.md]\nBasedOnStyles = Probe\n"
    )
    page = tmp_path / "page.md"
    page.write_text("We utilize a thing.\n")

    assert run_check([str(page), "--config", str(config)]).returncode == 0
    louder = run_check([str(page), "--config", str(config), "--level", "warning"])
    assert louder.returncode == 1
    assert "Treat warnings and suggestions as advice." in louder.stdout


# ------------------------------------------------------- the scoped edit path


def swap_config(tmp_path):
    """A rule carrying `action: replace`, so `--fix` has something to apply."""
    style = tmp_path / "styles" / "Swap"
    style.mkdir(parents=True)
    (style / "Terms.yml").write_text(
        "extends: substitution\n"
        "message: \"Use '%s' rather than '%s'.\"\n"
        "level: error\n"
        "ignorecase: true\n"
        "action:\n"
        "  name: replace\n"
        "swap:\n"
        "  utilize: use\n"
    )
    config = tmp_path / "vale.ini"
    config.write_text(
        f"StylesPath = {tmp_path / 'styles'}\n"
        "MinAlertLevel = error\n\n[*.md]\nBasedOnStyles = Swap\n"
    )
    return config


PARAGRAPHS = "We utilize one thing.\n\nWe utilize another thing.\n\nWe utilize a third.\n"


def test_a_range_confines_the_report_to_its_own_block(tmp_path):
    """The point of the whole exercise: an edit answers for what it changed."""
    config = swap_config(tmp_path)
    page = tmp_path / "page.md"
    page.write_text(PARAGRAPHS)
    result = run_check([str(page), "--config", str(config), "--range", "3-3"])
    assert result.returncode == 1
    assert "line 3:" in result.stdout
    assert "line 1:" not in result.stdout
    assert "line 5:" not in result.stdout
    assert "in the lines just changed in" in result.stdout


def test_no_range_still_reports_the_whole_file(tmp_path):
    config = swap_config(tmp_path)
    page = tmp_path / "page.md"
    page.write_text(PARAGRAPHS)
    result = run_check([str(page), "--config", str(config)])
    assert result.returncode == 1
    for line in ("line 1:", "line 3:", "line 5:"):
        assert line in result.stdout
    assert "in the lines just changed in" not in result.stdout


def test_a_range_widens_to_the_paragraph_it_landed_in(tmp_path):
    """Vale reports a wrapped sentence against the line it starts on, which is
    above the line an edit changed. Scoping to changed lines alone loses it."""
    config = swap_config(tmp_path)
    page = tmp_path / "page.md"
    page.write_text("We utilize one thing\nand it carries on here.\n\nWe utilize another.\n")
    result = run_check([str(page), "--config", str(config), "--range", "2-2"])
    assert result.returncode == 1
    assert "line 1:" in result.stdout
    assert "line 4:" not in result.stdout


def test_a_clean_range_in_a_dirty_file_says_nothing(tmp_path):
    config = swap_config(tmp_path)
    page = tmp_path / "page.md"
    page.write_text("A clean opening line.\n\nWe utilize another thing.\n")
    result = run_check([str(page), "--config", str(config), "--range", "1-1"])
    assert result.returncode == 0
    assert result.stdout == ""


def test_the_fix_stays_inside_the_range(tmp_path):
    """A gate whose blast radius outruns the edit rewrites untouched paragraphs."""
    config = swap_config(tmp_path)
    page = tmp_path / "page.md"
    page.write_text(PARAGRAPHS)
    result = run_check([str(page), "--config", str(config), "--range", "3-3", "--fix"])
    assert result.returncode == 0
    assert "applied 1 exact replacement(s)" in result.stdout
    assert (
        page.read_text()
        == "We utilize one thing.\n\nWe use another thing.\n\nWe utilize a third.\n"
    )


def test_several_ranges_are_allowed(tmp_path):
    config = swap_config(tmp_path)
    page = tmp_path / "page.md"
    page.write_text(PARAGRAPHS)
    result = run_check([str(page), "--config", str(config), "--range", "1-1", "--range", "5-5"])
    assert result.returncode == 1
    assert "line 1:" in result.stdout
    assert "line 5:" in result.stdout
    assert "line 3:" not in result.stdout


def test_a_malformed_range_is_refused_without_touching_stdout(tmp_path):
    config = swap_config(tmp_path)
    page = tmp_path / "page.md"
    page.write_text(PARAGRAPHS)
    result = run_check([str(page), "--config", str(config), "--range", "9-2"])
    assert result.returncode == 2
    assert result.stdout == ""

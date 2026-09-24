"""Applying the fixes a rule already carries, rather than paying a model for them.

A `substitution` rule with one right answer ships that answer in the alert.
Every one of those applied here is a model call the repair loop does not make,
so the cases that matter are the ones where a blind splice would be wrong:
capitalization, two fixes on one line, and a span that has moved.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "docs-engine" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lib.vale import check  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("vale") is None, reason="vale is not installed")

CHECK = SCRIPTS / "lib" / "vale" / "check.py"


def swap_config(tmp_path):
    """One substitution rule carrying `action: replace`, and one that does not."""
    swap = tmp_path / "styles" / "Swap"
    swap.mkdir(parents=True)
    (swap / "Terms.yml").write_text(
        "extends: substitution\n"
        "message: \"Use '%s' rather than '%s'.\"\n"
        "level: error\n"
        "ignorecase: true\n"
        "action:\n"
        "  name: replace\n"
        "swap:\n"
        "  utilise: use\n"
        "  leverage: use\n"
        "  robust: strong\n"
    )
    plain = tmp_path / "styles" / "Plain"
    plain.mkdir(parents=True)
    (plain / "Banned.yml").write_text(
        "extends: existence\n"
        "message: \"Inflated word: '%s'. Say the plain thing.\"\n"
        "level: error\n"
        "ignorecase: true\n"
        "tokens: ['delve']\n"
    )
    config = tmp_path / "config.ini"
    config.write_text(
        f"StylesPath = {tmp_path / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n"
        "[*.md]\nBasedOnStyles = Swap, Plain\n"
    )
    return config


def lint(config, doc):
    return check.run(config, [doc])


# ------------------------------------------------------------------ the splice


def test_an_exact_replacement_is_applied(tmp_path):
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("We utilise the thing.\n")

    applied = check.apply_fixes(doc, lint(config, doc))

    assert [a.match for a in applied] == ["utilise"]
    assert doc.read_text() == "We use the thing.\n"
    assert lint(config, doc) == []


def test_the_replacement_keeps_the_sentence_capitalized(tmp_path):
    """The swap tables are lower case. Opening a sentence in lower case is not a fix."""
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("Utilise the thing.\n")

    check.apply_fixes(doc, lint(config, doc))

    assert doc.read_text() == "Use the thing.\n"


def test_an_all_caps_match_stays_all_caps(tmp_path):
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("Do not UTILISE it.\n")

    check.apply_fixes(doc, lint(config, doc))

    assert doc.read_text() == "Do not USE it.\n"


def test_two_fixes_on_one_line_both_land(tmp_path):
    """Applied left to right, the first splice invalidates the second's offsets."""
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("We utilise a robust thing.\n")

    applied = check.apply_fixes(doc, lint(config, doc))

    assert len(applied) == 2
    assert doc.read_text() == "We use a strong thing.\n"


def test_fixes_across_lines_all_land(tmp_path):
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("We utilise it.\n\nIt is robust.\n")

    check.apply_fixes(doc, lint(config, doc))

    assert doc.read_text() == "We use it.\n\nIt is strong.\n"


def test_trailing_newline_survives(tmp_path):
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("We utilise it.\n")

    check.apply_fixes(doc, lint(config, doc))

    assert doc.read_text().endswith("it.\n")


# ------------------------------------------------------------- what is left alone


def test_a_rule_with_no_action_is_left_for_the_model(tmp_path):
    """`delve` needs a rewrite, and a fix applied without thought would be worse."""
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("Let us delve into it.\n")

    applied = check.apply_fixes(doc, lint(config, doc))

    assert applied == []
    assert doc.read_text() == "Let us delve into it.\n"


def test_a_stale_span_is_skipped(tmp_path):
    """An alert against text that has since moved must not splice the line it hits."""
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("We utilise the thing.\n")
    alerts = lint(config, doc)
    doc.write_text("Something else entirely.\n")

    applied = check.apply_fixes(doc, alerts)

    assert applied == []
    assert doc.read_text() == "Something else entirely.\n"


def test_an_alert_past_the_end_of_the_file_is_skipped(tmp_path):
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("We utilise the thing.\n")
    alerts = lint(config, doc)
    doc.write_text("Short.\n")

    assert check.apply_fixes(doc, alerts) == []


def test_replacement_reads_only_a_single_parameter_replace():
    kind = check.Alert("a.md", 1, (1, 2), "A.B", "error", "m", "x")
    assert check.replacement(kind) is None
    assert check.replacement(_with(kind, {"name": "suggest", "params": ["y"]})) is None
    assert check.replacement(_with(kind, {"name": "replace", "params": []})) is None
    assert check.replacement(_with(kind, {"name": "replace", "params": ["y", "z"]})) is None
    assert check.replacement(_with(kind, {"name": "replace", "params": ["y"]})) == "y"


def _with(alert, action):
    return check.Alert(
        alert.file,
        alert.line,
        alert.span,
        alert.check,
        alert.severity,
        alert.message,
        alert.match,
        action,
    )


# ---------------------------------------------------------------------- the cli


def run_cli(*args):
    return subprocess.run([sys.executable, str(CHECK), *args], capture_output=True, text=True)


def test_the_cli_reports_what_it_fixed_and_what_is_left(tmp_path):
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("We utilise it, then delve into it.\n")

    result = run_cli(str(doc), "--config", str(config), "--level", "error", "--fix")

    assert result.returncode == 1
    assert "applied 1 exact replacement" in result.stdout
    assert "utilise->use" in result.stdout
    assert "Plain.Banned" in result.stdout
    assert "Swap.Terms" not in result.stdout.split("Vale reports")[1]
    assert doc.read_text() == "We use it, then delve into it.\n"


def test_a_fully_fixable_file_exits_zero_and_still_says_what_changed(tmp_path):
    """The caller's copy of the file is stale, so silence would be a lie."""
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("We utilise it.\n")

    result = run_cli(str(doc), "--config", str(config), "--level", "error", "--fix")

    assert result.returncode == 0
    assert "applied 1 exact replacement" in result.stdout
    assert "Vale reports" not in result.stdout


def test_without_fix_the_file_is_untouched(tmp_path):
    config = swap_config(tmp_path)
    doc = tmp_path / "a.md"
    doc.write_text("We utilise it.\n")

    result = run_cli(str(doc), "--config", str(config), "--level", "error")

    assert result.returncode == 1
    assert doc.read_text() == "We utilise it.\n"
    assert "applied" not in result.stdout


# ------------------------------------------------------------------ the floor


def test_min_alert_level_narrows_what_vale_returns(tmp_path):
    """Filtering in Vale rather than in Python: the discarded alerts are never built."""
    style = tmp_path / "styles" / "Mixed"
    style.mkdir(parents=True)
    (style / "Loud.yml").write_text(
        "extends: existence\nmessage: loud\nlevel: error\ntokens: ['utilise']\n"
    )
    (style / "Quiet.yml").write_text(
        "extends: existence\nmessage: quiet\nlevel: suggestion\ntokens: ['thing']\n"
    )
    config = tmp_path / "config.ini"
    config.write_text(
        f"StylesPath = {tmp_path / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n"
        "[*.md]\nBasedOnStyles = Mixed\n"
    )
    doc = tmp_path / "a.md"
    doc.write_text("We utilise the thing.\n")

    assert len(check.run(config, [doc])) == 2
    assert [a.check for a in check.run(config, [doc], level="error")] == ["Mixed.Loud"]

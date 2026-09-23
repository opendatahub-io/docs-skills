"""The two heading rules that shipped installed and inert.

`RedHat.Headings` and `RedHat.NoGerundsInTitles` are both `level: suggestion`,
and every gate in this project runs at `error`, so neither ever fired. The same
guidance was carried as prompt text on every write instead. These tests hold the
levels up, because the rules live in a downloaded package that `vale sync`
rewrites and only the config can raise them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "docs-engine" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lib.vale import check, compose  # noqa: E402

TEMPLATE = REPO_ROOT / "vale" / "docs.ini"
RAISED = ("RedHat.Headings", "RedHat.NoGerundsInTitles")


# ------------------------------------------------------------------ the config


def test_the_seed_template_raises_both_rules():
    text = TEMPLATE.read_text()
    for rule in RAISED:
        assert f"{rule} = error" in text


def test_a_composed_config_raises_them_when_the_style_is_there(tmp_path):
    package = tmp_path / "package"
    (package / "styles" / "RedHat").mkdir(parents=True)
    config = compose.build(tmp_path / "ws", package, base_styles=["RedHat"])
    text = config.read_text()
    for rule in RAISED:
        assert f"{rule} = error" in text


def test_a_composed_config_stays_quiet_when_the_style_is_missing(tmp_path):
    """A level set on a style Vale cannot find is E100, and E100 aborts the config."""
    package = tmp_path / "package"
    (package / "styles").mkdir(parents=True)
    config = compose.build(tmp_path / "ws", package, base_styles=["RedHat"])
    assert "RedHat." not in config.read_text()


def test_a_carried_config_loses_the_levels_with_the_style(tmp_path):
    package = tmp_path / "package"
    (package / "styles").mkdir(parents=True)
    carried = tmp_path / ".vale.ini"
    carried.write_text(
        "StylesPath = styles\nMinAlertLevel = error\n\n"
        "[*.md]\nBasedOnStyles = RedHat, DocsNotes\n"
        "RedHat.Headings = error\nRedHat.NoGerundsInTitles = error\n"
    )
    (package / "styles" / "DocsNotes").mkdir()

    config = compose.build(tmp_path / "ws", package, target_config=carried)
    text = config.read_text()

    assert "RedHat" not in text
    assert "BasedOnStyles = DocsNotes" in text


def test_drop_rule_levels_keeps_the_styles_that_stayed():
    text = "BasedOnStyles = A, B\nA.One = error\nB.Two = error\nMinAlertLevel = error\n"
    kept = compose.drop_rule_levels(text, ["A"])
    assert "A.One" not in kept
    assert "B.Two = error" in kept
    assert "MinAlertLevel = error" in kept


# -------------------------------------------------------------------- the gate

_INSTALLED = (REPO_ROOT / "styles" / "RedHat" / "Headings.yml").is_file()
needs_redhat = pytest.mark.skipif(
    not _INSTALLED or shutil.which("vale") is None,
    reason="needs vale and a synced RedHat style",
)

DIRTY_HEADINGS = "## Configuring The Widget Service\n\nSome body text here.\n"


def seeded_config(tmp_path, raised=True):
    text = TEMPLATE.read_text().replace(
        "StylesPath = ../styles", f"StylesPath = {REPO_ROOT / 'styles'}"
    )
    if not raised:
        text = "\n".join(
            line
            for line in text.splitlines()
            if not line.startswith(("RedHat.Headings", "RedHat.NoGerunds"))
        )
    config = tmp_path / "vale.ini"
    config.write_text(text)
    return config


@needs_redhat
def test_a_title_case_gerund_heading_fails_the_gate(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text(DIRTY_HEADINGS)
    fired = {a.check for a in check.run(seeded_config(tmp_path), [doc], level="error")}
    assert set(RAISED) <= fired


@needs_redhat
def test_without_the_raise_the_same_heading_passes(tmp_path):
    """What the gate used to see, and why the prompt had to say it instead."""
    doc = tmp_path / "a.md"
    doc.write_text(DIRTY_HEADINGS)
    config = seeded_config(tmp_path, raised=False)
    fired = {a.check for a in check.run(config, [doc], level="error")}
    assert not set(RAISED) & fired


@needs_redhat
def test_a_sentence_case_imperative_heading_clears(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("## Configure the widget service\n\nSome body text here.\n")
    fired = {a.check for a in check.run(seeded_config(tmp_path), [doc], level="error")}
    assert not set(RAISED) & fired


# --------------------------------------------------- what the config resolves to


@needs_redhat
def test_the_resolved_config_carries_the_styles_and_the_levels(tmp_path):
    """`ls-config` is what Vale decided, rather than what the file asked for.

    A package rename, a dropped level or a style that failed to sync all read
    the same way at the gate: quiet green. Asserting a subset rather than the
    whole map, because Vale merges any config in the runner's home directory.
    """
    resolved = json.loads(
        subprocess.run(
            ["vale", "--config", str(seeded_config(tmp_path)), "ls-config"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    )
    assert {"RedHat", "Std", "Voices", "Direct", "RedHatVoice"} <= set(
        resolved["SBaseStyles"]["*.md"]
    )
    assert resolved["SLevels"]["*.md"]["RedHat.Headings"] == "error"
    assert resolved["SLevels"]["*.md"]["RedHat.NoGerundsInTitles"] == "error"


# ------------------------------------------------------- what the prompts dropped


def test_no_prompt_restates_the_rules():
    """The point of raising them. A rule and a prompt line are not both needed."""
    for name in ("prompts/write-topic.md", "reference/style-topics.md"):
        body = (REPO_ROOT / "skills" / "docs-engine" / name).read_text()
        for phrase in ("Sentence case in headings", "Use sentence case."):
            assert phrase not in body
        assert "imperative verb rather than the -ing form" not in body


# ------------------------------------------------------------ lowered, not raised

LOWERED = ("Direct.Length",)


def test_the_seed_template_lowers_direct_length():
    assert "Direct.Length = warning" in TEMPLATE.read_text()


def test_a_composed_config_lowers_it_when_the_style_is_there(tmp_path):
    """`Direct.Length` ships at `error` and counts the words in a sentence,
    which a Markdown table row is not. It fired five times on one row of a
    supported-accelerator table, survived three repair passes because there was
    nothing about the prose to repair, and stopped the run."""
    package = tmp_path / "package"
    (package / "styles" / "Direct").mkdir(parents=True)
    config = compose.build(tmp_path / "ws", package, base_styles=["Direct"])
    assert "Direct.Length = warning" in config.read_text()


def test_the_lowered_level_does_not_live_in_the_package_file(tmp_path):
    """`styles/Direct/` is gitignored because `vale sync` writes it. Editing
    the rule file works until the next sync and cannot be committed at all, so
    the level belongs in the config like the raised ones."""
    shipped = REPO_ROOT / "styles" / "Direct" / "Length.yml"
    if not shipped.is_file():
        pytest.skip("the Direct package is not synced in this checkout")
    assert "level: error" in shipped.read_text(), (
        "the package ships this at error; the config is what lowers it"
    )


def test_a_composed_config_stays_quiet_when_direct_is_missing(tmp_path):
    """A level set on a style Vale cannot find is E100, and E100 aborts."""
    package = tmp_path / "package"
    (package / "styles").mkdir(parents=True)
    config = compose.build(tmp_path / "ws", package, base_styles=["Direct"])
    assert "Direct." not in config.read_text()

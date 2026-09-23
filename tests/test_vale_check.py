"""The Vale runner: parsing, severity ranking, and the failure modes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

path = Path(__file__).resolve().parent.parent / "skills" / "docs-engine" / "scripts"
sys.path.insert(0, str(path))

from lib.vale import check  # noqa: E402


def scratch_repo(tmp_path):
    """A minimal Vale setup: one style, one rule, one config."""
    style = tmp_path / "styles" / "Probe"
    style.mkdir(parents=True)
    (style / "Banned.yml").write_text(
        "extends: existence\n"
        "message: \"Banned word: '%s'\"\n"
        "description: Use more precise language.\n"
        "link: https://example.com/precision\n"
        "level: error\n"
        "tokens: ['utilize']\n"
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


def test_clean_file_has_no_alerts(tmp_path):
    config = scratch_repo(tmp_path)
    clean = tmp_path / "clean.md"
    clean.write_text("We use a thing.\n")
    assert check.run(config, [clean]) == []


def test_dirty_file_is_parsed(tmp_path):
    config = scratch_repo(tmp_path)
    dirty = tmp_path / "dirty.md"
    dirty.write_text("We utilize a thing.\n")
    alerts = check.run(config, [dirty])
    assert len(alerts) == 1
    assert alerts[0].check == "Probe.Banned"
    assert alerts[0].line == 1
    assert alerts[0].severity == "error"
    assert alerts[0].match == "utilize"


def test_alert_fields_description_link_suggestions(tmp_path):
    config = scratch_repo(tmp_path)
    dirty = tmp_path / "dirty.md"
    dirty.write_text("We utilize a thing.\n")
    alerts = check.run(config, [dirty])
    assert len(alerts) == 1
    assert alerts[0].description == "Use more precise language."
    assert alerts[0].link == "https://example.com/precision"
    assert alerts[0].suggestions == []


def test_missing_file_raises_rather_than_reading_clean(tmp_path):
    # Vale answers a nonexistent path with `{}` and exit 0, which is
    # byte-identical to a clean file. Reporting that as clean would turn a typo
    # into a passing lint.
    config = scratch_repo(tmp_path)
    with pytest.raises(check.ValeError, match="file not found"):
        check.run(config, [tmp_path / "ghost.md"])


def test_unknown_style_raises(tmp_path):
    scratch_repo(tmp_path)
    broken = tmp_path / "broken.ini"
    broken.write_text(
        f"StylesPath = {tmp_path / 'styles'}\n"
        "MinAlertLevel = error\n"
        "\n"
        "[*.md]\n"
        "BasedOnStyles = Absent\n"
    )
    page = tmp_path / "any.md"
    page.write_text("Text.\n")
    with pytest.raises(check.ValeError):
        check.run(broken, [page])


def test_empty_file_list_does_not_call_vale():
    assert check.run(None, []) == []


@pytest.mark.parametrize(
    ("severity", "floor", "expected"),
    [
        ("error", "error", True),
        ("warning", "error", False),
        ("warning", "warning", True),
        ("suggestion", "suggestion", True),
        ("suggestion", "warning", False),
        ("nonsense", "error", True),
    ],
)
def test_severity_ranking(severity, floor, expected):
    assert check.at_or_above(severity, floor) is expected


def test_format_alerts_names_the_file_and_forbids_disabling():
    alert = check.Alert(
        file="guide.md",
        line=3,
        span=(1, 5),
        check="RedHatVoice.ProcedureHasSteps",
        severity="error",
        message="A procedure topic needs a '## Procedure' heading.",
        match="type: procedure",
    )
    text = check.format_alerts("docs/guide.md", [alert])
    assert "Vale reports 1 alert(s) at error level or above in docs/guide.md:" in text
    assert "line 3: RedHatVoice.ProcedureHasSteps [error]" in text
    assert "Do not disable a rule to clear one." in text


def test_format_alerts_separates_advice_below_error():
    alert = check.Alert(
        file="guide.md",
        line=1,
        span=(1, 2),
        check="Std.Grammar.PassiveVoice",
        severity="warning",
        message="Passive voice.",
        match="was done",
    )
    text = check.format_alerts("guide.md", [alert], floor="warning")
    assert "[warning]" in text
    assert "Treat warnings and suggestions as advice." in text


def test_suggestions_survive_the_parse(tmp_path):
    """`Suggestions` is populated by substitution-style rules with an action.

    `check.apply_fixes` reads `action`, so a rename in Vale's JSON shape would
    quietly turn every free fix back into a model call. See test_vale_fix.py
    for what is done with it.
    """
    style = tmp_path / "styles" / "Swap"
    style.mkdir(parents=True)
    (style / "Terms.yml").write_text(
        "extends: substitution\n"
        "message: \"Use '%s' rather than '%s'.\"\n"
        "level: error\n"
        "action:\n"
        "  name: replace\n"
        "ignorecase: true\n"
        "swap:\n"
        "  utilise: use\n"
    )
    config = tmp_path / "config.ini"
    config.write_text(
        f"StylesPath = {tmp_path / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n"
        "[*.md]\nBasedOnStyles = Swap\n"
    )
    doc = tmp_path / "a.md"
    doc.write_text("We utilise the thing.\n")

    alerts = check.run(config, [doc])
    assert len(alerts) == 1
    assert alerts[0].suggestions == ["use"]
    assert alerts[0].action == {"name": "replace", "params": ["use"]}
    assert alerts[0].match == "utilise"


def test_a_missing_style_is_reported_as_one_line(tmp_path):
    """The finding a caller shows a human must fit on a line.

    Vale's `Text` for E100 is three paragraphs: a banner, the sentence that
    matters, and a footer about the exit status. Relaying all of it printed
    seven terminal lines to say that a package had not been synced.
    """
    scratch_repo(tmp_path)
    broken = tmp_path / "broken.ini"
    broken.write_text(
        f"StylesPath = {tmp_path / 'styles'}\n"
        "MinAlertLevel = error\n"
        "\n"
        "[*.md]\n"
        "BasedOnStyles = RedHat\n"
    )
    page = tmp_path / "any.md"
    page.write_text("Text.\n")
    with pytest.raises(check.ValeError) as raised:
        check.run(broken, [page])

    message = str(raised.value)
    assert "\n" not in message
    assert message.startswith("E100: ")
    assert "does not exist on StylesPath" in message
    assert "/docs --sync-styles" in message
    assert "Execution stopped" not in message


def test_a_config_error_that_is_not_a_style_gets_a_different_next_action():
    # Read off vale 3.21.0 on 2026-09-12: E201 carries a single-paragraph Text.
    payload = (
        '{"Line": 0, "Path": "d.ini", "Code": "E201", "Span": 1, '
        '"Text": "The path \'/nowhere\' does not exist."}'
    )
    assert check.describe_error(payload, "", 2) == (
        "E201: The path '/nowhere' does not exist. Check the Vale config the run was given."
    )


def test_output_that_is_not_json_falls_back_to_its_first_line():
    message = check.describe_error("something broke\nand kept going\n", "", 2)
    assert message.startswith("something broke.")
    assert "\n" not in message


def test_no_output_at_all_names_the_exit_code():
    assert check.describe_error("", "", 2) == "vale exited 2 with no output"


# ------------------------------------------------- alerts that quote nothing


def alert_for(tmp_path, message, match, line=1, text="A sentence on line one.\n"):
    doc = tmp_path / "a.md"
    doc.write_text(text)
    return check.Alert(str(doc), line, (1, 2), "Probe.Rule", "error", message, match)


def test_a_short_match_inside_a_word_is_not_a_quote(tmp_path):
    """`Direct.Length`'s match is the sentence's first word. A bare substring
    test called that quoted whenever the message happened to contain it."""
    alert = alert_for(tmp_path, "It runs to 45 words. Split it.", "It")
    assert "A sentence on line one." in check.format_alerts("a.md", [alert])


def test_an_alert_that_quotes_its_match_is_left_alone(tmp_path):
    """Most rules name what they found. Repeating the line would be padding."""
    alert = alert_for(tmp_path, "Inflated word: 'leveraging'.", "leveraging")
    rendered = check.format_alerts("a.md", [alert])
    assert "Inflated word: 'leveraging'." in rendered
    assert "A sentence on line one." not in rendered


def test_an_alert_that_quotes_nothing_carries_its_line(tmp_path):
    """`Direct.Length` says how long the sentence ran and nothing about which
    one it was, against a line number in a file the model never sees."""
    alert = alert_for(tmp_path, "Sentence runs to 45 words. Split it.", "A")
    rendered = check.format_alerts("a.md", [alert])
    assert "Sentence runs to 45 words." in rendered
    assert "A sentence on line one." in rendered


def test_the_excerpt_is_capped(tmp_path):
    long_line = "word " * 400
    alert = alert_for(tmp_path, "Sentence runs to 400 words. Split it.", "word", text=long_line)
    rendered = check.format_alerts("a.md", [alert])
    assert len(rendered) < 1000
    assert "word word" in rendered


def test_a_line_past_the_end_adds_nothing(tmp_path):
    alert = alert_for(tmp_path, "Sentence runs to 45 words. Split it.", "A", line=99)
    rendered = check.format_alerts("a.md", [alert])
    assert "Sentence runs to 45 words." in rendered
    assert rendered.count("\n") == 2


def test_a_file_that_has_gone_adds_nothing(tmp_path):
    alert = check.Alert(
        str(tmp_path / "missing.md"), 1, (1, 2), "Probe.Rule", "error", "Runs long.", "A"
    )
    rendered = check.format_alerts("missing.md", [alert])
    assert "Runs long." in rendered


def test_carries_its_text():
    def probe(message, match):
        return check.Alert("a.md", 1, (1, 2), "R.R", "error", message, match)

    assert check.carries_its_text(probe("Hedge: 'It's worth noting'.", "It's worth noting"))
    assert not check.carries_its_text(probe("Sentence runs to 45 words.", "If"))
    assert not check.carries_its_text(probe("Avoid gerunds in titles.", "Introducing"))
    assert not check.carries_its_text(probe("Something.", ""))
    # The quoted form, so a two-letter match cannot land inside a word of the
    # message and rob the alert of the excerpt it needs.
    assert not check.carries_its_text(probe("It runs long. Split it.", "It"))


# ------------------------------------------------------------------- scoping


@pytest.mark.parametrize("text,expected", [("3-7", (3, 7)), ("5-5", (5, 5))])
def test_parse_range_reads_an_inclusive_pair(text, expected):
    assert check.parse_range(text) == expected


@pytest.mark.parametrize("text", ["7-3", "0-3", "abc", "3", "", "-3"])
def test_parse_range_refuses_what_is_not_a_range(text):
    import argparse

    with pytest.raises(argparse.ArgumentTypeError):
        check.parse_range(text)


LINES = ["one", "", "two", "three", "", "four"]


@pytest.mark.parametrize(
    "ranges,expected",
    [
        # A line in the middle of a paragraph brings the rest of it.
        ([(4, 4)], [(3, 4)]),
        # A paragraph of one line stays one line.
        ([(1, 1)], [(1, 1)]),
        # The last line has no blank after it to stop on.
        ([(6, 6)], [(6, 6)]),
        # Two lines of one paragraph are one range, not two.
        ([(3, 3), (4, 4)], [(3, 4)]),
        # Separate paragraphs stay separate.
        ([(1, 1), (6, 6)], [(1, 1), (6, 6)]),
        # A range past the end is clamped rather than dropped.
        ([(99, 120)], [(6, 6)]),
    ],
)
def test_expand_to_blocks(ranges, expected):
    assert check.expand_to_blocks(LINES, ranges) == expected


def test_expand_to_blocks_on_an_empty_file():
    assert check.expand_to_blocks([], [(1, 1)]) == []


@pytest.mark.parametrize(
    "line,ranges,expected",
    [
        # No scope is not an empty scope. It means the whole file.
        (5, [], True),
        (5, [(1, 3)], False),
        (2, [(1, 3), (9, 10)], True),
        (9, [(1, 3), (9, 10)], True),
        (4, [(1, 3), (9, 10)], False),
    ],
)
def test_in_ranges(line, ranges, expected):
    assert check.in_ranges(line, ranges) is expected


# -------------------------------------------------------------- one excerpt


def test_an_excerpt_is_printed_once_per_line(tmp_path):
    """Three rules reading one sentence used to carry three copies of it."""
    doc = tmp_path / "a.md"
    doc.write_text("A sentence on line one.\n")
    alerts = [
        check.Alert(str(doc), 1, (1, 1), f"Probe.Rule{n}", "error", f"Runs to {n} words.", "A")
        for n in (41, 42, 43)
    ]
    rendered = check.format_alerts("a.md", alerts)
    assert rendered.count("A sentence on line one.") == 1
    for n in (41, 42, 43):
        assert f"Probe.Rule{n}" in rendered


def test_a_second_line_keeps_its_own_excerpt(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("First sentence here.\nSecond sentence here.\n")
    alerts = [
        check.Alert(str(doc), 1, (1, 1), "Probe.A", "error", "Runs to 41 words.", "First"),
        check.Alert(str(doc), 2, (1, 1), "Probe.B", "error", "Runs to 42 words.", "Second"),
    ]
    rendered = check.format_alerts("a.md", alerts)
    assert "First sentence here." in rendered
    assert "Second sentence here." in rendered


def test_a_scoped_report_says_it_is_scoped():
    alert = check.Alert("a.md", 3, (1, 2), "Probe.Rule", "error", "Banned word: 'x'.", "x")
    assert "in the lines just changed in a.md" in check.format_alerts("a.md", [alert], scoped=True)
    assert "or above in a.md" in check.format_alerts("a.md", [alert])

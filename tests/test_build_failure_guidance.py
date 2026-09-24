"""What a run says when a Vale rule stops it.

A run that ends on `a step failed` with a list of alerts above it leaves the
reader two questions it never answers: which of those alerts was fatal, and
whether they are expected to rewrite the sentence or change the rule. Grouping
by rule answers the first. Naming the repository's own config answers the
second, because a level set there is carried into every composed config and
overrides the built-in one.

The trap this file mostly exists for: Vale honours the *first* level it finds
for a rule, so appending a second line for one the config already sets does
nothing at all. That is true of exactly the rules this tool sets levels for,
which are the ones most likely to stop a run, so the message has to say which
line to change rather than telling everyone to add one.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD = REPO_ROOT / "skills" / "docs" / "scripts"
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
for path in (_ENGINE, _BUILD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build  # noqa: E402

SEEDED = """StylesPath = styles
MinAlertLevel = error

[*.md]
BasedOnStyles = RedHat, DocsNotes

RedHat.Headings = error
RedHat.NoGerundsInTitles = error
"""


@dataclass
class FakeAlert:
    file: str
    line: int
    check: str
    message: str
    severity: str = "error"


def alert(rule, line=1, file="research.md", message="the rule fired"):
    return FakeAlert(file=file, line=line, check=rule, message=message, severity="error")


def seeded(tmp_path):
    (tmp_path / ".vale.ini").write_text(SEEDED)
    return tmp_path


# ------------------------------------------------------------- which config


def test_the_repositorys_own_config_is_the_one_named(tmp_path):
    seeded(tmp_path)
    assert build.target_config(tmp_path) == tmp_path / ".vale.ini"


def test_an_alternative_config_name_is_found(tmp_path):
    (tmp_path / "vale.ini").write_text(SEEDED)
    assert build.target_config(tmp_path).name == "vale.ini"


def test_a_repository_with_no_config_is_told_where_one_goes(tmp_path):
    assert build.target_config(tmp_path) == tmp_path / ".vale.ini"


# ------------------------------------------------------- add, or change


def test_a_rule_the_config_already_sets_reports_its_line_and_level(tmp_path):
    seeded(tmp_path)
    line, level = build.existing_level(tmp_path / ".vale.ini", "RedHat.Headings")
    assert (line, level) == (7, "error")


def test_a_rule_the_config_does_not_set_reports_nothing(tmp_path):
    seeded(tmp_path)
    assert build.existing_level(tmp_path / ".vale.ini", "DocsNotes.CitationRequired") == (None, "")


def test_a_config_that_is_not_there_is_not_an_error(tmp_path):
    assert build.existing_level(tmp_path / "absent.ini", "RedHat.Headings") == (None, "")


def test_a_rule_name_is_matched_whole(tmp_path):
    """`RedHat.Heading` must not match the `RedHat.Headings` line above it."""
    seeded(tmp_path)
    assert build.existing_level(tmp_path / ".vale.ini", "RedHat.Heading") == (None, "")


# ------------------------------------------------------------- the message


def said(capsys):
    return capsys.readouterr().err


def test_the_message_names_the_rule_and_where_it_fired(tmp_path, capsys):
    seeded(tmp_path)
    build.explain_blocking([alert("DocsNotes.CitationRequired", line=11)], tmp_path)
    out = said(capsys)
    assert "DocsNotes.CitationRequired" in out
    assert "research.md line 11" in out


def test_rules_are_grouped_and_ordered_by_how_often_they_fired(tmp_path, capsys):
    seeded(tmp_path)
    build.explain_blocking(
        [alert("Quiet.Rule"), alert("Loud.Rule", line=2), alert("Loud.Rule", line=3)],
        tmp_path,
    )
    out = said(capsys)
    assert out.index("Loud.Rule") < out.index("Quiet.Rule")
    assert "Loud.Rule (2)" in out
    assert "2 rule(s), 3 error-level alert(s)" in out


def test_a_rule_already_in_the_config_is_told_which_line_to_change(tmp_path, capsys):
    """Appending a second line for it would change nothing."""
    seeded(tmp_path)
    build.explain_blocking([alert("RedHat.Headings")], tmp_path)
    out = said(capsys)
    assert "RedHat.Headings = warning" in out
    assert "line 7, currently `error`" in out


def test_a_rule_not_in_the_config_is_told_to_add_it(tmp_path, capsys):
    seeded(tmp_path)
    build.explain_blocking([alert("DocsNotes.CitationRequired")], tmp_path)
    out = said(capsys)
    assert "add it under [*.md]" in out


def test_the_config_path_is_named(tmp_path, capsys):
    seeded(tmp_path)
    build.explain_blocking([alert("RedHat.Headings")], tmp_path)
    assert str(tmp_path / ".vale.ini") in said(capsys)


def test_the_listing_is_capped_and_says_how_many_it_held_back(tmp_path, capsys):
    seeded(tmp_path)
    build.explain_blocking([alert("A.Rule", line=n) for n in range(1, 16)], tmp_path, cap=4)
    out = said(capsys)
    assert "A.Rule (15)" in out
    assert "...11 more not shown" in out

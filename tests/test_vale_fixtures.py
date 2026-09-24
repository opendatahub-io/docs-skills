"""Every authored Vale rule, proven against a bad and a good fixture.

The rule list comes from git, not from the fixture tree. Walking the fixtures
would only prove the rules that someone already wrote a fixture for, so a rule
committed without one would sit in `styles/` unchecked. Enumerating the
git-tracked `.yml` files inverts that: adding a rule and forgetting its fixture
fails the suite. `.gitignore` excludes the third-party packages that land in
`styles/` after `make sync-styles`, so the tracked set is exactly our own rules
and it maintains itself.

The harness enables exactly one style per run, so a fixture proves its own rule
rather than whatever else happens to be installed. It also caps alert message
length: a rule that interpolates its whole match through `%s` can cost more to
report than the prose it polices, so that failure belongs in CI.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "skills" / "docs-engine" / "scripts"))

from lib.vale import check  # noqa: E402

FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "vale"
STYLES = _REPO_ROOT / "styles"
MAX_MESSAGE = 160


def committed_rule_files():
    """Every git-tracked rule file under `styles/`."""
    completed = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files", "-z", "styles/*.yml"],
        capture_output=True,
        text=True,
        check=True,
    )
    names = [name for name in completed.stdout.split("\0") if name]
    if not names:
        raise RuntimeError("git tracks no rule files under styles/")
    return [_REPO_ROOT / name for name in names]


def committed_rules():
    """Every (style, rule) pair committed to `styles/`."""
    return sorted((path.relative_to(STYLES).parts[0], path.stem) for path in committed_rule_files())


def config_enabling_only(style, tmp_path):
    config = tmp_path / "vale.ini"
    config.write_text(
        f"StylesPath = {STYLES}\nMinAlertLevel = suggestion\n\n[*.md]\nBasedOnStyles = {style}\n"
    )
    return config


RULE_FILES = committed_rule_files()
PAIRS = committed_rules()


@pytest.mark.parametrize(("style", "rule"), PAIRS)
def test_every_committed_rule_has_a_fixture_pair(style, rule):
    for name in ("bad.md", "good.md"):
        fixture = FIXTURES / style / rule / name
        assert fixture.is_file(), f"{style}.{rule} has no {name}"


def test_no_fixture_outlives_its_rule():
    # A fixture for a rule that no longer exists passes vacuously and reads like
    # coverage, so the two sets have to agree in both directions.
    found = {
        (style.name, rule.name)
        for style in FIXTURES.iterdir()
        if style.is_dir()
        for rule in style.iterdir()
        if rule.is_dir()
    }
    assert sorted(found - set(PAIRS)) == []


@pytest.mark.parametrize(("style", "rule"), PAIRS)
def test_rule_fires_on_bad(style, rule, tmp_path):
    config = config_enabling_only(style, tmp_path)
    alerts = check.run(config, [FIXTURES / style / rule / "bad.md"])
    assert f"{style}.{rule}" in [a.check for a in alerts]


@pytest.mark.parametrize(("style", "rule"), PAIRS)
def test_good_fixture_is_clean_for_the_whole_style(style, rule, tmp_path):
    # Not just for its own rule. A good fixture carries the front matter and the
    # fenced code its rule has to look past, and that markup must not set off a
    # sibling rule in the same voice either.
    config = config_enabling_only(style, tmp_path)
    alerts = check.run(config, [FIXTURES / style / rule / "good.md"])
    assert [f"line {a.line}: {a.check}" for a in alerts] == []


@pytest.mark.parametrize(("style", "rule"), PAIRS)
def test_alert_message_stays_cheap(style, rule, tmp_path):
    config = config_enabling_only(style, tmp_path)
    alerts = check.run(config, [FIXTURES / style / rule / "bad.md"])
    for alert in (a for a in alerts if a.check == f"{style}.{rule}"):
        assert len(alert.message) <= MAX_MESSAGE, alert.message


@pytest.mark.parametrize("rule_file", RULE_FILES, ids=lambda path: path.stem)
def test_no_committed_rule_relies_on_a_bracket_parameter(rule_file):
    # A bracket parameter is global per rule, so a committed rule that expects a
    # section to tune it would be tuned everywhere at once. Budgets are
    # generated per artifact instead; see lib/vale/compose.py.
    assert "[max]" not in rule_file.read_text(), rule_file


# -------------------------------------------------- modular heading vocabulary


@pytest.mark.skipif(shutil.which("vale") is None, reason="vale is not installed")
@pytest.mark.parametrize(
    "name,front,body,expected",
    [
        (
            "a concept may enumerate without instructing",
            "concept",
            "A job moves through three states:\n\n1. Pending.\n2. Running.\n3. Done.\n",
            set(),
        ),
        (
            "a concept holding a Steps section is holding a procedure",
            "concept",
            "## Steps\n\n1. Run the installer.\n",
            {"RedHatVoice.ConceptHasNoSteps"},
        ),
        (
            "a procedure may spell its steps section Steps",
            "procedure",
            "## Steps\n\n1. Run it.\n\n## Verification\n\nCheck it.\n",
            set(),
        ),
        (
            "a procedure may spell it Procedure",
            "procedure",
            "## Procedure\n\n1. Run it.\n\n## Verification\n\nCheck it.\n",
            set(),
        ),
        # Heading levels. Delete the ### or #### alternatives from either script
        # and nothing else in the suite notices.
        (
            "a Steps heading counts at level three",
            "procedure",
            "### Steps\n\n1. Run it.\n\n## Verification\n\nCheck it.\n",
            set(),
        ),
        (
            "a Procedure heading counts at level four",
            "procedure",
            "#### Procedure\n\n1. Run it.\n\n## Verification\n\nCheck it.\n",
            set(),
        ),
        (
            "a concept is caught at level four too",
            "concept",
            "#### Steps\n\n1. Run the installer.\n",
            {"RedHatVoice.ConceptHasNoSteps"},
        ),
        # Tilde fences. The scripts handle ``` and ~~~; only the first was tested.
        (
            "a tilde-fenced heading does not satisfy a procedure",
            "procedure",
            "~~~markdown\n## Procedure\n~~~\n\n## Verification\n\nCheck it.\n",
            {"RedHatVoice.ProcedureHasSteps"},
        ),
        (
            "a tilde-fenced heading does not incriminate a concept",
            "concept",
            "Prose about the thing.\n\n~~~markdown\n## Procedure\n~~~\n",
            set(),
        ),
        # Quoted front matter is legal YAML and silently switched both rules off.
        (
            "a quoted type still gates the concept rule",
            '"concept"',
            "## Procedure\n\n1. Run the installer.\n",
            {"RedHatVoice.ConceptHasNoSteps"},
        ),
        # Four spaces makes it a code block in CommonMark. A trimmed comparison
        # read an indented example as a real heading.
        (
            "an indented heading is a code block, not a section",
            "concept",
            "Prose about the thing.\n\n    ## Procedure\n\n    1. Run it.\n",
            set(),
        ),
        (
            "an indented heading does not satisfy a procedure either",
            "procedure",
            "    ## Procedure\n\n## Verification\n\nCheck it.\n",
            {"RedHatVoice.ProcedureHasSteps"},
        ),
        (
            "three spaces is still a heading",
            "concept",
            "Prose.\n\n   ## Steps\n\n1. Run it.\n",
            {"RedHatVoice.ConceptHasNoSteps"},
        ),
        (
            "a quoted type still gates the procedure rule",
            "'procedure'",
            "Prose with no steps section.\n",
            {"RedHatVoice.ProcedureHasSteps"},
        ),
    ],
)
def test_modular_heading_vocabulary(tmp_path, name, front, body, expected):
    """Red Hat modular docs spell the steps section `Procedure` or `Steps`.

    Accepting only the first rejected correct procedure topics, and treating
    any `1. ` line as a step flagged every ordered list in a concept. Both were
    reported against the committed rules and reproduced before this test landed.
    """
    config = tmp_path / "config.ini"
    config.write_text(
        f"StylesPath = {_REPO_ROOT / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n"
        "[*.md]\nBasedOnStyles = RedHatVoice\n"
    )
    doc = tmp_path / "m.md"
    doc.write_text(f"---\ntype: {front}\n---\n\n# Title\n\n{body}")
    fired = {alert.check for alert in check.run(config, [doc])}
    assert fired & {"RedHatVoice.ConceptHasNoSteps", "RedHatVoice.ProcedureHasSteps"} == expected


@pytest.mark.skipif(shutil.which("vale") is None, reason="vale is not installed")
def test_the_repo_and_topic_chains_share_one_type_vocabulary():
    """The copied generator typed a procedure `task` while the Vale rules gate
    on `procedure`, so every repo-mode procedure was silently exempt from the
    structural rules until the two chains were first run together."""
    sys.path.insert(0, str(_REPO_ROOT / "skills" / "docs-engine" / "scripts"))
    from lib.md import docs_meta

    assert "task" not in docs_meta.TYPES
    assert "procedure" in docs_meta.TYPES

    schema = json.loads(
        (_REPO_ROOT / "skills" / "docs-engine" / "schemas" / "write-out.json").read_text()
    )
    enum = schema["properties"]["frontmatter"]["properties"]["type"]["enum"]
    assert "task" not in enum and "procedure" in enum

    for path in (_REPO_ROOT / "skills" / "docs-engine" / "languages").glob("*.md"):
        assert ", task]" not in path.read_text(), path
        assert "[task]" not in path.read_text(), path


@pytest.mark.skipif(shutil.which("vale") is None, reason="vale is not installed")
@pytest.mark.parametrize("spelling", ["procedure", '"procedure"', "'procedure'", "task"])
@pytest.mark.parametrize(
    "rule", ["RedHatVoice.ProcedureHasSteps", "RedHatVoice.ProcedureHasVerification"]
)
def test_both_procedure_rules_gate_every_spelling(tmp_path, spelling, rule):
    """A spelling a rule does not recognise is a document it silently exempts.

    `task` is what this project wrote before the rename and is still on disk in
    any repository documented earlier. Quoted values are legal YAML that an
    exact comparison read as a non-match. Either gap switches an error-level
    rule off without saying so.
    """
    config = tmp_path / "config.ini"
    config.write_text(
        f"StylesPath = {_REPO_ROOT / 'styles'}\n"
        "MinAlertLevel = suggestion\n\n"
        "[*.md]\nBasedOnStyles = RedHatVoice\n"
    )
    doc = tmp_path / "m.md"
    doc.write_text(f"---\ntype: {spelling}\n---\n\n# Title\n\nProse with no sections.\n")
    assert rule in {alert.check for alert in check.run(config, [doc])}

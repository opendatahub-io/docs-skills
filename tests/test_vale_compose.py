"""Composing one run config from a target repository's config and our voices.

Two behaviours are pinned here. Vale resolves overlapping globs by last match
wins and the winning section replaces BasedOnStyles rather than extending it, so
ONBOARDING.md must draw its own voice alone. And a bracket parameter is global per
rule, so each artifact's budget arrives as a generated one-rule style instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "skills" / "docs-engine" / "scripts")
)

from lib.vale import check, compose  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent


def target_repo(tmp_path):
    """A repository with a Vale config and a style of its own."""
    repo = tmp_path / "target"
    style = repo / "styles" / "House"
    style.mkdir(parents=True)
    (style / "Banned.yml").write_text(
        "extends: existence\nmessage: \"House rule: '%s'\"\nlevel: error\ntokens: ['utilize']\n"
    )
    (repo / ".vale.ini").write_text(
        "StylesPath = styles\nMinAlertLevel = error\n\n[*.md]\nBasedOnStyles = House\n"
    )
    return repo


def long_note(words=28):
    """A cited bullet of `words` words, so only a budget rule can object to it."""
    return "- " + " ".join(f"w{i}" for i in range(words)) + " https://x.example\n"


def test_target_repository_rules_still_fire(tmp_path):
    repo = target_repo(tmp_path)
    config = compose.build(tmp_path / "ws", _REPO_ROOT, target_config=repo / ".vale.ini")
    page = repo / "guide.md"
    page.write_text("We utilize a thing.\n")
    assert "House.Banned" in [a.check for a in check.run(config, [page])]


def test_downloaded_styles_are_linked_without_copying_them(tmp_path):
    downloaded = tmp_path / "downloaded"
    style = downloaded / "Downloaded"
    style.mkdir(parents=True)
    (style / "Rule.yml").write_text(
        "extends: existence\nmessage: found\nlevel: error\ntokens: [downloaded]\n"
    )
    workspace = tmp_path / "ws"
    config = compose.build(
        workspace,
        _REPO_ROOT,
        base_styles=["Downloaded"],
        downloaded_styles=downloaded,
    )
    assert (workspace / "vale" / "styles" / "Downloaded").resolve() == style.resolve()
    page = workspace / "page.md"
    page.write_text("downloaded\n")
    assert "Downloaded.Rule" in [alert.check for alert in check.run(config, [page])]


def test_onboarding_draws_its_own_voice_and_budget(tmp_path):
    repo = target_repo(tmp_path)
    workspace = tmp_path / "ws"
    config = compose.build(
        workspace, _REPO_ROOT, target_config=repo / ".vale.ini", budgets={"onboarding": 20}
    )
    research = workspace / "ONBOARDING.md"
    research.write_text(long_note())
    checks = [a.check for a in check.run(config, [research])]
    assert "DocsBudgetOnboarding.Words" in checks
    assert "House.Banned" not in checks


def test_each_artifact_gets_its_own_budget(tmp_path):
    # The case a bracket parameter cannot express: one small budget and two
    # large ones, in one config, applied to the same content.
    workspace = tmp_path / "ws"
    config = compose.build(
        workspace, _REPO_ROOT, base_styles=["RedHatVoice"], budgets={"onboarding": 20}
    )
    for name in ("ONBOARDING", "plan", "git-context"):
        (workspace / f"{name}.md").write_text(long_note())

    assert "DocsBudgetOnboarding.Words" in [
        a.check for a in check.run(config, [workspace / "ONBOARDING.md"])
    ]
    assert check.run(config, [workspace / "plan.md"]) == []
    assert check.run(config, [workspace / "git-context.md"]) == []


def test_artifact_sections_come_after_the_general_section(tmp_path):
    config = compose.build(tmp_path / "ws", _REPO_ROOT, base_styles=["RedHatVoice"])
    text = config.read_text()
    assert text.index("[**/*.md]") < text.index("[**/ONBOARDING.md]")


def test_the_generated_config_sets_min_alert_level_once(tmp_path):
    # A carried-over MinAlertLevel would duplicate the one we set.
    repo = target_repo(tmp_path)
    config = compose.build(tmp_path / "ws", _REPO_ROOT, target_config=repo / ".vale.ini")
    assert config.read_text().count("MinAlertLevel") == 1


def test_works_with_no_target_config(tmp_path):
    workspace = tmp_path / "ws"
    config = compose.build(workspace, _REPO_ROOT, base_styles=["RedHatVoice"])
    plan = workspace / "plan.md"
    plan.write_text("# Plan\n\n- Ship the thing\n")
    assert check.run(config, [plan]) == []


def test_a_target_style_cannot_shadow_ours(tmp_path):
    # Our styles are linked first, so a target repository carrying its own
    # DocsNotes cannot replace the voice the pipeline depends on.
    repo = tmp_path / "target"
    (repo / "styles" / "DocsNotes").mkdir(parents=True)
    (repo / "styles" / "DocsNotes" / "Impostor.yml").write_text(
        "extends: existence\nmessage: 'impostor'\nlevel: error\ntokens: ['zzz']\n"
    )
    (repo / ".vale.ini").write_text("StylesPath = styles\nMinAlertLevel = error\n")
    workspace = tmp_path / "ws"
    compose.build(workspace, _REPO_ROOT, target_config=repo / ".vale.ini")
    linked = (workspace / "vale" / "styles" / "DocsNotes").resolve()
    assert linked == (_REPO_ROOT / "styles" / "DocsNotes").resolve()


def test_an_unknown_budget_key_is_an_error(tmp_path):
    # Ignoring it would leave onboarding on its 6000 default with nothing said.
    with pytest.raises(ValueError) as raised:
        compose.build(tmp_path / "ws", _REPO_ROOT, budgets={"reserach": 20})
    assert "reserach" in str(raised.value)
    assert "onboarding" in str(raised.value)


def test_a_relative_package_root_still_links_our_styles(tmp_path, monkeypatch):
    # Symlinks are written into the workspace, so an unresolved relative root
    # would be read against the workspace and land as a broken link.
    monkeypatch.chdir(_REPO_ROOT.parent)
    workspace = tmp_path / "ws"
    config = compose.build(workspace, _REPO_ROOT.name, base_styles=["DocsNotes"])
    note = workspace / "ONBOARDING.md"
    note.write_text("- The mirror registry requires a pull secret\n")
    assert "DocsNotes.CitationRequired" in [a.check for a in check.run(config, [note])]


def test_styles_path_is_absolute_even_when_the_workspace_is_relative(tmp_path, monkeypatch):
    """Vale resolves StylesPath against the config's own directory.

    A relative workspace produced `StylesPath = ws/vale/styles` inside
    `ws/vale/config.ini`, which Vale read as `ws/vale/ws/vale/styles` and
    rejected with E201. Verified against vale 3.21.0.
    """
    monkeypatch.chdir(tmp_path)
    config = compose.build("ws", _REPO_ROOT, base_styles=["DocsNotes"])
    line = next(
        row for row in Path(config).read_text().splitlines() if row.startswith("StylesPath")
    )
    styles = Path(line.split("=", 1)[1].strip())
    assert styles.is_absolute()
    assert styles.is_dir()


def test_a_reused_workspace_is_rejected(tmp_path):
    """`link_styles` skips names that already exist, so a reused workspace would
    keep the previous target repository's styles. Building into one is an error
    rather than a silently wrong config."""
    workspace = tmp_path / "ws"
    compose.build(workspace, _REPO_ROOT, base_styles=["DocsNotes"])
    with pytest.raises(compose.WorkspaceError):
        compose.build(workspace, _REPO_ROOT, base_styles=["DocsNotes"])


def test_an_unavailable_base_style_is_dropped_from_the_config(tmp_path):
    """E100 aborts the whole config, not the one section that named the style.

    When a base style does not exist, a config naming it fails to load at all
    and every artifact section below goes with it. Dropping the name keeps the
    rest of the config alive, so only the available style remains.
    """
    workspace = tmp_path / "ws"
    config = compose.build(workspace, _REPO_ROOT, base_styles=["NoSuchStyle", "DocsNotes"])
    text = config.read_text()
    assert "NoSuchStyle" not in text
    assert "BasedOnStyles = DocsNotes" in text

    note = workspace / "note.md"
    note.write_text("Some ordinary prose.\n")
    assert check.run(config, [note]) == []


def test_the_artifact_sections_still_fire_after_a_style_is_dropped(tmp_path):
    """When an unavailable base style is dropped, other sections still run.

    Dropping a nonexistent style keeps the rest of the config alive, so rules
    from available styles in artifact sections continue to apply.
    """
    workspace = tmp_path / "ws"
    config = compose.build(workspace, _REPO_ROOT, base_styles=["NoSuchStyle", "DocsNotes"])
    research = workspace / "ONBOARDING.md"
    research.write_text("- A claim with nothing behind it\n")
    assert "DocsNotes.CitationRequired" in [a.check for a in check.run(config, [research])]


def test_the_general_section_goes_when_no_base_style_resolves(tmp_path):
    """An empty BasedOnStyles is a config error, so the general section is removed.

    When all base styles are unavailable and dropped, the BasedOnStyles list
    becomes empty, which is itself a config error. The general section must be
    removed entirely, but artifact sections continue to apply.
    """
    workspace = tmp_path / "ws"
    config = compose.build(workspace, _REPO_ROOT, base_styles=["NoSuchStyle", "AlsoMissing"])
    assert "[**/*.md]" not in config.read_text()
    research = workspace / "ONBOARDING.md"
    research.write_text("- A claim with nothing behind it\n")
    assert "DocsNotes.CitationRequired" in [a.check for a in check.run(config, [research])]


def test_a_config_whose_base_styles_all_resolve_is_left_alone(tmp_path):
    config = compose.build(tmp_path / "ws", _REPO_ROOT, base_styles=["DocsNotes", "DocsPlan"])
    assert "BasedOnStyles = DocsNotes, DocsPlan" in config.read_text()


def test_warnings_reach_the_caller_without_blocking_it(tmp_path):
    """MinAlertLevel is suggestion so that --vale-level has something to filter.

    The gate stays where it was: every consumer applies its own floor through
    `check.at_or_above`, and both default to error.
    """
    repo = tmp_path / "target"
    style = repo / "styles" / "House"
    style.mkdir(parents=True)
    (style / "Soft.yml").write_text(
        "extends: existence\nmessage: \"House note: '%s'\"\nlevel: warning\ntokens: ['utilize']\n"
    )
    (repo / ".vale.ini").write_text(
        "StylesPath = styles\nMinAlertLevel = error\n\n[*.md]\nBasedOnStyles = House\n"
    )
    config = compose.build(tmp_path / "ws", _REPO_ROOT, target_config=repo / ".vale.ini")
    page = repo / "guide.md"
    page.write_text("We utilize a thing.\n")

    alerts = check.run(config, [page])
    assert [a.severity for a in alerts] == ["warning"]
    assert [a for a in alerts if check.at_or_above(a.severity, "error")] == []


def test_onboarding_and_index_have_a_section_each():
    """A budget key with no section is accepted and ignored, which is the
    silent failure resolve_budgets exists to close."""
    keyed = {key for key, _, _, _ in compose.ARTIFACT_SECTIONS}
    assert "onboarding" in keyed and "index" in keyed
    assert set(compose.DEFAULT_BUDGETS) == keyed


def test_every_artifact_section_names_a_file_the_chain_writes():
    """A section is only half the pairing. Its glob has to match something.

    `evidence` had a key, a section and a generated style for as long as the
    budgets existed, and its `[**/evidence/*.md]` glob matched nothing: no
    step ever wrote that directory. The budget resolved, the rule shipped, and
    it governed no file. Pairing the key to the section could not see that.
    """
    scripts = "\n".join(p.read_text() for p in (_REPO_ROOT / "skills").rglob("*.py"))
    # git-context.md and index.md are written by the entry points, so until
    # both exist this asserts against half a tree. The guard clears itself the
    # moment they land rather than needing a second edit to re-enable it.
    entry_points = (
        _REPO_ROOT / "skills" / "docs" / "scripts" / "build.py",
        _REPO_ROOT / "skills" / "docs-plan" / "scripts" / "plan.py",
    )
    missing = [e.parent.parent.name for e in entry_points if not e.is_file()]
    if missing:
        pytest.skip(f"the chain is mid-migration; {', '.join(missing)} is not here yet")
    for key, glob, _, _ in compose.ARTIFACT_SECTIONS:
        name = glob.strip("[]").rsplit("/", 1)[-1]
        assert "*" not in name, f"{key} globs a directory, so no file name pins it"
        assert f'"{name}"' in scripts, f"{key} budgets {name}, which no step under skills/ writes"


def test_a_carried_config_loses_a_style_that_was_never_downloaded(tmp_path, capsys):
    """The missing-style drop was skipped whenever the target had a .vale.ini,
    which is the file `/docs --sync-styles` writes. One package that failed
    to download then aborted the whole config with E100, artifact sections and
    all -- the exact failure the drop exists to prevent."""
    repo = tmp_path / "target"
    repo.mkdir()
    (repo / ".vale.ini").write_text(
        "StylesPath = styles\n\n[*.md]\nBasedOnStyles = RedHat, Std, NeverDownloaded\n"
    )
    built = compose.build(
        tmp_path / "ws", _REPO_ROOT / "skills" / "docs-engine", target_config=repo / ".vale.ini"
    )
    text = Path(built).read_text()
    assert "NeverDownloaded" not in text
    assert "dropped from the config" in capsys.readouterr().err


def test_a_carried_config_keeps_the_styles_it_does_have(tmp_path):
    repo = tmp_path / "target"
    style = repo / "styles" / "House"
    style.mkdir(parents=True)
    (style / "Banned.yml").write_text(
        "extends: existence\nmessage: x\nlevel: error\ntokens: ['a']\n"
    )
    (repo / ".vale.ini").write_text(
        "StylesPath = styles\n\n[*.md]\nBasedOnStyles = House, NeverDownloaded\n"
    )
    built = compose.build(
        tmp_path / "ws", _REPO_ROOT / "skills" / "docs-engine", target_config=repo / ".vale.ini"
    )
    text = Path(built).read_text()
    assert "BasedOnStyles = House" in text
    assert "NeverDownloaded" not in text

"""build.py's prose wiring.

The orchestrator is a subprocess driver, so these tests cover the two decisions
it makes on its own: where the Vale workspace comes from, and whether a failure
to build one stops the run.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD = REPO_ROOT / "skills" / "docs" / "scripts"
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
for path in (_ENGINE, _BUILD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build  # noqa: E402
from lib.pipeline import workspace  # noqa: E402
from lib.vale import check  # noqa: E402
from lib.vale import compose as vale_compose  # noqa: E402

REPO_ROOT_STR = str(REPO_ROOT)


def compose(repo, out, config):
    """The orchestrator's call, minus the package root it always passes."""
    return workspace.build(repo, out, config, REPO_ROOT)[0]


from lib.ast import build_module_map  # noqa: E402


def test_workspace_is_built_fresh_each_time(tmp_path):
    """The second call must not inherit the first call's style symlinks."""
    out = tmp_path / "out"
    out.mkdir()
    first = compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}})
    (Path(first).parent / "styles" / "Stale").mkdir()
    second = compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}})
    assert second is not None
    assert not (Path(second).parent / "styles" / "Stale").exists()


def test_workspace_config_is_usable(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    config = compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}})
    assert Path(config).is_file()
    assert "DocsNotes" in Path(config).read_text()


def test_workspace_uses_project_local_downloaded_styles(tmp_path):
    out = tmp_path / ".docs-gen"
    downloaded = out / workspace.VALE_PACKAGES_DIR / "Downloaded"
    downloaded.mkdir(parents=True)
    (downloaded / "Rule.yml").write_text(
        "extends: existence\nmessage: found\nlevel: error\ntokens: [downloaded]\n"
    )
    config = compose(tmp_path, out, {"vale": {"base_styles": ["Downloaded"]}})
    linked = Path(config).parent / "styles" / "Downloaded"
    assert linked.resolve() == downloaded.resolve()


def test_a_target_config_is_carried_over(tmp_path):
    (tmp_path / ".vale.ini").write_text(
        "MinAlertLevel = warning\n\n[*.md]\nBasedOnStyles = DocsPlan\n"
    )
    out = tmp_path / "out"
    out.mkdir()
    config = Path(compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}}))
    assert "DocsPlan" in config.read_text()


def test_a_composed_workspace_does_not_enter_the_module_registry_walk(tmp_path):
    """Same defect, one layer down: the registry walker also walks `.docs-gen`.

    `detect_language.py` and `build_module_map.py` used to carry their own
    separate copies of `EXCLUDED_DIRS`, so excluding `.docs-gen` from one did
    not exclude it from the other. `build_module_map` groups files by
    language-specific extension, so a Python-only fixture repo can't show the
    defect under `--lang python` (the workspace holds no `.py` files); asking
    it to group by `yaml` instead, which is what the generated
    `DocsBudget*/Words.yml` files and vale's own rule files actually are, does.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def a():\n    return 1\n")

    before = build_module_map.build_module_map(str(repo), "yaml")
    assert before["modules"] == {}

    out_dir = repo / ".docs-gen"
    out_dir.mkdir()
    built = compose(repo, out_dir, {"vale": {"base_styles": ["DocsNotes"]}})
    assert built is not None

    after = build_module_map.build_module_map(str(repo), "yaml")
    assert after["modules"] == {}


def test_a_workspace_path_blocked_by_a_file_returns_none_rather_than_raising(tmp_path):
    """The stale-workspace cleanup must not be able to take the run down.

    `shutil.rmtree` raises `NotADirectoryError` when the path it is handed is
    a file, not a directory. That call used to run before the `try:` that
    wraps `compose.build`, so nothing caught it and a leftover file at the
    workspace path took down the whole sync run over a gate that is meant to
    be optional. It now runs inside that same `try:`.
    """
    out = tmp_path / "out"
    out.mkdir()
    (out / workspace.VALE_DIR).write_text("not a directory")
    assert compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}}) is None


def test_an_unbuildable_workspace_returns_none_rather_than_raising(tmp_path):
    """Prose checking is a gate, not a prerequisite.

    `compose.resolve_budgets` raises on an unknown budget key, which is how a
    typo like `reserch` is caught rather than silently leaving research on its
    default. sync logs that and stands the gate down; it does not stop the run,
    and it does not build a config that quietly ignores the setting.
    """
    out = tmp_path / "out"
    out.mkdir()
    assert compose(tmp_path, out, {"vale": {"budgets": {"reserch": 6000}}}) is None


def report_with(**sections):
    """A write-report shaped like the real one, with only the keys under test."""
    base = {"written": [], "unchanged": [], "refused": [], "failed": [], "deferred": []}
    base.update(sections)
    return base


def test_the_chains_own_artifacts_are_linted(tmp_path):
    """compose.build declares a voice per artifact and nothing ran them: the
    reviewer walks the documentation directory, and SKIP_DIRS excludes the
    artifact directory, so the contract held only in unit tests."""
    out = tmp_path / "out"
    out.mkdir()
    config = compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}})
    (out / "ONBOARDING.md").write_text("# Research\n\n- A claim with nothing behind it\n")
    assert len(workspace.lint_artifacts(out, config)[0]) >= 1


def test_a_clean_artifact_reports_nothing(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    config = compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}})
    (out / "ONBOARDING.md").write_text("# Research\n\n- A sourced claim [src:main.py]\n")
    assert workspace.lint_artifacts(out, config) == ([], "")


def test_no_config_means_no_linting(tmp_path):
    (tmp_path / "ONBOARDING.md").write_text("- unsourced\n")
    assert workspace.lint_artifacts(tmp_path, None) == ([], "")


def test_a_missing_artifact_is_not_a_failure(tmp_path):
    """A run that stopped before planning has no plan.md to lint."""
    out = tmp_path / "out"
    out.mkdir()
    config = compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}})
    assert workspace.lint_artifacts(out, config) == ([], "")


def test_a_linter_that_could_not_run_is_not_a_clean_pass(tmp_path, monkeypatch):
    """Vale aborting on its config returned no alerts, which artifact_gate read
    as nothing to report. The run then went through write and review with the
    prose gate off and no line anywhere saying so."""
    out = tmp_path / "out"
    out.mkdir()
    config = compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}})
    (out / "ONBOARDING.md").write_text("# Research\n\n- A claim\n")

    def refuse(*a, **k):
        raise check.ValeError("E100 could not find style 'RedHat'")

    monkeypatch.setattr(check, "run", refuse)
    alerts, reason = workspace.lint_artifacts(out, config)
    assert alerts == []
    assert "E100" in reason


def test_every_budget_key_is_reachable_by_lint_artifacts(tmp_path):
    """`lint_artifacts` must derive its file list from `compose.ARTIFACT_SECTIONS`
    instead of keeping one of its own. The previous list named three of the
    artifacts the budgets cover, and git-context.md, ONBOARDING.md and the
    changeset index drifted out of it silently. This fixture plants one file
    per glob and fails loudly if any key goes unmatched.

    Planting the file is why this alone is not enough: it proves the glob
    matches, never that a step writes there. `evidence` passed here for as
    long as it existed. `test_every_artifact_section_names_a_file_the_chain_writes`
    in tests/test_vale_compose.py is the other half.
    """
    out = tmp_path / "out"
    fixture = {
        "git_context": "git-context.md",
        "onboarding": "ONBOARDING.md",
        "plan": "plan.md",
        "index": "changeset-2026-01-01-x/index.md",
    }
    # Keeps this fixture itself honest: a budget key added to compose.py
    # without a matching entry here fails this assertion first.
    assert set(fixture) == set(vale_compose.DEFAULT_BUDGETS)
    for rel in fixture.values():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content\n")

    matched = workspace.artifact_files(out)

    assert set(matched) == set(vale_compose.DEFAULT_BUDGETS)
    for key, rel in fixture.items():
        assert out / rel in matched[key]


def test_a_previously_unlinted_artifact_is_now_caught(tmp_path):
    """ONBOARDING.md was one of the four artifacts nothing ever ran a lint
    against, because the old hardcoded name list did not include it."""
    out = tmp_path / "out"
    out.mkdir()
    config = compose(tmp_path, out, {"vale": {"base_styles": ["DocsNotes"]}})
    (out / "ONBOARDING.md").write_text("# Placement\n\n- A claim with nothing behind it\n")
    assert len(workspace.lint_artifacts(out, config)[0]) >= 1


def test_a_warning_level_alert_is_returned_for_the_caller_to_weigh(tmp_path):
    """Filtering to errors here would silently drop the budget warnings, which
    are the ones a reader most wants to see and least wants enforced. This
    answers what Vale found; `build.artifact_gate` decides which of it stops a
    run. Built from a hand-written config rather than `compose.build`, so the
    severity under test does not move when a rule's level changes.
    """
    styles = tmp_path / "styles" / "Probe"
    styles.mkdir(parents=True)
    (styles / "Soft.yml").write_text(
        "extends: existence\nmessage: \"Soft: '%s'\"\nlevel: warning\ntokens: ['utilize']\n"
    )
    config = tmp_path / "vale.ini"
    config.write_text(
        f"StylesPath = {tmp_path / 'styles'}\nMinAlertLevel = suggestion\n\n"
        "[**/ONBOARDING.md]\nBasedOnStyles = Probe\n"
    )
    out = tmp_path / "out"
    out.mkdir()
    (out / "ONBOARDING.md").write_text("We utilize a thing.\n")
    alerts, _ = workspace.lint_artifacts(out, str(config))
    assert [a.severity for a in alerts] == ["warning"]


def commits(repo):
    import subprocess

    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "i"],
        check=True,
    )


def test_a_repository_with_no_commits_has_no_history(tmp_path):
    """A freshly initialised repository has a .git directory and no HEAD.
    `git log` there fails with "does not have any commits yet", which reached
    the console as a raw JSON error and read like a crash."""
    import subprocess

    repo = tmp_path / "empty"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert build.has_history(repo) is False


def test_a_repository_with_a_commit_has_history(tmp_path):
    repo = tmp_path / "real"
    repo.mkdir()
    commits(repo)
    assert build.has_history(repo) is True


def test_a_directory_that_is_not_a_repository_has_no_history(tmp_path):
    assert build.has_history(tmp_path) is False

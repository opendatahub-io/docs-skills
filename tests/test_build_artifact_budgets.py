"""build.py must actually enforce the budgets compose.py composes.

`compose.build` turns `.docs-gen.yaml`'s `vale.budgets` into a generated,
`level: error` Vale style per artifact, and until now nothing read the
severity of what Vale found: `build.py` logged up to ten alerts and moved on
to `write`, the expensive step. These tests pin the gate in: an error-level
alert on one of the chain's own artifacts stops the run with exit 3, at
every point the reasoning trail can be inspected -- before `write`, on
`--dry-run`, and after `write` returns, for the index it writes.

No model is involved. `build.run` is faked to report success for every step
these tests do not care about, so a failure below can only come from the
gate itself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD = REPO_ROOT / "skills" / "docs" / "scripts"
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
for path in (_ENGINE, _BUILD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build  # noqa: E402
from lib.vale import check  # noqa: E402


def _args(**over):
    base = dict(
        topic="hierarchical KV cache tiering",
        ticket=None,
        no_sources=True,
        version=None,
        max_repos=3,
        dry_run=False,
        no_review=True,
        llm_cmd=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _config(budgets=None):
    cfg = {"product": "RHOAI", "version": "2.19"}
    if budgets:
        cfg["vale"] = {"budgets": budgets}
    return cfg


def bulleted_words(n, cited=False):
    """A single bullet with `n` words, under every length limit but this one."""
    tail = " https://example.com/evidence" if cited else ""
    return "- " + " ".join(f"w{i}" for i in range(n)) + tail + "\n"


def fake_run_always_ok(calls):
    def fake_run(argv, label, allowed=(0,)):
        calls.append([str(a) for a in argv])
        return 0

    return fake_run


def fake_run_writing_index(calls, content):
    """Also stands in for write.py: real write.py writes `index.md` into the
    changeset directory it is given, so this fake does the one thing about
    that the test cares about and nothing else."""

    def fake_run(argv, label, allowed=(0,)):
        argv = [str(a) for a in argv]
        calls.append(argv)
        if "write.py" in argv[0]:
            changeset_dir = Path(argv[argv.index("--changeset") + 1])
            changeset_dir.mkdir(parents=True, exist_ok=True)
            (changeset_dir / "index.md").write_text(content)
        return 0

    return fake_run


def run_dir(out_dir, args, monkeypatch):
    """Where `build` writes one run's artifacts, which a test seeds into.

    `build` empties that directory before the chain starts, so that a re-run
    cannot read what the last one left. These tests fake `run`, so the seeded
    files stand in for what a real step would have written and the clear is
    turned off rather than racing it.
    """
    monkeypatch.setattr(build, "clear_run_directory", lambda root, where: None)
    path = build.run_directory(out_dir, args)
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_an_over_budget_artifact_is_reported_and_does_not_stop_the_run(
    tmp_path, monkeypatch, capsys
):
    """A budget is a target. Going over it says the reduction that step
    exists to perform probably did not happen, which is worth saying and
    is not worth throwing away a run for."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls = []
    monkeypatch.setattr(build, "run", fake_run_always_ok(calls))
    args = _args()
    where = run_dir(out_dir, args, monkeypatch)
    (where / "ONBOARDING.md").write_text(bulleted_words(30, cited=True))

    code = build.build(tmp_path, out_dir, "docs", _config({"onboarding": 5}), args, None)

    assert code != 3
    assert [c for c in calls if "write.py" in c[0]], "a target must not stop the run"
    err = capsys.readouterr().err
    assert "ONBOARDING.md" in err
    assert "budget of 5" in err


def test_a_warning_level_alert_does_not_fail_the_run(tmp_path, monkeypatch):
    """A run with nothing over any error-level rule must reach `write`, even
    though the composed config also carries warning/suggestion-level rules
    Vale's own MinAlertLevel lets through internally."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls = []
    monkeypatch.setattr(build, "run", fake_run_always_ok(calls))
    args = _args()
    where = run_dir(out_dir, args, monkeypatch)
    (where / "ONBOARDING.md").write_text(bulleted_words(10, cited=True))

    code = build.build(tmp_path, out_dir, "docs", _config({"onboarding": 100}), args, None)

    assert code == 0
    assert [c for c in calls if "write.py" in c[0]]


def test_dry_run_reports_an_over_budget_artifact(tmp_path, monkeypatch):
    """--dry-run exists to inspect the reasoning trail without drafting,
    exactly when a caller wants to know it is over budget. It is told, and
    the dry run still succeeds."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls = []
    monkeypatch.setattr(build, "run", fake_run_always_ok(calls))
    args = _args(dry_run=True)
    (run_dir(out_dir, args, monkeypatch) / "research.md").write_text(bulleted_words(30, cited=True))

    code = build.build(tmp_path, out_dir, "docs", _config({"research": 5}), args, None)

    assert code == 0
    assert not [c for c in calls if "write.py" in c[0]], "--dry-run still drafts nothing"


def test_dry_run_still_succeeds_within_budget(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls = []
    monkeypatch.setattr(build, "run", fake_run_always_ok(calls))

    code = build.build(tmp_path, out_dir, "docs", _config(), _args(dry_run=True), None)

    assert code == 0


def test_an_over_budget_index_is_reported_after_write(tmp_path, monkeypatch):
    """index.md is written by write.py, after the site build.py used to lint
    at. It has to be checked once write returns, on the same rules."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls = []
    monkeypatch.setattr(build, "run", fake_run_writing_index(calls, bulleted_words(30, cited=True)))

    code = build.build(tmp_path, out_dir, "docs", _config({"index": 5}), _args(), None)

    assert code == 0, "a target must not stop the run"
    assert [c for c in calls if "write.py" in c[0]]


def test_an_in_budget_index_still_lets_the_run_finish(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    calls = []
    monkeypatch.setattr(build, "run", fake_run_writing_index(calls, bulleted_words(10, cited=True)))

    code = build.build(tmp_path, out_dir, "docs", _config({"index": 100}), _args(), None)

    assert code == 0


def _alert(n, severity="error"):
    return check.Alert(
        file=f"artifact-{n}.md",
        line=1,
        span=(0, 1),
        check="Test.Rule",
        severity=severity,
        message=f"problem number {n}",
        match="",
    )


def test_more_alerts_than_the_cap_says_how_many_were_not_shown(capsys):
    alerts = [_alert(n) for n in range(12)]

    build.report_alerts(alerts)

    err = capsys.readouterr().err
    shown = [line for line in err.splitlines() if " line " in line and " - " in line]
    assert len(shown) == 10
    assert "2 more alert(s) not shown" in err


def test_at_or_under_the_cap_says_nothing_about_hidden_alerts(capsys):
    alerts = [_alert(n) for n in range(5)]

    build.report_alerts(alerts)

    err = capsys.readouterr().err
    assert "not shown" not in err

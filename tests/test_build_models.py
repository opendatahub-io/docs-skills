"""Per-step model resolution.

One command for every step sends the same model to extract a cited fact and to
decide a document's structure. These are not the same job, so a repository can
name a model per step, and the resolver decides which one a step gets.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_BUILD = REPO_ROOT / "skills" / "docs" / "scripts"
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
for path in (_ENGINE, _BUILD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build  # noqa: E402
from lib.pipeline import config as pipeline_config  # noqa: E402

CONFIG = {"llm_cmd": "base", "llm_cmd_steps": {"plan": "strong", "review": "strong"}}


def test_a_step_with_no_entry_gets_the_global_command():
    assert pipeline_config.llm_cmd_for("write", CONFIG) == "base"


def test_a_named_step_gets_its_own_command():
    assert pipeline_config.llm_cmd_for("plan", CONFIG) == "strong"


def test_a_named_step_outranks_the_environment():
    """`DOCS_LLM_CMD` is the extension sending every step to the session's own
    model. That used to win here, so a repository that named a model for its
    planning step got the session's instead and nothing said so."""
    assert pipeline_config.llm_cmd_for("plan", CONFIG, env="from-env") == "strong"


def test_an_unnamed_step_still_takes_the_environment():
    """The bridge stays the default, so only a pinned step spawns anything."""
    assert pipeline_config.llm_cmd_for("write", CONFIG, env="from-env") == "from-env"


def test_the_environment_outranks_a_general_command():
    """Inside a session the session's model is the general choice, and a config
    file overriding what someone picked with `/model` is not what that key is for."""
    assert pipeline_config.llm_cmd_for("write", {"llm_cmd": "base"}, env="from-env") == "from-env"


def test_a_named_step_may_be_another_runner_entirely():
    """The reason the entry is a command and not a model pattern."""
    config = {"llm_cmd_steps": {"review": "claude -p"}}
    assert pipeline_config.llm_cmd_for("review", config, env="from-env") == "claude -p"


def test_the_command_line_beats_the_environment():
    assert pipeline_config.llm_cmd_for("plan", CONFIG, cli="from-cli", env="from-env") == "from-cli"


def test_an_empty_config_falls_back_to_the_built_in():
    assert pipeline_config.llm_cmd_for("write", {}) == pipeline_config.DEFAULTS["llm_cmd"]


def test_an_empty_per_step_value_does_not_override():
    """A key present but blank is not a choice; it must not beat the global."""
    assert (
        pipeline_config.llm_cmd_for("plan", {"llm_cmd": "base", "llm_cmd_steps": {"plan": ""}})
        == "base"
    )


def test_an_unknown_step_key_is_an_error():
    """A typo left silently in place leaves that step on a model nobody chose,
    which is the failure this project keeps closing."""
    with pytest.raises(ValueError) as excinfo:
        pipeline_config.check_steps({"llm_cmd_steps": {"paln": "strong"}})
    assert "paln" in str(excinfo.value)
    assert "plan" in str(excinfo.value), "the message should name the real steps"


def test_every_known_step_is_accepted():
    pipeline_config.check_steps(
        {"llm_cmd_steps": {step: "x" for step in pipeline_config.MODEL_STEPS}}
    )


def test_a_step_stays_off_unless_named():
    """A step not named in the config was not given a command. Turning one on
    by default would bill every run that was deterministic yesterday."""
    assert pipeline_config.step_is_configured("write", CONFIG) is False
    assert pipeline_config.step_is_configured("review", CONFIG) is True
    assert pipeline_config.step_is_configured("write", {"llm_cmd": "base"}) is False


def test_analyze_is_a_step():
    """`analyze.py` takes a `--llm-cmd` now: it summarizes each module and
    synthesizes the onboarding guide, which is a model call per module."""
    assert "analyze" in pipeline_config.MODEL_STEPS
    pipeline_config.check_steps({"llm_cmd_steps": {"analyze": "strong"}})
    assert "analyze" in pipeline_config.model_table({"llm_cmd_steps": {"analyze": "strong"}})


def test_a_step_no_chain_runs_is_still_rejected():
    """The guard analyze used to demonstrate. A typo here leaves a step on a
    model nobody chose, silently."""
    with pytest.raises(ValueError) as excinfo:
        pipeline_config.check_steps({"llm_cmd_steps": {"reserch": "strong"}})
    assert "reserch" in str(excinfo.value)


def test_the_table_names_where_each_command_came_from():
    table = pipeline_config.model_table(CONFIG)
    assert "plan" in table and "llm_cmd_steps" in table
    assert "write" in table and "llm_cmd" in table


def test_the_table_names_a_pinned_step_over_the_bridge():
    """What `/docs --models` has to show inside a session: which steps
    spawn a command of their own, and which take the session."""
    table = pipeline_config.model_table(CONFIG, None, "python3 ask.py")
    rows = dict(line.split(maxsplit=1) for line in table.splitlines())
    assert "[llm_cmd_steps]" in rows["plan"]
    assert "strong" in rows["plan"]
    assert "[DOCS_LLM_CMD]" in rows["write"]


def test_the_table_says_built_in_when_the_config_is_silent():
    """load_config seeds from DEFAULTS, so an unchanged value is not a choice."""
    table = pipeline_config.model_table({"llm_cmd": pipeline_config.DEFAULTS["llm_cmd"]})
    assert "built-in" in table
    assert "[llm_cmd]" not in table


def test_the_table_covers_every_step_that_can_spend_a_call():
    table = pipeline_config.model_table(CONFIG)
    for step in pipeline_config.MODEL_STEPS:
        assert step in table


def test_models_prints_and_exits_without_touching_the_repository(tmp_path, capsys):
    """It must run before the loop guard and before anything is written."""
    (tmp_path / ".docs-gen.yaml").write_text(
        "generate:\n  llm_cmd: base\n  llm_cmd_steps:\n    plan: strong\n"
    )
    assert build.main(["--repo", str(tmp_path), "--models"]) == 0
    out = capsys.readouterr().out
    assert "plan" in out and "strong" in out
    assert not (tmp_path / ".docs-gen").exists(), "no artifact directory should appear"


def test_a_typo_stops_the_run_before_any_work(tmp_path):
    (tmp_path / ".docs-gen.yaml").write_text("generate:\n  llm_cmd_steps:\n    reveiw: strong\n")
    assert build.main(["--repo", str(tmp_path), "--models"]) == 2


def test_every_skill_frontmatter_parses():
    """A colon followed by a space in an unquoted description breaks the YAML
    and skillsaw rejects the skill. It has happened twice."""
    import yaml

    for skill in sorted((REPO_ROOT / "skills").glob("*/SKILL.md")):
        front = skill.read_text().split("---")[1]
        parsed = yaml.safe_load(front)
        assert isinstance(parsed, dict), skill
        assert parsed.get("name"), skill
        assert parsed.get("description"), skill


def test_the_policy_modules_do_not_print():
    """A library that prints cannot be called from anything with output of its
    own, which is why these were split out of the orchestrator."""
    for name in ("config", "workspace"):
        source = (
            REPO_ROOT / "skills" / "docs-engine" / "scripts" / "lib" / "pipeline" / f"{name}.py"
        ).read_text()
        assert "print(" not in source, f"{name} prints"
        assert "log(" not in source, f"{name} logs"

def test_the_bridge_reads_as_the_session_in_the_table():
    """`python3 '/long/path/ask.py'` says less to a reader than what it does."""
    table = pipeline_config.model_table({}, None, "python3 '/some/where/lib/run/ask.py'")
    assert "the pi session" in table
    assert "ask.py" not in table


def test_a_real_command_is_left_alone():
    assert pipeline_config.readable("claude -p") == "claude -p"
    assert pipeline_config.readable("pi -p -nt --model x") == "pi -p -nt --model x"

"""/docs: which planner mode a run chooses, and what it forwards.

Without a topic the run plans the foundation set, which the gates decide from
the evidence at no model cost. A `--topic` run keeps the planner prompt,
because a subject nobody named cannot be gated for.

The tests read the argv the orchestrator builds rather than running the chain,
which is where the decision actually lives.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs" / "scripts"))

import build  # noqa: E402

_SOURCE = (_ROOT / "skills" / "docs" / "scripts" / "build.py").read_text()


def _plan_block():
    """The argv assembly for the plan step, as source."""
    start = _SOURCE.index("    plan_args = [")
    end = _SOURCE.index('code = run(plan_args, "planning"')
    return _SOURCE[start:end]


def test_a_run_without_a_topic_asks_for_the_foundation_set():
    block = _plan_block()
    assert '"--foundation"' in block
    assert "if topic:" in block and "elif" in block


def test_a_topic_run_keeps_the_planner_prompt():
    """`--topic` and `--foundation` are exclusive: one gates, the other asks."""
    block = _plan_block()
    topic_at = block.index('plan_args += ["--topic", topic]')
    foundation_at = block.index('plan_args.append("--foundation")')
    assert topic_at < foundation_at, "the topic branch must come first"
    assert "elif" in block[topic_at:foundation_at]


def test_configured_skips_are_forwarded_one_flag_each():
    block = _plan_block()
    assert '"--skip-doc"' in block
    assert 'foundation.get("skip")' in block


def test_the_foundation_can_be_switched_off_in_config():
    block = _plan_block()
    assert 'foundation.get("enabled", True)' in block, "absent config must default to enabled"


def test_the_config_key_is_read_from_the_generate_block():
    block = _plan_block()
    assert 'config.get("generate")' in block
    assert '.get("foundation")' in block


def test_build_exposes_the_orchestrator_the_chain_runs():
    assert callable(build.build)

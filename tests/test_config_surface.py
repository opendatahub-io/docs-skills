"""lib/pipeline/config.py: what a run may be configured to do, after the purge.

The ticket and published-docs steps are gone, so the keys that only they read
are gone with them. A repository still carrying one is warned about, not failed
on: the key means nothing now, and a stale config is not a reason to refuse to
document a codebase.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ENGINE = Path(__file__).resolve().parent.parent / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lib.pipeline import config  # noqa: E402


def test_model_steps_are_the_five_that_survive():
    assert config.MODEL_STEPS == ("analyze", "plan", "write", "review", "changelog")


def test_the_retired_helpers_are_gone():
    for name in ("resolve_version", "VersionUnresolved", "ticket_evidence_policy"):
        assert not hasattr(config, name), f"{name} should have gone with the ticket reader"


def test_a_retired_config_key_warns_and_does_not_fail(tmp_path):
    (tmp_path / ".docs-gen.yaml").write_text(
        "generate:\n  product: red_hat_openshift_ai\n  docs_dir: docs\n"
        "  coverage:\n    ticket_evidence: strict\n"
    )
    loaded = config.load_config(tmp_path)
    assert loaded["docs_dir"] == "docs"
    assert "product" in loaded["_warning"]
    assert "coverage" in loaded["_warning"]


def test_a_clean_config_carries_no_warning(tmp_path):
    (tmp_path / ".docs-gen.yaml").write_text("generate:\n  docs_dir: guides\n")
    loaded = config.load_config(tmp_path)
    assert loaded["docs_dir"] == "guides"
    assert not loaded.get("_warning")


def test_an_unknown_per_step_model_key_is_rejected():
    with pytest.raises(ValueError, match="research"):
        config.check_steps({"llm_cmd_steps": {"research": "pi -p"}})


def test_the_sync_defaults_share_one_config_surface():
    """docs-sync had its own DEFAULTS. Two surfaces meant two answers."""
    for key in ("bot_author", "max_modules_per_run", "write_doc_comments", "changelog"):
        assert key in config.DEFAULTS

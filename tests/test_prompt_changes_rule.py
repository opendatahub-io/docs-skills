"""The prompt rule that makes handing the writer commit messages safe.

Commit messages are exactly what would tempt a writer to narrate the page's own
history ("previously this used to..."). The write prompt must say a commit is
evidence for what is true NOW, never history to recount, and must describe the
`changes` block where the other evidence blocks are described.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS = REPO_ROOT / "skills" / "docs-engine" / "prompts"

WRITE_PROMPT = (PROMPTS / "write-topic.md").read_text()


def test_the_write_prompt_forbids_narrating_the_page_s_own_history():
    lowered = WRITE_PROMPT.lower()
    assert "previously" in lowered
    assert "this was formerly" in lowered
    assert "the documentation used to" in lowered


def test_the_write_prompt_forbids_mentioning_a_commit_release_or_rename():
    lowered = WRITE_PROMPT.lower()
    assert "never mention a commit" in lowered
    assert "rename event" in lowered


def test_the_write_prompt_describes_the_changes_block():
    assert "`changes`" in WRITE_PROMPT
    assert "evidence for the present" in WRITE_PROMPT.lower()


def test_the_write_prompt_describes_the_code_block_as_the_spine():
    """A page rests on the repository now, so `code` has to be named as such."""
    lowered = WRITE_PROMPT.lower()
    assert "`code`" in WRITE_PROMPT
    assert "spine of the page" in lowered

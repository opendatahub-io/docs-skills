"""docs-review: every command a tutorial prints is one the repository declares.

A getting-started page whose commands fail is worse than no page. The writer
receives the allowlist as evidence, and this is the half that does not depend
on the model having honoured it.

A command line is not one command. `FOO=1 make build && ./x | tee log` carries
three heads behind a leading assignment, and a parser taking the first token
would pass the assignment and miss the rest.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs-review" / "scripts"))

import review  # noqa: E402

_PAGE = "---\ntitle: G\ntype: procedure\nfoundation: get-started\n---\n\n"


def test_heads_are_found_in_fenced_shell_blocks():
    page = "# T\n\n```bash\nmake build\n```\n\nprose\n\n```console\n$ npm run dev\n```\n"
    assert [head for _, head in review.command_heads(page)] == ["make build", "npm run dev"]


def test_a_compound_line_yields_every_head():
    page = "```bash\nFOO=1 make build && ./bin/x | tee log\n```\n"
    heads = [head for _, head in review.command_heads(page)]
    assert "make build" in heads
    assert "./bin/x" in heads
    assert "tee" in heads
    assert not any(head.startswith("FOO=") for head in heads)


def test_a_non_shell_fence_is_not_read_for_commands():
    page = "```python\nmake_build()\n```\n\n```yaml\nrun: make build\n```\n"
    assert review.command_heads(page) == []


def test_an_undeclared_command_is_a_finding(tmp_path):
    page = tmp_path / "GET-STARTED.md"
    page.write_text(_PAGE + "```bash\nmake deploy\n```\n")
    findings = review.check_commands(page, allowed={"make build"})
    assert len(findings) == 1
    assert findings[0]["kind"] == "command"
    assert findings[0]["severity"] == "warning"
    assert "make deploy" in findings[0]["detail"]
    assert findings[0]["line"] == 8


def test_a_builtin_needs_no_declaration(tmp_path):
    page = tmp_path / "GET-STARTED.md"
    page.write_text(_PAGE + "```bash\ngit clone https://x/y\ncd y\n```\n")
    assert review.check_commands(page, allowed=set()) == []


def test_a_declared_command_passes(tmp_path):
    page = tmp_path / "GET-STARTED.md"
    page.write_text(_PAGE + "```bash\nmake build\n```\n")
    assert review.check_commands(page, allowed={"make build"}) == []


def test_a_prompt_prefix_is_not_mistaken_for_a_command(tmp_path):
    page = tmp_path / "GET-STARTED.md"
    page.write_text(_PAGE + "```console\n$ make build\nok      example/pkg     0.4s\n```\n")
    findings = review.check_commands(page, allowed={"make build"})
    # The output line is not a command, but nothing distinguishes it from one,
    # so it is reported rather than silently trusted. What matters is that the
    # prompt-prefixed command itself resolves.
    assert all("make build" not in finding["detail"] for finding in findings)

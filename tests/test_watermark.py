"""lib/git/git_context.py: the watermark that makes the second run incremental.

`write_watermark(path, module, sha, doc, registry_hash=None)` records one
module per call, which is how docs-sync writes it as it walks the rebuild list.
`read_watermark` returns `{"registry_hash": None, "modules": {}}` for a file
that is not there.

The corrupt-file test pins behaviour this branch does not have yet: the current
`read_watermark` lets `json.JSONDecodeError` escape, so an interrupted write
ends the next run in a traceback rather than a rebuild. Hardening it is part of
the graft.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ENGINE = Path(__file__).resolve().parent.parent / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lib.git import git_context  # noqa: E402


def test_a_written_watermark_reads_back(tmp_path):
    mark = tmp_path / ".docs-state.json"
    git_context.write_watermark(mark, "pkg/queue", "abc1234", "docs/queue.md", registry_hash="h1")
    read = git_context.read_watermark(mark)
    assert read["modules"]["pkg/queue"] == {"sha": "abc1234", "doc": "docs/queue.md"}
    assert read["registry_hash"] == "h1"


def test_a_second_module_joins_the_first(tmp_path):
    mark = tmp_path / ".docs-state.json"
    git_context.write_watermark(mark, "pkg/queue", "abc1234", "docs/queue.md")
    git_context.write_watermark(mark, "pkg/sched", "def5678", "docs/sched.md")
    assert sorted(git_context.read_watermark(mark)["modules"]) == ["pkg/queue", "pkg/sched"]


def test_a_missing_watermark_reads_as_empty(tmp_path):
    read = git_context.read_watermark(tmp_path / "absent.json")
    assert read == {"registry_hash": None, "modules": {}}


def test_a_corrupt_watermark_reads_as_empty_rather_than_raising(tmp_path):
    mark = tmp_path / ".docs-state.json"
    mark.write_text("{not json")
    assert git_context.read_watermark(mark) == {"registry_hash": None, "modules": {}}


def test_normalize_url_strips_the_git_suffix():
    assert git_context.normalize_url("https://github.com/o/p.git") == "https://github.com/o/p"
    assert git_context.normalize_url("https://github.com/o/p") == "https://github.com/o/p"


def test_fetched_survives_the_graft():
    assert callable(git_context.fetched)

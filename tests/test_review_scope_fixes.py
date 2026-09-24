"""docs-review: which document a finding names, and which pages a run judges.

A finding is joined back to its document by the `doc` field, so one check
reporting an absolute build path put its findings on a file nothing else in
the report mentioned. An orphan report is a recommendation to delete, so a
run that judges pages it never planned recommends deleting work that is fine.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs-review" / "scripts"))

import review  # noqa: E402

_PAGE = "---\ntitle: G\ntype: procedure\nfoundation: get-started\n---\n\n"
_GENERATED = (
    "---\ntitle: {title}\nmanaged: generated\ngenerator: docs-skills/0.4.2\n"
    "source_sha: abc1234\n{extra}---\n\n# {title}\n"
)


def test_a_command_finding_names_the_document_the_way_every_other_check_does(tmp_path):
    """`repo` is resolved, so passing the page's absolute path put a build
    directory in review.json and split this page's findings off from its own
    frontmatter and grounding findings."""
    page = tmp_path / "docs" / "GET-STARTED.md"
    page.parent.mkdir(parents=True)
    text = _PAGE + "```bash\nmake deploy\n```\n"
    page.write_text(text)
    findings = review.check_commands("docs/GET-STARTED.md", {"make build"}, text)
    assert [finding["doc"] for finding in findings] == ["docs/GET-STARTED.md"]


def test_the_page_is_not_read_twice_when_the_caller_holds_it(tmp_path):
    findings = review.check_commands("docs/GET-STARTED.md", set(), "```bash\nmake deploy\n```\n")
    assert len(findings) == 1


def test_a_docker_command_resolves_against_the_allowlist():
    """`docker build -t x .` reduces to a two-word head the way every other
    runner taking a subcommand does."""
    heads = [head for _, head in review.command_heads("```bash\ndocker build -t x .\n```\n")]
    assert heads == ["docker build"]


def test_an_interpreter_and_a_pipe_utility_pass_with_no_manifest():
    page = "```bash\npython3 -m venv .venv\ncat a | grep b\n```\n"
    assert review.check_commands("docs/GET-STARTED.md", set(), page) == []


# ----------------------------------------------------------- orphan scope


def _tree(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text(
        _GENERATED.format(title="Architecture", extra="foundation: architecture\n")
    )
    (docs / "pkg__queue.md").write_text(_GENERATED.format(title="Queue", extra=""))
    return tmp_path


def test_a_foundation_run_does_not_call_a_topic_page_rubbish(tmp_path):
    """A foundation run plans the five documents and nothing else, so the
    pages an earlier `--topic` run left are not unclaimed by it. Reporting
    them told a maintainer to delete them with `--prune-orphans`."""
    found = review.orphans(
        _tree(tmp_path), "docs", claimed={"docs/ARCHITECTURE.md"}, foundation_run=True
    )
    assert [entry["doc"] for entry in found] == []


def test_a_foundation_run_still_reports_a_foundation_page_nothing_claims(tmp_path):
    found = review.orphans(_tree(tmp_path), "docs", claimed=set(), foundation_run=True)
    assert [entry["doc"] for entry in found] == ["docs/ARCHITECTURE.md"]


def test_a_topic_run_is_in_no_position_to_judge_the_foundation_set(tmp_path):
    found = review.orphans(
        _tree(tmp_path), "docs", claimed={"docs/pkg__queue.md"}, foundation_run=False
    )
    assert [entry["doc"] for entry in found] == []

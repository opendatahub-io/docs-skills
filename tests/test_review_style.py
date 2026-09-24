"""The style judgment pass.

Deterministic checks run first and Vale runs before them. What reaches a model
is only what neither could decide, which is the whole reason this call is worth
its tokens.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_REVIEW = REPO_ROOT / "skills" / "docs-review" / "scripts"
if str(_REVIEW) not in sys.path:
    sys.path.insert(0, str(_REVIEW))

import review  # noqa: E402


def reply(*findings):
    calls = []

    def run_step(prompt_text, payload, schema, command, timeout, retries=1, values=None):
        calls.append((prompt_text, payload, schema, values))
        return {"findings": list(findings)}, 1

    run_step.calls = calls
    return run_step


def test_a_finding_becomes_a_warning(monkeypatch):
    """A model's reading of tone is advice. It must not block a run by itself."""
    monkeypatch.setattr(
        review.step, "run_step", reply({"topic": "tables", "quote": "q", "fix": "f"})
    )
    out = review.judge_style("docs/a.md", "body", "fake", 10)
    assert [f["severity"] for f in out] == ["warning"]
    assert out[0]["kind"] == "style"
    assert out[0]["topic"] == "tables"


def test_preview_status_is_a_suggestion(monkeypatch):
    """Unannounced preview status is useful context, not a warning-level gate."""
    monkeypatch.setattr(
        review.step,
        "run_step",
        reply({"topic": "preview technology", "quote": "q", "fix": "f"}),
    )
    out = review.judge_style("docs/a.md", "body", "fake", 10)
    assert [f["severity"] for f in out] == ["suggestion"]


def test_a_clean_page_produces_nothing(monkeypatch):
    monkeypatch.setattr(review.step, "run_step", reply())
    assert review.judge_style("docs/a.md", "body", "fake", 10) == []


def test_the_detail_stays_short(monkeypatch):
    """A finding that quotes half the page costs more than it reports."""
    monkeypatch.setattr(
        review.step,
        "run_step",
        reply({"topic": "minimalism", "quote": "x" * 400, "fix": "y" * 400}),
    )
    assert len(review.judge_style("docs/a.md", "body", "fake", 10)[0]["detail"]) < 320


def test_the_body_is_capped_and_the_cut_is_declared(monkeypatch):
    """A model handed a prefix it does not know is a prefix will judge a
    half-built table as a broken one."""
    stub = reply()
    monkeypatch.setattr(review.step, "run_step", stub)
    body = "\n".join(f"line {i} of the page" for i in range(500))
    review.judge_style("docs/a.md", body, "fake", 10, limit=100)
    sent = stub.calls[0][1]
    assert len(sent["body"]) <= 120
    assert sent["body"].endswith("[truncated]\n")
    assert sent["truncated"] is True


def test_a_short_body_is_sent_whole_and_flagged_untruncated(monkeypatch):
    stub = reply()
    monkeypatch.setattr(review.step, "run_step", stub)
    review.judge_style("docs/a.md", "a short page", "fake", 10)
    assert stub.calls[0][1]["body"] == "a short page"
    assert stub.calls[0][1]["truncated"] is False


def test_the_cut_lands_on_a_line_boundary(monkeypatch):
    stub = reply()
    monkeypatch.setattr(review.step, "run_step", stub)
    review.judge_style("docs/a.md", "aaaa\nbbbb\ncccc\ndddd\n", "fake", 10, limit=12)
    assert "\naaaa\nbbbb" not in stub.calls[0][1]["body"].replace("aaaa\nbbbb", "")
    assert stub.calls[0][1]["body"].startswith("aaaa\nbbbb")


def test_the_topics_reach_the_model_from_their_one_source(monkeypatch):
    """The prompt carries framing and a placeholder. Everything a reviewer is
    asked to judge comes from style-topics.md, so nothing restates it."""
    stub = reply()
    monkeypatch.setattr(review.step, "run_step", stub)
    review.judge_style("docs/a.md", "body", "fake", 10)

    prompt_text, _, _, values = stub.calls[0]
    assert prompt_text == (review.PROMPTS / "judge-style.md").read_text()

    rendered = review.step.render(prompt_text, review.step.build_values({}, values))
    assert "{{topics}}" not in rendered
    topics = review.TOPICS.read_text()
    ids = review.style_topic_ids(topics)
    assert ids

    # The heading has to end where the id ends. A prefix match passed a heading
    # carrying a trailing space, and a model that echoed it back failed the
    # enum the same run had just built from the stripped form.
    headings = re.findall(r"^### (.*)$", rendered, re.M)
    assert headings == ids


def test_the_schema_enum_is_built_from_the_topic_headings(monkeypatch):
    """A finding under a topic the caller has never heard of cannot be
    rendered, so the list the model may name is the list that was sent."""
    stub = reply()
    monkeypatch.setattr(review.step, "run_step", stub)
    review.judge_style("docs/a.md", "body", "fake", 10)

    _, _, schema, _ = stub.calls[0]
    enum = schema["properties"]["findings"]["items"]["properties"]["topic"]["enum"]
    assert enum == review.style_topic_ids(review.TOPICS.read_text())
    assert enum, "a run with no topics must not reach a model at all"

    committed = json.loads((review.SCHEMAS / "judge-style-out.json").read_text())
    topic = committed["properties"]["findings"]["items"]["properties"]["topic"]
    assert "enum" not in topic, "the committed schema must not carry a second copy of the ids"
    assert topic.get("minLength") == 1, "step.py runs this schema without docs-review's enum"


def test_no_other_file_restates_a_topic():
    """The point of the extraction: one place to edit a rule."""
    topics = review.TOPICS.read_text()
    bodies = re.findall(r"^## [^\n]+\n\n(.*?)(?=^## |\Z)", topics, re.MULTILINE | re.DOTALL)
    assert len(bodies) == len(review.style_topic_ids(topics))

    others = [
        (REPO_ROOT / "skills" / "docs-style" / "SKILL.md").read_text(),
        (review.PROMPTS / "judge-style.md").read_text(),
    ]
    # Every line, not just the first: five of the six bullets under `procedures`
    # could be copied out wholesale while a first-line check stayed green.
    for body in bodies:
        for line in body.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            for other in others:
                assert line not in other, line


def test_a_missing_prompt_warns_rather_than_crashing(monkeypatch, tmp_path):
    """A damaged checkout still completes its other review passes."""
    monkeypatch.setattr(review, "PROMPTS", tmp_path)
    out = review.judge_style("docs/a.md", "body", "fake", 10)
    assert [f["kind"] for f in out] == ["style-unavailable"]
    assert "judge-style.md" in out[0]["detail"]


def test_the_warning_names_the_file_that_is_actually_missing(monkeypatch, tmp_path):
    """It named the prompt whichever file was gone, so the one file the
    operator was told to check was the one file still on disk."""
    monkeypatch.setattr(review, "TOPICS", tmp_path / "style-topics.md")
    out = review.judge_style("docs/a.md", "body", "fake", 10)
    assert "style-topics.md" in out[0]["detail"]
    assert "judge-style.md" not in out[0]["detail"]


def test_a_schema_without_a_topic_property_warns_rather_than_aborting(monkeypatch, tmp_path):
    """main() catches StepError and RuntimeError. A KeyError from indexing five
    levels into the schema escaped both and took the whole run down with it,
    discarding every deterministic finding already paid for."""
    monkeypatch.setattr(review, "SCHEMAS", tmp_path)
    (tmp_path / "judge-style-out.json").write_text('{"type": "object"}')
    out = review.judge_style("docs/a.md", "body", "fake", 10)
    assert [f["kind"] for f in out] == ["style-unavailable"]
    assert "judge-style-out.json" in out[0]["detail"]

    # A half-written file is the same story as a malformed one.
    (tmp_path / "judge-style-out.json").write_text('{"properties": {"find')
    out = review.judge_style("docs/a.md", "body", "fake", 10)
    assert [f["kind"] for f in out] == ["style-unavailable"]


def test_every_topic_id_survives_the_extension_renderer():
    """docs.ts splits `topic: quote - fix` back apart to build the two-line
    finding. An id its pattern cannot match loses that hierarchy silently, so
    the constraint is read from the extension rather than restated here."""
    source = (REPO_ROOT / "extensions" / "docs.ts").read_text()
    literal = re.search(r"^const FINDING_TOPIC = /(.+)/([a-z]*);$", source, re.M)
    assert literal, "docs.ts no longer declares FINDING_TOPIC as a regex literal"
    pattern = re.compile(literal.group(1), re.I if "i" in literal.group(2) else 0)

    for topic_id in review.style_topic_ids(review.TOPICS.read_text()):
        assert pattern.match(f"{topic_id}: a quote - a fix"), topic_id


def test_the_preamble_holds_no_heading_the_topics_would_absorb():
    """The topics begin at the first `##` heading, which is the file's own
    stated contract. A preamble line that opened one would be read as a topic
    and would reach both the prompt and the enum as a bogus id."""
    topics = review.TOPICS.read_text()
    match = review.TOPIC_HEADING.search(topics)
    assert match, "style-topics.md carries no topic headings"
    assert review.style_topic_ids(topics[: match.start()]) == []


def _repo(tmp_path, managed="generated"):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    body = " ".join(f"word{i}" for i in range(60))
    (repo / "docs" / "a.md").write_text(
        f"---\nmanaged: {managed}\ndescription: d\nsource_sha: abc1234\n---\n\n# A\n\n{body}\n"
    )
    out = tmp_path / "out"
    out.mkdir()
    return repo, out


def test_the_pass_does_not_run_without_a_model(tmp_path, monkeypatch):
    repo, out = _repo(tmp_path)

    def explode(*a, **k):
        raise AssertionError("a model was called without --llm-cmd")

    monkeypatch.setattr(review.step, "run_step", explode)
    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs"])
    assert json.loads((out / "review.json").read_text())["style_judged"] == 0


def test_no_style_switches_the_pass_off(tmp_path, monkeypatch):
    repo, out = _repo(tmp_path)

    def explode(*a, **k):
        raise AssertionError("a model was called despite --no-style")

    monkeypatch.setattr(review.step, "run_step", explode)
    review.main(
        [
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--docs-dir",
            "docs",
            "--llm-cmd",
            "fake",
            "--no-style",
        ]
    )
    assert json.loads((out / "review.json").read_text())["style_judged"] == 0


def test_a_manual_page_is_never_judged(tmp_path, monkeypatch):
    """Hand-written prose is not the writer's to restyle."""
    repo, out = _repo(tmp_path, managed="manual")
    monkeypatch.setattr(review.step, "run_step", reply())
    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--llm-cmd", "fake"])
    assert json.loads((out / "review.json").read_text())["style_judged"] == 0


def test_a_generated_page_is_judged_and_recorded(tmp_path, monkeypatch):
    repo, out = _repo(tmp_path)
    monkeypatch.setattr(
        review.step, "run_step", reply({"topic": "headings", "quote": "A", "fix": "Name it."})
    )
    code = review.main(
        ["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--llm-cmd", "fake"]
    )
    report = json.loads((out / "review.json").read_text())
    assert report["style_judged"] == 1
    assert any(f["kind"] == "style" for f in report["findings"])
    assert code == 0, "a style warning alone must not block"


def test_a_style_warning_blocks_only_under_strict(tmp_path, monkeypatch):
    repo, out = _repo(tmp_path)
    monkeypatch.setattr(
        review.step, "run_step", reply({"topic": "headings", "quote": "A", "fix": "Name it."})
    )
    code = review.main(
        [
            "--repo",
            str(repo),
            "--out",
            str(out),
            "--docs-dir",
            "docs",
            "--llm-cmd",
            "fake",
            "--strict",
        ]
    )
    assert code == 3


def test_a_failing_model_is_a_warning_not_a_crash(tmp_path, monkeypatch):
    repo, out = _repo(tmp_path)

    def boom(*a, **k):
        raise review.step.StepError(["the model returned nothing usable"], "")

    monkeypatch.setattr(review.step, "run_step", boom)
    code = review.main(
        ["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--llm-cmd", "fake"]
    )
    report = json.loads((out / "review.json").read_text())
    assert any(f["kind"] == "style-failed" for f in report["findings"])
    assert code == 0


def test_a_stub_page_is_not_worth_a_model_call(tmp_path, monkeypatch):
    """The claims pass skips a document with nothing to check. This one had no
    equivalent, so enabling --llm-cmd billed a call for every page."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "stub.md").write_text(
        "---\nmanaged: generated\ndescription: d\nsource_sha: abc1234\n---\n\n# Stub\n\nTBD.\n"
    )
    out = tmp_path / "out"
    out.mkdir()

    def explode(*a, **k):
        raise AssertionError("a stub page was sent to a model")

    monkeypatch.setattr(review.step, "run_step", explode)
    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--llm-cmd", "fake"])
    assert json.loads((out / "review.json").read_text())["style_judged"] == 0


def test_a_page_with_no_managed_field_is_not_billed(tmp_path, monkeypatch):
    """check_frontmatter treats an absent managed field as manual. Billing a
    model for a page the rest of the tool will not touch is the wrong
    default."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    body = " ".join(f"word{i}" for i in range(60))
    (repo / "docs" / "a.md").write_text(f"---\ndescription: d\n---\n\n# A\n\n{body}\n")
    out = tmp_path / "out"
    out.mkdir()

    def explode(*a, **k):
        raise AssertionError("an un-onboarded page was sent to a model")

    monkeypatch.setattr(review.step, "run_step", explode)
    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--llm-cmd", "fake"])
    assert json.loads((out / "review.json").read_text())["style_judged"] == 0


def test_style_judged_counts_calls_not_documents(tmp_path, monkeypatch):
    """judged += 1 used to run before the call, so a checkout with no prompt
    reported a pass per document while making no model call at all."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    body = " ".join(f"word{i}" for i in range(60))
    for name in ("a.md", "b.md"):
        (repo / "docs" / name).write_text(
            f"---\nmanaged: generated\ndescription: d\nsource_sha: abc1234\n---\n\n# A\n\n{body}\n"
        )
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(review, "PROMPTS", tmp_path)
    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--llm-cmd", "fake"])
    report = json.loads((out / "review.json").read_text())
    assert report["style_judged"] == 0
    unavailable = [f for f in report["findings"] if f["kind"] == "style-unavailable"]
    assert len(unavailable) == 1, "one cause, one warning, not one per document"


def test_missing_topics_warn_once_for_the_run_too(tmp_path, monkeypatch):
    """The preflight checked the prompt and the schema after judge_style had
    grown a third input, so a checkout carrying two of the three files billed a
    pass per page in the report and warned once per page on the way."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    body = " ".join(f"word{i}" for i in range(60))
    for name in ("a.md", "b.md", "c.md"):
        (repo / "docs" / name).write_text(
            f"---\nmanaged: generated\ndescription: d\nsource_sha: abc1234\n---\n\n# A\n\n{body}\n"
        )
    out = tmp_path / "out"
    out.mkdir()

    def explode(*a, **k):
        raise AssertionError("a model was called with no topics to judge against")

    monkeypatch.setattr(review.step, "run_step", explode)
    monkeypatch.setattr(review, "TOPICS", tmp_path / "style-topics.md")
    review.main(["--repo", str(repo), "--out", str(out), "--docs-dir", "docs", "--llm-cmd", "fake"])
    report = json.loads((out / "review.json").read_text())
    assert report["style_judged"] == 0
    unavailable = [f for f in report["findings"] if f["kind"] == "style-unavailable"]
    assert len(unavailable) == 1, "one cause, one warning, not one per document"
    assert "style-topics.md" in unavailable[0]["detail"]

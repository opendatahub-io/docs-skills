"""The ownership contract: fenced regions, the churn floor, and language files.

The guarantees here are the ones the plan puts in scripts rather than prompts,
because trust in generated documentation is lost permanently the first time a
hand-written paragraph is overwritten.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
ENGINE = _ROOT / "skills" / "docs-engine"
sys.path.insert(0, str(ENGINE / "scripts"))

from lib.md import fences, language_file, render  # noqa: E402

ASSISTED = """---
title: Scheduler
managed: assisted
---
# Scheduler

A paragraph a human wrote and cares about. <!-- an ordinary comment -->

<!-- docs-gen:begin section=api source=pkg/scheduler sha=a1b2c3d -->
generated body
<!-- docs-gen:end -->

Closing prose, also a human's.

  <!-- docs-gen:begin section=deps source=pkg/scheduler -->
  indented generated body
  <!-- docs-gen:end -->

Trailing line.
"""


# ------------------------------------------------------------------ fences


def test_parse_finds_every_region_in_order():
    regions = fences.parse(ASSISTED)
    assert [r.section for r in regions] == ["api", "deps"]
    assert regions[0].source == "pkg/scheduler"
    assert regions[0].sha == "a1b2c3d"
    assert regions[1].sha is None


def test_replace_leaves_every_byte_outside_the_region():
    after = fences.replace(ASSISTED, "api", "fresh body", sha="9f8e7d6")
    assert "A paragraph a human wrote and cares about." in after
    assert "<!-- an ordinary comment -->" in after
    assert "Closing prose, also a human's." in after
    assert "Trailing line." in after
    assert "generated body" not in after.split("section=deps")[0]
    assert fences.outside(ASSISTED) == fences.outside(after)


def test_replace_stamps_the_new_sha_on_the_marker():
    after = fences.replace(ASSISTED, "api", "fresh", sha="9f8e7d6")
    assert "section=api source=pkg/scheduler sha=9f8e7d6" in after


def test_replace_preserves_indentation():
    after = fences.replace(ASSISTED, "deps", "  a\n  b", sha="9f8e7d6")
    marker = [ln for ln in after.splitlines() if "section=deps" in ln][0]
    assert marker.startswith("  <!--")
    assert "  <!-- docs-gen:end -->" in after


def test_replace_is_idempotent():
    once = fences.replace(ASSISTED, "api", "fresh body", sha="9f8e7d6")
    twice = fences.replace(once, "api", "fresh body", sha="9f8e7d6")
    assert once == twice


def test_replace_refuses_an_unknown_section():
    with pytest.raises(fences.FenceError, match="no region with section"):
        fences.replace(ASSISTED, "nope", "x")


@pytest.mark.parametrize(
    "broken,reason",
    [
        ("<!-- docs-gen:begin section=a -->\nx\n", "never closed"),
        ("<!-- docs-gen:end -->\n", "with no begin"),
        (
            "<!-- docs-gen:begin section=a -->\n"
            "<!-- docs-gen:begin section=b -->\nx\n<!-- docs-gen:end -->\n",
            "nested",
        ),
        (
            "<!-- docs-gen:begin section=a -->\nx\n<!-- docs-gen:end -->\n"
            "<!-- docs-gen:begin section=a -->\ny\n<!-- docs-gen:end -->\n",
            "two regions claim",
        ),
        ("<!-- docs-gen:begin source=x -->\ny\n<!-- docs-gen:end -->\n", "no section"),
    ],
)
def test_parse_rejects_structure_it_cannot_rewrite_safely(broken, reason):
    with pytest.raises(fences.FenceError, match=reason):
        fences.parse(broken)


def test_stale_reports_regions_behind_the_head():
    assert [r.section for r in fences.stale(ASSISTED, "9f8e7d6ab")] == ["api", "deps"]
    fresh = fences.replace(ASSISTED, "api", "x", sha="9f8e7d6")
    assert [r.section for r in fences.stale(fresh, "9f8e7d6ab")] == ["deps"]


# ------------------------------------------------------------------ rendering


PAYLOAD = {
    "path": "docs/scheduler.md",
    "frontmatter": {
        "title": "Scheduler",
        "description": "Queues and retries jobs: at most once",
        "type": "concept",
        "managed": "generated",
    },
    "sections": [
        {"id": "purpose", "heading": "What it does", "body": "Owns job admission."},
        {"id": "design", "heading": "Design", "body": "Two queues.", "level": 3},
    ],
}


def test_document_is_byte_identical_across_runs():
    assert render.document(PAYLOAD) == render.document(PAYLOAD)


def test_document_honours_section_levels():
    text = render.document(PAYLOAD)
    assert "## What it does" in text
    assert "### Design" in text


def test_document_quotes_a_description_containing_a_colon():
    assert "description: 'Queues and retries jobs: at most once'" in render.document(PAYLOAD)


def test_worth_writing_rejects_a_one_line_reword():
    """Nondeterministic prose churn must not open a pull request."""
    before = render.document(PAYLOAD)
    after = before.replace("Two queues.", "Two queues!")
    write, reason = render.worth_writing(before, after)
    assert write is False
    assert "below floor" in reason


def test_worth_writing_rejects_a_frontmatter_only_change():
    before = render.document(PAYLOAD)
    after = before.replace("managed: generated", "managed: generated\nsource_sha: abc123")
    assert render.worth_writing(before, after) == (False, "frontmatter only")


def test_worth_writing_accepts_a_new_section():
    before = render.document(PAYLOAD)
    plus = dict(PAYLOAD)
    plus["sections"] = PAYLOAD["sections"] + [
        {"id": "errors", "heading": "Failure modes", "body": "Rejects on overflow."}
    ]
    write, reason = render.worth_writing(before, render.document(plus))
    assert write is True
    assert "structure" in reason


def test_worth_writing_accepts_a_new_file():
    assert render.worth_writing(None, render.document(PAYLOAD))[0] is True


def test_merge_front_never_demotes_a_manual_file():
    """A human promoting a page to `manual` must survive the next run."""
    merged = render.merge_front(
        {"managed": "manual", "owner": "a@b.c"}, {"managed": "generated", "title": "T"}
    )
    assert merged["managed"] == "manual"
    assert merged["owner"] == "a@b.c"


# ------------------------------------------------------------- language files


def test_every_shipped_language_file_validates():
    """A contributor adding a language finds out here, not in a generation run."""
    catalogue = language_file.load_all(ENGINE / "languages")
    assert catalogue, "no language files found"
    for name, lang in catalogue.items():
        assert lang.language == name
        assert lang.extensions
        assert lang.doc_types("library")


def test_language_file_resolves_by_name_and_extension():
    assert language_file.for_language("python").language == "python"
    assert language_file.for_language(".go").language == "go"
    assert language_file.for_language("py").language == "python"


def test_language_file_renders_its_generator_command():
    py = language_file.for_language("python")
    assert py.generator_command(out="site", package="mypkg") == (
        "pdoc --output-directory site mypkg"
    )


def test_doc_comments_are_not_writable_by_default():
    """Writing doc comments into source is a code PR, a different risk class."""
    for lang in language_file.load_all(ENGINE / "languages").values():
        assert lang.writes_doc_comments is False


def test_unknown_module_kind_falls_back_to_library():
    py = language_file.for_language("python")
    assert py.doc_types("something-else") == py.doc_types("library")


def test_load_rejects_frontmatter_that_fails_the_schema(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("---\nlanguage: rust\n---\n\nbody\n")
    with pytest.raises(language_file.LanguageFileError, match="artifacts"):
        language_file.load(bad)


def test_load_rejects_a_file_with_no_frontmatter(tmp_path):
    bad = tmp_path / "bare.md"
    bad.write_text("# Just prose\n")
    with pytest.raises(language_file.LanguageFileError, match="no YAML frontmatter"):
        language_file.load(bad)

"""The heading tree of a Markdown document, keyed on dotted section numbers.

Structure comes from the dotted number rather than the `#` depth, because a
renderer may flatten every heading to `###` whatever its real level. A heading
can carry U+00A0 after its number, and inside a phrase like `Red\xa0Hat`, so
the parser must never treat that character as a delimiter.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_ENGINE = REPO_ROOT / "skills" / "docs-engine" / "scripts"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from lib.md import sections  # noqa: E402

GUIDE = (
    "### Deploy and serve large language models at scale in Red\xa0Hat OpenShift AI\n"
    "\n"
    "Intro prose.\n"
    "\n"
    "### 1.1.\xa0Enable Distributed Inference with llm-d\n"
    "\n"
    "Enable it.\n"
    "\n"
    "### 8.3.\xa0Inference scheduling\n"
    "\n"
    "Scheduling prose.\n"
    "\n"
    "#### 8.3.3.\xa0Intelligent inference scheduler with KV cache routing\n"
    "\n"
    "You can configure the scheduler to track KV cache blocks.\n"
    "\n"
    "#### 8.3.4.\xa0Something else\n"
    "\n"
    "Other prose.\n"
    "\n"
    "### 9.1.\xa0A later chapter\n"
    "\n"
    "Later prose.\n"
)


def test_an_unnumbered_heading_is_the_guide_title():
    parsed = sections.parse(GUIDE)
    assert parsed[0].number == ""
    assert parsed[0].title.startswith("Deploy and serve")
    assert parsed[0].depth == 0


def test_depth_comes_from_the_number_not_the_hash_count():
    """`### 8.3.` and `#### 8.3.3.` both render at their own hash depth, and
    the real hierarchy is 2 and 3."""
    by_number = {s.number: s for s in sections.parse(GUIDE)}
    assert by_number["8.3"].depth == 2
    assert by_number["8.3.3"].depth == 3


def test_the_title_keeps_its_non_breaking_spaces():
    parsed = sections.parse(GUIDE)
    assert "Red\xa0Hat" in parsed[0].title


def test_a_subtree_ends_at_its_next_sibling():
    body = sections.subtree(GUIDE, "8.3.3")
    assert "track KV cache blocks" in body
    assert "Something else" not in body


def test_a_subtree_includes_its_children():
    body = sections.subtree(GUIDE, "8.3")
    assert "Intelligent inference scheduler" in body
    assert "Something else" in body
    assert "A later chapter" not in body


def test_a_subtree_ends_at_a_shallower_number():
    """8.3.4 is followed by 9.1, which is shallower, so the subtree stops."""
    body = sections.subtree(GUIDE, "8.3.4")
    assert "Other prose" in body
    assert "A later chapter" not in body


def test_an_unknown_section_has_no_subtree():
    assert sections.subtree(GUIDE, "42.1") is None


def test_replace_swaps_one_subtree_and_leaves_the_rest_byte_identical():
    new = "#### 8.3.3.\xa0Intelligent inference scheduler\n\nRewritten.\n"
    out = sections.replace(GUIDE, "8.3.3", new)
    assert "Rewritten." in out
    assert "track KV cache blocks" not in out
    assert "A later chapter" in out
    assert out.startswith("### Deploy and serve")


def test_replacing_an_unknown_section_raises():
    try:
        sections.replace(GUIDE, "42.1", "x")
    except sections.SectionError as exc:
        assert "42.1" in str(exc)
    else:
        raise AssertionError("replacing an absent section must raise")


def test_the_tree_the_model_sees_is_numbers_and_titles():
    """A 64,803-word guide has to reach the model as its heading tree."""
    rendered = sections.tree_lines(sections.parse(GUIDE))
    assert "8.3.3" in rendered
    assert "Intelligent inference scheduler" in rendered
    assert "track KV cache blocks" not in rendered


def test_the_tree_names_chapters_that_have_no_heading_of_their_own():
    """Chapter 8 is never rendered as a heading; it exists in the numbering."""
    rendered = sections.tree_lines(sections.parse(GUIDE))
    assert "Chapter 8" in rendered
    assert "Chapter 9" in rendered


# --- fix round 1: a renderer may emit chapter-level headings as Setext, not
# ATX. `parse` must recognise them or a subtree/replace at the last numbered
# heading of one chapter silently swallows the whole of the next chapter.


def test_a_setext_equals_line_is_the_guide_title():
    text = "My Guide\n========\n\nProse.\n"
    parsed = sections.parse(text)
    assert parsed[0].number == ""
    assert parsed[0].title == "My Guide"
    assert parsed[0].depth == 0


def test_a_numbered_setext_heading_parses_its_chapter_number_and_strips_the_prefix():
    text = (
        "My Guide\n========\n\n"
        "Chapter\xa04.\xa0Configure authentication for Distributed Inference with llm-d\n"
        "----------------------------------------------------------------------------\n\n"
        "Prose.\n"
    )
    chapter = sections.parse(text)[-1]
    assert chapter.number == "4"
    assert chapter.depth == 1
    assert chapter.title == "Configure authentication for Distributed Inference with llm-d"
    assert not chapter.title.startswith("Chapter")


def test_an_unnumbered_setext_heading_bounds_a_preceding_subtree():
    """`Preface` carries no number, but it must still stop the subtree before it."""
    text = (
        "My Guide\n========\n\n"
        "### 1.1.\xa0First topic\n\n"
        "First topic prose.\n\n"
        "Preface\n-------\n\n"
        "Preface prose that must not leak into 1.1's subtree.\n"
    )
    body = sections.subtree(text, "1.1")
    assert "First topic prose" in body
    assert "Preface prose" not in body


def test_a_table_delimiter_row_is_not_a_setext_heading():
    text = (
        "My Guide\n========\n\n"
        "| Col A | Col B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
        "\n"
        "### 1.1.\xa0Real heading\n\n"
        "Body.\n"
    )
    parsed = sections.parse(text)
    assert [s.number for s in parsed] == ["", "1.1"]
    assert not any("Col" in s.title for s in parsed)


def test_a_fence_marker_sharing_a_line_with_a_definition_list_colon_still_toggles():
    """A definition list can open its fenced body on the same line as its
    `:` marker (`:   ```), which a naive `line.strip().startswith('```')`
    check misses. Missing that one open desyncs fence tracking for the rest
    of the document, and a real heading further down gets skipped as if it
    were still inside a fence."""
    text = (
        "My Guide\n========\n\n"
        "**Term**\n"
        ":   ```\n"
        "    plugins:\n"
        "    - type: foo\n"
        "    ```\n"
        "\n"
        "### 2.1.\xa0Real heading after the fenced definition\n\n"
        "Body.\n"
    )
    parsed = sections.parse(text)
    assert parsed[-1].number == "2.1"


def test_bounds_returns_none_for_an_unknown_number():
    assert sections.bounds(sections.parse(GUIDE), "42.1") is None


def test_bounds_returns_none_for_an_empty_number():
    """An empty number is what a blank model answer, or Section.number of any
    unnumbered heading, looks like. It must never match the depth-0 guide
    title and hand back the whole document as a "subtree"."""
    assert sections.bounds(sections.parse(GUIDE), "") is None


def test_replacing_the_empty_number_raises_instead_of_replacing_the_whole_guide():
    try:
        sections.replace(GUIDE, "", "x")
    except sections.SectionError:
        pass
    else:
        raise AssertionError("replace(text, '', ...) must raise, not replace everything")


def test_replace_of_a_sections_own_subtree_round_trips_byte_identically():
    """The core promise of this module: cut a subtree out, put the same bytes
    back, and the document is unchanged."""
    body = sections.subtree(GUIDE, "8.3")
    assert sections.replace(GUIDE, "8.3", body) == GUIDE


# --- fix round 1: the writer never hands `replace` the raw bytes `subtree`
# returned. It runs them through `render.normalize` first, which strips
# leading and trailing whitespace, so the blank line `subtree` always leaves
# at its own end (the one separating it from whatever comes next) is gone by
# the time `replace` sees the body. `replace` must restore that boundary
# itself, or an untouched section comes back with its next heading glued on.


def test_replace_round_trips_through_the_writers_normalize():
    """Echoing a subtree back unmodified, the way the writer's own draft does
    when a model changes nothing, must reproduce the guide byte for byte even
    after `render.normalize` has stripped the body's edges."""
    from lib.md import render

    body = render.normalize(sections.subtree(GUIDE, "8.3.3"))
    assert sections.replace(GUIDE, "8.3.3", body) == GUIDE


# --- fix round 2: the round-1 fix restored the blank line unconditionally,
# so it ADDED one where the guide never had one. The boundary must be read
# from the guide being edited, not imposed by `replace` itself.


def test_replace_round_trips_when_headings_are_not_blank_line_separated():
    """Not every guide blank-line-separates its headings. A subtree whose own
    original span ended with no blank line must come back with none, even
    after the same normalize the writer applies."""
    from lib.md import render

    text = "### 1.1.\xa0A\n\nProse A.\n### 1.2.\xa0B\n\nProse B.\n"
    raw = sections.subtree(text, "1.1")
    assert sections.replace(text, "1.1", raw) == text

    normalized = render.normalize(raw)
    assert sections.replace(text, "1.1", normalized) == text


def test_a_tilde_fence_is_recognised_and_hides_headings_inside_it():
    """`~~~` is a valid fence delimiter too. Missing it means a heading-shaped
    line inside one gets treated as real, truncating the subtree early."""
    text = (
        "My Guide\n========\n\n"
        "### 1.1.\xa0A\n\n"
        "~~~\n"
        "### 1.2.\xa0Not a real heading, just fenced example text\n"
        "~~~\n\n"
        "Trailing prose that belongs to 1.1.\n"
    )
    body = sections.subtree(text, "1.1")
    assert "Trailing prose" in body
    assert "Not a real heading" in body


def test_a_longer_fence_is_not_closed_by_a_shorter_embedded_run():
    """A ```` block (4 backticks) can safely contain a bare ``` (3 backticks)
    as literal content; only a run of 4 or more of the same character closes
    it. A naive toggle-on-any-run closes early and misreads what follows."""
    text = "My Guide\n========\n\n### 1.1.\xa0A\n\n````\n```\n````\n\n### 1.2.\xa0B\n\nBody two.\n"
    parsed = sections.parse(text)
    assert [s.number for s in parsed] == ["", "1.1", "1.2"]


def test_an_unterminated_fence_raises_instead_of_hiding_everything_after_it():
    """A fence that never closes must not silently hide every heading after
    it, the same silent-deletion shape the Setext fix closed."""
    text = "My Guide\n========\n\n### 1.1.\xa0A\n\n```\nnever closed\n"
    try:
        sections.parse(text)
    except sections.SectionError:
        pass
    else:
        raise AssertionError("an unterminated fence must raise, not hide structure")


def test_a_list_item_followed_by_a_dash_run_is_not_a_setext_heading():
    """A Setext heading cannot interrupt a list; CommonMark requires the line
    above the heading text to be blank."""
    text = (
        "My Guide\n========\n\n"
        "* item zero\n"
        "* item one\n"
        "-----\n\n"
        "### 1.1.\xa0Real heading\n\n"
        "Body.\n"
    )
    parsed = sections.parse(text)
    assert [s.number for s in parsed] == ["", "1.1"]


def test_an_indented_line_followed_by_equals_is_not_a_setext_heading():
    """A 4-space indented line is a code block in CommonMark, not a heading
    candidate, no matter what follows it."""
    text = "My Guide\n========\n\n    output header\n    ====\n\nProse.\n"
    parsed = sections.parse(text)
    assert not any(s.title == "output header" for s in parsed)


def test_a_lone_equals_under_prose_is_not_a_setext_heading():
    """A single `=` is too weak a signal; require at least two, matching `-`."""
    text = "My Guide\n========\n\nSome prose line\n=\n\nMore prose.\n"
    parsed = sections.parse(text)
    assert not any(s.title == "Some prose line" for s in parsed)


# --- fix round 3: an unnumbered ATX heading must bound too, not just Setext.


def test_an_unnumbered_atx_heading_bounds_a_preceding_subtree():
    """`# Legal Notice` at the end of a guide carries no number, and `parse`
    gives it depth 0 -- the same depth as the guide's own leading heading.
    Only the leading heading may be exempt from bounding; this one must still
    stop the subtree before it, or an unrelated appendix leaks into whatever
    section happens to precede it."""
    text = "### 3.1.\xa0Alpha\n\nAlpha prose.\n\n# Legal Notice\n\nCopyright.\n"
    body = sections.subtree(text, "3.1")
    assert "Alpha prose" in body
    assert "Legal Notice" not in body
    assert "Copyright" not in body


def test_replace_leaves_a_trailing_unnumbered_atx_heading_untouched():
    text = "### 3.1.\xa0Alpha\n\nAlpha prose.\n\n# Legal Notice\n\nCopyright.\n"
    out = sections.replace(text, "3.1", "### 3.1.\xa0Alpha\n\nRewritten.\n")
    assert "Legal Notice" in out
    assert "Copyright" in out


def test_the_guide_title_itself_is_still_never_a_boundary_when_it_is_atx():
    """The document's own leading heading is an unnumbered ATX heading in
    `GUIDE`. The fix for a trailing unnumbered ATX heading must not turn the
    guide title into a boundary too."""
    body = sections.subtree(GUIDE, "9.1")
    assert "Later prose" in body

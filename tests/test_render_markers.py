"""The comment markers that wrap what the tool actually produced.

A human opening a draft, or the review step scoping its lint to net-new
prose, both need to know exactly which span the tool wrote. The markers are
the answer to both.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIB = REPO_ROOT / "skills" / "docs-engine" / "scripts"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from lib.md import render  # noqa: E402


def test_wrap_marker_surrounds_the_body_with_the_run_identity():
    wrapped = render.wrap_marker("Some rewritten prose.", "RHOAIENG-82726")
    lines = wrapped.splitlines()
    assert lines[0] == "<!-- docs-gen output RHOAIENG-82726 -->"
    assert lines[-1] == "<!-- end docs-gen -->"
    assert "Some rewritten prose." in wrapped


def test_wrap_marker_is_a_no_op_without_a_marker_id():
    assert render.wrap_marker("Some prose.", "") == "Some prose."
    assert render.wrap_marker("Some prose.", None) == "Some prose."


def test_marked_spans_extracts_the_content_between_the_comments():
    text = (
        "Published prose before.\n\n"
        "<!-- docs-gen output RHOAIENG-82726 -->\n"
        "The new bit.\n"
        "<!-- end docs-gen -->\n\n"
        "Published prose after.\n"
    )
    spans = render.marked_spans(text)
    assert spans == ["The new bit."]


def test_marked_spans_finds_every_pair():
    text = (
        "<!-- docs-gen output T -->\nOne.\n<!-- end docs-gen -->\n\n"
        "Untouched.\n\n"
        "<!-- docs-gen output T -->\nTwo.\n<!-- end docs-gen -->\n"
    )
    assert render.marked_spans(text) == ["One.", "Two."]


def test_marked_spans_is_empty_without_any_markers():
    assert render.marked_spans("Just prose, no markers.\n") == []

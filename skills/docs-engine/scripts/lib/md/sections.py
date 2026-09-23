#!/usr/bin/env python3
"""The heading tree of a published guide, and one subtree of it."""

from __future__ import annotations

import re
from dataclasses import dataclass

HEADING = re.compile(r"^(#{1,6})\s+(?:(\d+(?:\.\d+)*)\.)?\s*(.+?)\s*$")
SETEXT_CHAPTER_TITLE = re.compile(r"^Chapter\s+(\d+)\.\s*(.+?)\s*$")
# A definition list can open its fenced body right after the `:` marker
# (`:   ```), and missing that shape desyncs every open/close count after it.
# The captured run records which character and how long, so a close needs a
# same-character run at least that long, as CommonMark requires.
FENCE_OPEN = re.compile(r"^\s*(?::\s+)?(`{3,}|~{3,})")
NBSP = "\xa0"
INDENTED_CODE = 4


class SectionError(RuntimeError):
    """The guide does not have the section it was asked for."""


@dataclass(frozen=True)
class Section:
    """One heading. `number` is empty for an unnumbered guide title."""

    number: str
    title: str
    line: int
    depth: int


def _is_underline(line, char, minlen):
    """Whether `line` is a Setext underline of `char`, tolerant of U+00A0."""
    run = line.strip().replace(NBSP, "")
    return len(run) >= minlen and set(run) == {char}


def _is_fence_close(line, char, minlen):
    """Return whether line closes the current fenced block."""
    run = line.strip()
    return len(run) >= minlen and set(run) == {char}


def parse(text):
    """Every heading in `text`, in order, with its depth from its number."""
    lines = (text or "").splitlines()
    found = []
    in_fence = False
    fence_char = None
    fence_len = 0
    fence_open_line = None
    total = len(lines)
    index = 0
    while index < total:
        line = lines[index]

        if in_fence:
            if _is_fence_close(line, fence_char, fence_len):
                in_fence = False
                fence_char = None
                fence_len = 0
                fence_open_line = None
            index += 1
            continue

        open_match = FENCE_OPEN.match(line)
        if open_match:
            run = open_match.group(1)
            in_fence = True
            fence_char = run[0]
            fence_len = len(run)
            fence_open_line = index
            index += 1
            continue

        match = HEADING.match(line)
        if match:
            number = match.group(2) or ""
            found.append(
                Section(
                    number=number,
                    title=match.group(3),
                    line=index,
                    depth=len(number.split(".")) if number else 0,
                )
            )
            index += 1
            continue

        text_line = line.strip()
        next_line = lines[index + 1] if index + 1 < total else None
        prev_blank = index == 0 or not lines[index - 1].strip()
        indented = (len(line) - len(line.lstrip(" "))) >= INDENTED_CODE
        if text_line and next_line is not None and prev_blank and not indented:
            if _is_underline(next_line, "=", 2):
                found.append(Section(number="", title=text_line, line=index, depth=0))
                index += 2
                continue
            if _is_underline(next_line, "-", 2):
                chapter = SETEXT_CHAPTER_TITLE.match(text_line)
                if chapter:
                    number, title = chapter.group(1), chapter.group(2)
                else:
                    number, title = "", text_line
                found.append(Section(number=number, title=title, line=index, depth=1))
                index += 2
                continue

        index += 1

    if in_fence:
        raise SectionError(
            f"a fenced code block opened at line {fence_open_line + 1} is never closed"
        )
    return found


def bounds(parsed, number):
    """The line range of one subtree, end exclusive, or None if absent."""
    if not number:
        return None
    for position, section in enumerate(parsed):
        if section.number != number:
            continue
        for later in parsed[position + 1 :]:
            # Depth 0 marks an unnumbered heading. The guide's own leading
            # heading is always `parsed[0]` and can never appear here. Every
            # other depth-0 heading is unrelated content the subtree must stop
            # before, so it bounds unconditionally.
            if later.depth == 0 or later.depth <= section.depth:
                return section.line, later.line
        return section.line, -1
    return None


def subtree(text, number):
    """One section and its children, as text, or None if absent."""
    lines = (text or "").splitlines(keepends=True)
    span = bounds(parse(text), number)
    if span is None:
        return None
    start, end = span
    return "".join(lines[start:] if end < 0 else lines[start:end])


def replace(text, number, body):
    """`text` with one subtree swapped for `body`, byte-identical elsewhere."""
    lines = (text or "").splitlines(keepends=True)
    span = bounds(parse(text), number)
    if span is None:
        raise SectionError(f"the guide has no section {number}")
    start, end = span
    replacement = body if body.endswith("\n") else body + "\n"
    tail = [] if end < 0 else lines[end:]
    original_span = lines[start:end] if end >= 0 else lines[start:]
    boundary_was_blank = bool(original_span) and original_span[-1].strip() == ""
    if tail and boundary_was_blank and not replacement.endswith("\n\n"):
        replacement += "\n"
    return "".join(lines[:start] + [replacement] + tail)


def tree_lines(parsed):
    """The tree as the model sees it: one line per heading, indented by depth."""
    rendered = []
    chapters = set()
    for section in parsed:
        if section.depth == 0:
            rendered.append(section.title)
            continue
        if section.depth == 1:
            if section.number:
                chapters.add(section.number)
                rendered.append(f"Chapter {section.number}. {section.title}")
            else:
                rendered.append(section.title)
            continue
        chapter = section.number.split(".")[0]
        if chapter not in chapters:
            chapters.add(chapter)
            rendered.append(f"Chapter {chapter}")
        rendered.append("  " * (section.depth - 1) + f"{section.number}. {section.title}")
    return "\n".join(rendered)

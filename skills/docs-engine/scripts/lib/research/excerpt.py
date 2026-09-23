#!/usr/bin/env python3
"""Cut a fetched page down to the parts a topic actually asks about."""

from __future__ import annotations

import re
from dataclasses import dataclass

# `## Heading`, and the underlined forms rhd emits for h1 and h2.
ATX = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
SETEXT = re.compile(r"^([=-]{3,})\s*$")

STOP = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "use",
    "using",
    "with",
    "you",
    "your",
    "what",
    "when",
    "where",
    "which",
}


@dataclass(frozen=True)
class Section:
    heading: str
    body: str
    score: int = 0

    @property
    def words(self):
        return len(self.body.split())


def terms(topic):
    """The words of a topic worth matching on."""
    found = re.findall(r"[a-z0-9][a-z0-9._-]*", topic.replace("\xa0", " ").lower())
    return {word for word in found if word not in STOP and len(word) > 2}


def split(content):
    """A page's sections, in the order it wrote them."""
    lines = content.splitlines()
    sections = []
    heading = ""
    body = []

    index = 0
    while index < len(lines):
        line = lines[index]
        nxt = lines[index + 1] if index + 1 < len(lines) else ""

        atx = ATX.match(line)
        underlined = bool(line.strip()) and bool(SETEXT.match(nxt))
        if atx or underlined:
            if heading or any(row.strip() for row in body):
                sections.append(Section(heading, "\n".join(body).strip()))
            heading = atx.group(2) if atx else line.strip()
            body = []
            index += 2 if underlined else 1
            continue

        body.append(line)
        index += 1

    if heading or any(row.strip() for row in body):
        sections.append(Section(heading, "\n".join(body).strip()))
    return sections


def score(section, wanted):
    """How many of the topic's terms this section uses."""
    if not wanted:
        return 0
    body_terms = terms(section.body)
    head_terms = terms(section.heading)
    return len(wanted & body_terms) + 3 * len(wanted & head_terms)


def relevant(content, topic, budget=12000, minimum=1):
    """The highest-scoring sections of a page, up to `budget` characters."""
    wanted = terms(topic)
    scored = [
        Section(section.heading, section.body, score(section, wanted))
        for section in split(content)
        if section.body.strip()
    ]
    ranked = sorted(
        ((index, section) for index, section in enumerate(scored) if section.score >= minimum),
        key=lambda pair: (-pair[1].score, pair[0]),
    )

    taken = []
    spent = 0
    for index, section in ranked:
        cost = len(section.heading) + len(section.body)
        if spent and spent + cost > budget:
            continue
        taken.append((index, section))
        spent += cost
        if spent >= budget:
            break
    return [section for _, section in sorted(taken, key=lambda pair: pair[0])]


def render(sections):
    """The selected sections as Markdown, headings intact."""
    parts = []
    for section in sections:
        parts.append(f"## {section.heading}\n\n{section.body}" if section.heading else section.body)
    return "\n\n".join(parts)

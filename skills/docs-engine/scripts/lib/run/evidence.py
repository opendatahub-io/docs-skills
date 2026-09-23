#!/usr/bin/env python3
"""What a writer's citation is, read the same way by every step that reads one.

Three steps read the `evidence` array: the writer decides what to cite, the
reviewer decides whether it resolves, the coverage gate decides whether it
proves anything. Widening the pattern in one place and not the others yields a
citation the writer emits, the schema accepts and the reviewer flags, and no
artifact records the disagreement.

`write-out.json` holds a fourth copy as a JSON Schema `pattern` string that
cannot import anything. That one is edited by hand.
"""

from __future__ import annotations

import re

# An evidence entry naming a page rather than a file in this repository.
URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")

# The Jira description, cited as itself. A single-letter project key is legal:
# rejecting one dropped the description silently, which is the one failure
# nothing downstream reports.
TICKET = re.compile(r"^jira:[A-Za-z][A-Za-z0-9_]*-[0-9]+:description$")


def ticket_reference(key):
    """The stable citation a writer uses for a Jira description."""
    reference = f"jira:{(key or '').strip()}:description"
    return reference if TICKET.match(reference) else ""


def is_ticket(entry):
    """Whether one evidence entry cites a ticket description."""
    return bool(TICKET.match((entry or "").strip()))


def only_ticket(entries):
    """Whether a page rests on ticket descriptions and nothing else.

    A ticket states a fact, the page repeats it, and the citation points back
    at the ticket. Nothing outside the request was consulted, so the chain has
    checked the ticket against itself. That can still be the right page to
    write; what it cannot be is a requirement the run verified.

    Cites nothing at all is a different outcome with its own reason, so an
    empty array is false here.
    """
    kept = [entry for entry in entries or [] if (entry or "").strip()]
    return bool(kept) and all(is_ticket(entry) for entry in kept)

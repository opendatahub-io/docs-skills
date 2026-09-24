"""docs-write: the shape each foundation document is written to.

An archetype is how a document-specific contract arrives without a
document-specific prompt. GET-STARTED carries the tutorial rules; the others
carry their own organisation.

A foundation stem with no archetype file would silently fall back to the plain
type archetype and lose its contract, so the mapping is asserted rather than
assumed.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))
sys.path.insert(0, str(_ROOT / "skills" / "docs-write" / "scripts"))

import write  # noqa: E402
from lib.foundation import gates  # noqa: E402


def test_every_foundation_document_has_an_archetype():
    for doc in gates.DOCUMENTS:
        text = write.archetype_for(doc.doc_type, doc.stem)
        assert text.strip(), f"{doc.stem} has no archetype"


def test_a_plain_type_still_resolves_without_a_foundation_stem():
    assert write.archetype_for("concept").strip()
    assert write.archetype_for("procedure").strip()


def test_the_tutorial_contract_reaches_get_started():
    text = write.archetype_for("procedure", "get-started")
    lowered = text.lower()
    assert "one path" in lowered
    assert "expected output" in lowered


def test_an_unknown_foundation_stem_falls_back_to_the_type():
    assert write.archetype_for("concept", "nonesuch") == write.archetype_for("concept")

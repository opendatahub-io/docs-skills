"""lib/foundation/evidence: what reaches the model, per document.

ARCHITECTURE gets the dependency graph and the module purposes, never the
signatures. That exclusion is the synthesis this work exists to produce: forty
modules arrive as a shape rather than as forty symbol lists.

Every payload is capped, which is what lets a 300-module repository produce the
same five documents as a 3-module one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "skills" / "docs-engine" / "scripts"))

from lib.foundation import evidence  # noqa: E402


def _out(tmp_path, modules, **files):
    out = tmp_path / ".docs-gen"
    (out / "modules").mkdir(parents=True)
    (out / "registry.json").write_text(json.dumps({"modules": modules}))
    for name, data in files.items():
        (out / name).write_text(json.dumps(data))
    return out


def test_architecture_carries_the_graph_and_never_a_signature(tmp_path):
    out = _out(
        tmp_path,
        {"pkg/a": {"kind": "library"}, "pkg/b": {"kind": "library"}},
        **{
            "dep-pairs.json": {"pairs": [{"from": "pkg/a", "to": "pkg/b"}]},
            "api-surface.json": {"modules": {"pkg/a": {"symbols": {"Run": {"sig": "func Run()"}}}}},
        },
    )
    got = evidence.payload("architecture", tmp_path, out, ["pkg/a", "pkg/b"])
    assert got["edges"] == [{"from": "pkg/a", "to": "pkg/b"}]
    assert "func Run()" not in json.dumps(got)


def test_architecture_ranks_modules_by_fan_in(tmp_path):
    # pkg/hub is depended on by both leaves, so its fan-in (2) is unambiguously
    # the highest in the fixture. If ranking ever regresses from fan-in to
    # fan-out (or to source order), this fails here rather than three layers
    # up in a document that merely looked wrong.
    out = _out(
        tmp_path,
        {
            "pkg/hub": {"kind": "library"},
            "pkg/leaf1": {"kind": "library"},
            "pkg/leaf2": {"kind": "library"},
        },
        **{
            "dep-pairs.json": {
                "pairs": [
                    {"from": "pkg/leaf1", "to": "pkg/hub"},
                    {"from": "pkg/leaf2", "to": "pkg/hub"},
                ]
            }
        },
    )
    (out / "modules" / "pkg__hub.json").write_text(
        json.dumps({"module": "pkg/hub", "purpose": "Shared by both leaves"})
    )
    got = evidence.payload("architecture", tmp_path, out, ["pkg/leaf1", "pkg/leaf2", "pkg/hub"])
    assert got["modules"][0]["module"] == "pkg/hub"
    assert got["modules"][0]["purpose"] == "Shared by both leaves"


def test_the_module_list_is_capped_and_the_tail_is_counted(tmp_path):
    modules = {f"pkg/m{index:03d}": {"kind": "library"} for index in range(50)}
    out = _out(tmp_path, modules, **{"dep-pairs.json": {"pairs": []}})
    got = evidence.payload("architecture", tmp_path, out, sorted(modules))
    assert len(got["modules"]) == evidence.MODULE_CAP
    assert got["tail"]["count"] == 50 - evidence.MODULE_CAP
    assert got["tail"]["by_kind"]["library"] == 50 - evidence.MODULE_CAP


def test_readme_survives_a_malformed_onboarding_file(tmp_path):
    out = _out(tmp_path, {"pkg/a": {"kind": "library"}, "cmd/x": {"kind": "cli"}})
    (out / "onboarding.json").write_text("{ this is not json")
    got = evidence.payload("readme", tmp_path, out, ["pkg/a", "cmd/x"])
    assert got["counts"] == {"cli": 1, "library": 1}
    assert got["what_this_is"] == ""
    assert got["synthesis_available"] is False


def test_readme_uses_the_synthesis_where_it_parses(tmp_path):
    out = _out(tmp_path, {"pkg/a": {"kind": "library"}})
    (out / "onboarding.json").write_text(
        json.dumps({"sections": [{"id": "what-this-is", "body": "A router."}]})
    )
    got = evidence.payload("readme", tmp_path, out, ["pkg/a"])
    assert got["what_this_is"] == "A router."
    assert got["synthesis_available"] is True


def test_get_started_carries_the_declared_commands(tmp_path):
    (tmp_path / "Makefile").write_text("build: ## Compile\n\tgo build ./...\n")
    out = _out(tmp_path, {"cmd/x": {"kind": "cli"}})
    got = evidence.payload("get-started", tmp_path, out, ["cmd/x"])
    assert "make build" in got["allowed_commands"]
    assert got["declared"]["make"][0]["help"] == "Compile"


def test_roadmap_carries_deprecations_grouped_by_package(tmp_path):
    out = _out(
        tmp_path,
        {"pkg/a": {}},
        **{
            "api-surface.json": {
                "modules": {
                    "pkg/a": {
                        "symbols": {
                            "Old": {"doc": "Deprecated: use New."},
                            "Older": {"doc": "Deprecated: use New."},
                            "Fine": {"doc": "Does a thing."},
                        }
                    }
                }
            }
        },
    )
    got = evidence.payload("roadmap", tmp_path, out, ["pkg/a"])
    assert got["deprecations"][0]["module"] == "pkg/a"
    assert sorted(got["deprecations"][0]["symbols"]) == ["Old", "Older"]

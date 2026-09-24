"""What reaches the model, per foundation document, and what never does.

Each payload is a slice of the committed grounding tier chosen for one
document, capped before it leaves. The caps are what make the output size
independent of the repository size.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from lib.foundation import commands, gates

# The modules that arrive in full. Above this the tail is counted rather than
# described, so a 300-module repository costs what a 20-module one costs.
MODULE_CAP = 20
# Deprecation groups, and symbols named inside one group.
DEPRECATION_GROUP_CAP = 20
DEPRECATION_SYMBOL_CAP = 10


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return default


def _summaries(out_dir):
    found = {}
    directory = Path(out_dir) / "modules"
    if not directory.is_dir():
        return found
    for record in sorted(directory.glob("*.json")):
        data = _load(record, {})
        if data.get("module"):
            found[data["module"]] = data
    return found


def _ranked(modules, pairs, summaries, sources):
    """Modules ordered by fan-in crossed with onboarding priority."""
    fan_in = Counter(pair.get("to") for pair in pairs if pair.get("to"))
    chosen = [name for name in sources if name in modules] or sorted(modules)

    def weight(name):
        priority = (summaries.get(name) or {}).get("onboarding_priority") or 0
        return (-(fan_in.get(name, 0) + priority), name)

    return sorted(chosen, key=weight)


def _tail(modules, kept):
    rest = [name for name in modules if name not in set(kept)]
    return {
        "count": len(rest),
        "by_kind": dict(Counter((modules[name] or {}).get("kind", "library") for name in rest)),
        "by_prefix": dict(Counter(name.split("/", 1)[0] for name in rest)),
    }


def _module_records(names, modules, summaries):
    records = []
    for name in names:
        summary = summaries.get(name) or {}
        records.append(
            {
                "module": name,
                "kind": (modules.get(name) or {}).get("kind", "library"),
                "purpose": summary.get("purpose", ""),
                "responsibilities": (summary.get("responsibilities") or [])[:5],
                "gotchas": (summary.get("gotchas") or [])[:3],
                "evidence": (summary.get("evidence") or [])[:3],
            }
        )
    return records


def _section(onboarding, section_id):
    for section in (onboarding or {}).get("sections") or []:
        if section.get("id") == section_id:
            return section.get("body", "")
    return ""


def payload(stem, repo, out_dir, sources):
    """The evidence one foundation document is written from."""
    out = Path(out_dir)
    modules = (_load(out / "registry.json", {}).get("modules")) or {}
    summaries = _summaries(out)
    pairs = (_load(out / "dep-pairs.json", {}).get("pairs")) or []
    surface = (_load(out / "api-surface.json", {}).get("modules")) or {}

    if stem == "readme":
        raw = Path(out / "onboarding.json")
        onboarding = _load(raw, None) if raw.is_file() else None
        kinds = Counter((entry or {}).get("kind", "library") for entry in modules.values())
        return {
            "counts": dict(sorted(kinds.items())),
            "what_this_is": _section(onboarding, "what-this-is"),
            "synthesis_available": onboarding is not None,
        }

    if stem == "get-started":
        declared = commands.declared_commands(repo)
        entries = _ranked(modules, pairs, summaries, sources)[:MODULE_CAP]
        return {
            "entry_points": _module_records(entries, modules, summaries),
            "declared": declared,
            "allowed_commands": sorted(commands.allowlist(declared)),
            "prerequisites": _prerequisites(repo),
        }

    if stem == "architecture":
        kept = _ranked(modules, pairs, summaries, sources)[:MODULE_CAP]
        return {
            "modules": _module_records(kept, modules, summaries),
            "edges": pairs,
            "tail": _tail(modules, kept),
        }

    if stem == "security":
        kept = _ranked(modules, pairs, summaries, sources)[:MODULE_CAP]
        return {
            "modules": _module_records(kept, modules, summaries),
            "symbols": {
                name: sorted((surface.get(name) or {}).get("symbols") or {})[:40] for name in kept
            },
            "configs": _security_configs(repo),
        }

    return {
        "deprecations": _deprecations(surface),
        "api_versions": sorted(name for name in modules if "alpha" in name or "beta" in name),
        "unreleased": _unreleased_entries(repo),
    }


def _prerequisites(repo):
    """Version floors a reader must satisfy, as the manifests state them."""
    root = Path(repo)
    found = {}
    go_mod = root / "go.mod"
    if go_mod.is_file():
        for line in go_mod.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("go "):
                found["go"] = line.split(None, 1)[1].strip()
                break
    package = root / "package.json"
    if package.is_file():
        engines = (_load(package, {}).get("engines")) or {}
        found.update({name: str(value) for name, value in engines.items()})
    dockerfile = root / "Dockerfile"
    if dockerfile.is_file():
        for line in dockerfile.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().upper().startswith("FROM "):
                found["base_image"] = line.split(None, 1)[1].strip()
                break
    return found


def _security_configs(repo):
    return [name for name in gates.SECURITY_CONFIGS if (Path(repo) / name).is_file()]


def _deprecations(surface):
    """Deprecated symbols grouped by the module holding them."""
    groups = []
    for name in sorted(surface):
        symbols = sorted(
            symbol
            for symbol, meta in ((surface.get(name) or {}).get("symbols") or {}).items()
            if "Deprecated:" in ((meta or {}).get("doc") or "")
        )
        if symbols:
            groups.append(
                {
                    "module": name,
                    "symbols": symbols[:DEPRECATION_SYMBOL_CAP],
                    "total": len(symbols),
                }
            )
    return groups[:DEPRECATION_GROUP_CAP]


def _unreleased_entries(repo):
    directory = Path(repo) / "release-notes.d" / "unreleased"
    if not directory.is_dir():
        return []
    return sorted(entry.name for entry in directory.iterdir() if entry.is_file())[:40]

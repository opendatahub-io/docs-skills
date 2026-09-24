"""Which of the five foundation documents this repository's evidence supports.

Nothing here calls a model. A gate reads the committed grounding tier and the
working tree, and a document that fails one is skipped with the gate named, so
a maintainer knows whether to supply evidence or switch the gate off.
"""

from __future__ import annotations

import json
import re
from collections import namedtuple
from pathlib import Path

from lib.foundation import commands

Document = namedtuple("Document", "stem path doc_type title")

DOCUMENTS = (
    Document("readme", "README.md", "reference", "What this repository is"),
    Document("get-started", "GET-STARTED.md", "procedure", "Get started"),
    Document("architecture", "ARCHITECTURE.md", "concept", "Architecture"),
    Document("security", "SECURITY.md", "concept", "Security"),
    Document("roadmap", "ROADMAP.md", "reference", "Roadmap"),
)

STEMS = {doc.stem for doc in DOCUMENTS}

SECURITY_WORDS = (
    "auth",
    "authn",
    "authz",
    "rbac",
    "token",
    "cert",
    "tls",
    "crypto",
    "secret",
    "credential",
)
SECURITY_CONFIGS = (
    ".golangci-security.yml",
    ".bandit",
    "bandit.yaml",
    ".semgrep.yml",
    "semgrep.yaml",
    "trivy.yaml",
    ".snyk",
)
# Where GitHub looks for a policy, all three, case-insensitively.
POLICY_LOCATIONS = ("SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md")

API_VERSION = re.compile(r"(?:^|/)v\d+(?:alpha|beta)\d*(?:/|$)")
ENTRY_KINDS = ("cli", "service")

_SECURITY_WORDS = frozenset(SECURITY_WORDS)
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
# Two boundary rules, not one. `(?<=[a-z0-9])(?=[A-Z])` catches AuthToken;
# on its own it misses an acronym run meeting a TitleCase word, so TLSConfig
# stayed one token and stopped matching `tls`. `(?<=[A-Z])(?=[A-Z][a-z])`
# catches that run-to-word boundary: TLSConfig -> TLS|Config,
# RBACPolicy -> RBAC|Policy, JWTToken -> JWT|Token.
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokens(text):
    """Lowercase whole-word tokens: split on non-alphanumerics and camelCase.

    `internal/authoring` yields `{internal, authoring}`, not a substring hit
    on `auth`; `AuthToken` yields `{auth, token}`; `TLSConfig` yields
    `{tls, config}`. Vocabulary membership is tested against this set, never
    against the raw string, so `cert` does not fire on `concert`, `secret`
    does not fire on `secretary`, and an all-caps initialism like `TLS` or
    `RBAC` still surfaces as its own token instead of fusing with the word
    that follows it.
    """
    tokens = []
    for chunk in _NON_ALNUM.split(text):
        if not chunk:
            continue
        tokens.extend(_CAMEL_BOUNDARY.sub(" ", chunk).casefold().split())
    return tokens


def _has_security_word(text):
    return bool(_SECURITY_WORDS & set(_tokens(text)))


def _load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return default


def _exists_insensitive(root, relative):
    """Whether `relative` exists under `root`, ignoring case in the final name.

    `docs/architecture.md` and `docs/ARCHITECTURE.md` are one file on macOS and
    two on Linux. A run creating the second breaks the repository for half the
    team, so the comparison is case-insensitive whatever the filesystem says.
    """
    target = Path(root) / relative
    parent = target.parent
    if not parent.is_dir():
        return None
    wanted = target.name.casefold()
    for entry in parent.iterdir():
        if entry.name.casefold() == wanted:
            return entry
    return None


def _security_evidence(repo, modules, surface):
    for name in modules:
        if _has_security_word(name):
            return f"module {name}"
    for name, entry in (surface or {}).items():
        for symbol in entry.get("symbols") or {}:
            if _has_security_word(symbol):
                return f"symbol {symbol} in {name}"
    for config in SECURITY_CONFIGS:
        if (Path(repo) / config).is_file():
            return config
    return ""


def _existing_policy(repo):
    for location in POLICY_LOCATIONS:
        found = _exists_insensitive(repo, location)
        if found is not None:
            return str(Path(found).relative_to(repo))
    return ""


def _forward_markers(modules, surface):
    """Markers carrying a commitment to something changing."""
    found = []
    for name in modules:
        if API_VERSION.search(name):
            found.append(f"api version {name}")
            break
    for name, entry in (surface or {}).items():
        for symbol, meta in (entry.get("symbols") or {}).items():
            if "Deprecated:" in (meta.get("doc") or ""):
                found.append(f"deprecated {symbol} in {name}")
                break
    return found


def _unreleased(repo):
    root = Path(repo)
    if (root / "release-notes.d" / "unreleased").is_dir():
        return "release-notes.d/unreleased"
    changelog = root / "CHANGELOG.md"
    if changelog.is_file():
        text = changelog.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^#{1,3}\s*\[?unreleased\]?", text, re.I | re.M):
            return "CHANGELOG.md Unreleased"
    return ""


def evaluate(repo, out_dir, docs_dir, skip=()):
    """The deliverables the evidence supports, and every skip with its gate."""
    unknown = sorted(set(skip) - STEMS)
    if unknown:
        raise ValueError(
            f"unknown foundation document(s) in skip: {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(STEMS))}"
        )

    registry = _load(Path(out_dir) / "registry.json", {})
    modules = registry.get("modules") or {}
    surface = (_load(Path(out_dir) / "api-surface.json", {}).get("modules")) or {}
    pairs = (_load(Path(out_dir) / "dep-pairs.json", {}).get("pairs")) or []

    written, skipped = [], []
    for doc in DOCUMENTS:
        relative = f"{docs_dir}/{doc.path}"
        record = {"doc": relative}

        if doc.stem in skip:
            skipped.append(
                {**record, "gate": "disabled", "reason": "switched off in .docs-gen.yaml"}
            )
            continue

        gate, reason, sources = _decide(doc, repo, docs_dir, modules, surface, pairs)
        if gate:
            skipped.append({**record, "gate": gate, "reason": reason})
            continue

        written.append(
            {
                "path": relative,
                "type": doc.doc_type,
                "title": doc.title,
                "kind": "new",
                "rationale": reason,
                "sources": sources,
                "foundation": doc.stem,
            }
        )
    return written, skipped


def _decide(doc, repo, docs_dir, modules, surface, pairs):
    """`(gate, reason, sources)`. An empty gate means the document is written."""
    collision = _collision(repo, f"{docs_dir}/{doc.path}")
    if collision:
        return collision[0], collision[1], []

    if doc.stem == "readme":
        if not modules:
            return "no_modules", "the registry holds no module", []
        return "", f"the registry holds {len(modules)} module(s)", sorted(modules)

    if doc.stem == "get-started":
        entries = [name for name, entry in modules.items() if entry.get("kind") in ENTRY_KINDS]
        if not entries:
            return "no_entry_point", "no module of kind cli or service", []
        if not commands.has_manifest(repo):
            return "no_runnable_target", "no manifest declares a runnable target", []
        return "", f"{len(entries)} entry point(s) with a declared target", sorted(entries)

    if doc.stem == "architecture":
        if len(modules) < 3 or not pairs:
            return (
                "graph_too_small",
                f"{len(modules)} module(s) and {len(pairs)} edge(s); 3 and 1 are the floor",
                [],
            )
        return "", f"{len(modules)} modules across {len(pairs)} edges", sorted(modules)

    if doc.stem == "security":
        policy = _existing_policy(repo)
        if policy:
            return "policy_exists", f"a policy already exists at {policy}", []
        evidence = _security_evidence(repo, modules, surface)
        if not evidence:
            return "no_security_surface", "no security vocabulary and no tool config", []
        matched = sorted(name for name in modules if _has_security_word(name))
        return "", f"security evidence in {evidence}", matched

    markers = _forward_markers(modules, surface)
    unreleased = _unreleased(repo)
    if unreleased:
        markers.append(unreleased)
    if not markers:
        return (
            "no_forward_marker",
            "no deprecation, alpha or beta API version, or unreleased notes",
            [],
        )
    return "", f"forward markers: {', '.join(markers[:3])}", sorted(modules)


def _collision(repo, relative):
    """`(gate, reason)` where an existing file forbids writing, else `()`."""
    found = _exists_insensitive(repo, relative)
    if found is None:
        return ()
    name = str(Path(found).relative_to(repo))
    if Path(found).name != Path(relative).name:
        return ("path_collision", f"{name} differs only by case")
    try:
        from lib.md import docs_meta

        front, _, had = docs_meta.parse(Path(found).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return ()
    if had and front.get("managed", "manual") == "manual":
        return ("manual_page", f"{name} is managed: manual")
    return ()

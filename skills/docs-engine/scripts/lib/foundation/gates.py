"""Which of the five foundation documents this repository's evidence supports.

Nothing here calls a model. A gate reads the committed grounding tier and the
working tree, and a document that fails one is skipped with the gate named, so
a maintainer knows whether to supply evidence or switch the gate off.
"""

from __future__ import annotations

import json
import re
from collections import Counter, namedtuple
from pathlib import Path

from lib.foundation import commands
from lib.md import docs_meta

Document = namedtuple("Document", "stem path doc_type title")

DOCUMENTS = (
    Document("readme", "README.md", "reference", "What this repository is"),
    Document("get-started", "GET-STARTED.md", "procedure", "Get started"),
    Document("architecture", "ARCHITECTURE.md", "concept", "Architecture"),
    Document("security", "SECURITY.md", "concept", "Security"),
    Document("roadmap", "ROADMAP.md", "reference", "Roadmap"),
)

STEMS = {doc.stem for doc in DOCUMENTS}

# How many modules a document may cite. `source_modules` ships in the page's
# frontmatter and `docs_meta.stale()` joins it, so an uncapped list grows the
# shipped page with the repository and re-queues README, ARCHITECTURE and
# ROADMAP on any single-module change. `evidence.MODULE_CAP` reads this, so
# the modules a page declares are the modules that grounded it. A change
# outside the cap is recovered by the `full_rebuild` verdict.
SOURCE_CAP = 20

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


def registry_modules(out_dir, strict=False):
    """`(registry, modules)` from registry.json, with the shape checked.

    A registry whose `modules` is a list reaches `.items()` several frames
    later as an AttributeError, which the caller cannot tell apart from an
    empty repository. Say what is wrong instead. The planner reads this too,
    so the check and its wording live in one place.

    `strict` re-raises an unreadable or malformed file rather than treating it
    as an empty registry, which is what a caller that has already established
    the file exists wants.
    """
    path = Path(out_dir) / "registry.json"
    try:
        registry = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        if strict:
            raise
        registry = {}
    modules = registry.get("modules") or {} if isinstance(registry, dict) else {}
    if not isinstance(modules, dict):
        raise ValueError(
            "registry.json: `modules` must be an object keyed by module path, "
            f"found {type(modules).__name__}. Re-run docs-repo-analyze."
        )
    return registry, modules


def _exists_insensitive(root, relative):
    """The real path matching `relative` under `root`, ignoring case, or None.

    `docs/architecture.md` and `docs/ARCHITECTURE.md` are one file on macOS and
    two on Linux. A run creating the second breaks the repository for half the
    team, so the comparison ignores case whatever the filesystem does. A tree
    that does not exist yet is the normal first-run state, not an error.
    """
    target = Path(root) / relative
    parent = target.parent
    try:
        entries = list(parent.iterdir())
    except (OSError, NotADirectoryError):
        return None
    wanted = target.name.casefold()
    for entry in entries:
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


def _capped(names, pairs):
    """The most depended-on `SOURCE_CAP` of `names`, in name order."""
    names = sorted(names)
    if len(names) <= SOURCE_CAP:
        return names
    fan_in = Counter(pair.get("to") for pair in pairs if pair.get("to"))
    ranked = sorted(names, key=lambda name: (-fan_in.get(name, 0), name))
    return sorted(ranked[:SOURCE_CAP])


def _existing_policy(repo, owned=""):
    """The policy this repository already has, ignoring the one we write.

    `owned` is the path the security document is written to. Under the
    default `docs_dir` that is `docs/SECURITY.md`, which is also a location
    GitHub reads, so without this the document gates itself off on the
    second run and review then reports it as an orphan.
    """
    owned = owned.casefold()
    for location in POLICY_LOCATIONS:
        found = _exists_insensitive(repo, location)
        if found is None:
            continue
        relative = str(Path(found).relative_to(repo))
        if relative.casefold() == owned:
            continue
        return relative
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

    _, modules = registry_modules(out_dir)
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
                "sources": _capped(sources, pairs),
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
        policy = _existing_policy(repo, f"{docs_dir}/{doc.path}")
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
    """`(gate, reason)` where an existing file forbids writing, else `()`.

    Order matters. A name differing only by case is refused before the
    frontmatter is consulted, because the file we would create is a second
    file on this filesystem and one file on someone else's.
    """
    found = _exists_insensitive(repo, relative)
    if found is None:
        return ()
    name = str(Path(found).relative_to(repo))
    if Path(found).name != Path(relative).name:
        return ("path_collision", f"{name} differs only by case from {relative}")
    try:
        text = Path(found).read_text(encoding="utf-8", errors="replace")
        front, _, had = docs_meta.parse(text)
    except (OSError, UnicodeDecodeError, docs_meta.MetaError):
        # A page this step cannot parse is one the writer refuses for the same
        # reason. Treating it as owned is the safe answer.
        return ("manual_page", f"{name} cannot be parsed and is treated as owned")
    if not had or front.get("managed", "manual") == "manual":
        return ("manual_page", f"{name} is managed: manual")
    return ()

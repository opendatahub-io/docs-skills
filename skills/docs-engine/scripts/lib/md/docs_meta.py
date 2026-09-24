#!/usr/bin/env python3
"""Frontmatter metadata for generated documentation."""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# ------------------------------------------------------------------ schema

TYPES = ("concept", "procedure", "reference", "changelog", "overview")

# Types this project no longer writes, mapped to what replaced them. Still
# read, because a repository documented before the rename has them on disk.
# Nothing writes one, and `validate` warns rather than failing, so a tree
# drifts towards the current vocabulary.
LEGACY_TYPES = {"task": "procedure"}


def canonical_type(kind):
    """The current name for a type, whatever name a document was written under."""
    return LEGACY_TYPES.get(kind, kind)


MANAGED = ("generated", "assisted", "manual")

# Emission order. Anything not listed follows, sorted, so custom keys survive.
ORDER = (
    "id",
    "title",
    "description",
    "type",
    "owner",
    "tags",
    "lastUpdated",
    "managed",
    "source_modules",
    "source_sha",
    "generator",
)

REQUIRED = ("title", "description", "type", "managed")
SHA = re.compile(r"^[0-9a-f]{7,40}$")

# Files that are agent instructions rather than documentation. Marking or
# indexing these corrupts the very files an agent reads to orient itself.
# Nested ones count: an AGENTS.md beside a package is read the same way.
SKIP_NAMES = {"AGENTS.md", "CLAUDE.md", "GEMINI.md", "SKILL.md"}
# The repository's front page belongs to whoever wrote it, so it is left alone
# where it sits at the root. Skipping the name everywhere instead swept up the
# `README.md` the foundation set writes under `docs_dir`: that page could not
# be stamped, could not reach the index, and `stale()` could never queue it,
# so the one document every reader starts at was the one document no
# incremental run could rewrite.
ROOT_ONLY_SKIP = {"README.md"}
SKIP_DIRS = {
    ".claude",
    ".cursor",
    ".github",
    "node_modules",
    "vendor",
    ".git",
    ".agent_workspace",
    ".docs-gen",
    "site",
    "_build",
}

INDEX_BEGIN = "<!-- docs-gen:index:begin -->"
INDEX_END = "<!-- docs-gen:index:end -->"


class MetaError(RuntimeError):
    pass


# ------------------------------------------------------------- parse / render


def parse(text, source=None):
    """Split a document into (frontmatter dict, body, had_frontmatter)."""
    location = f"{source}: " if source is not None else ""
    if not text.startswith("---"):
        return {}, text, False
    lines = text.split("\n")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            block = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            if yaml is None:
                raise MetaError(f"{location}PyYAML is required to read frontmatter")
            try:
                data = yaml.safe_load(block) or {}
            except yaml.YAMLError as exc:
                # A caller guards against `MetaError`, this module's own
                # vocabulary. A `YAMLError` reaching it from here is a
                # different exception for the same fact, and it escaped every
                # guard that had been written for malformed frontmatter.
                raise MetaError(f"{location}Frontmatter is not valid YAML: {exc}") from exc
            if not isinstance(data, dict):
                raise MetaError(f"{location}Frontmatter is not a mapping")
            return data, body, True
    return {}, text, False


def _scalar(value):
    """Quote only when a bare scalar would be ambiguous to a YAML reader."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    risky = text == "" or text[0] in "#&*!|>%@`[{'\"" or text[-1] in " :"
    risky = (
        risky or ":" in text or text.lower() in ("true", "false", "null", "yes", "no", "on", "off")
    )
    risky = risky or (text.replace(".", "", 1).isdigit()) or "\n" in text or "\r" in text
    risky = risky or re.search(r"\s#", text) is not None
    if risky:
        return json.dumps(text, ensure_ascii=False)
    return text


def render(front, body):
    """Serialize deterministically. Same input, same bytes, every time."""
    keys = [k for k in ORDER if k in front] + sorted(k for k in front if k not in ORDER)
    lines = ["---"]
    for key in keys:
        value = front[key]
        if isinstance(value, (list, tuple)):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_scalar(item)}" for item in value)
        else:
            lines.append(f"{key}: {_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body.lstrip("\n")


# -------------------------------------------------------------------- walking


def walk(root, docs_dir=None):
    root = Path(root)
    base = root / docs_dir if docs_dir else root
    if not base.exists():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if not name.endswith(".md") or name in SKIP_NAMES:
                continue
            if name in ROOT_ONLY_SKIP and Path(dirpath) == root:
                continue
            yield Path(dirpath) / name


# -------------------------------------------------------------------- sources


def from_file(path, root, front):
    """Everything derivable from the document itself."""
    out = {}
    text = path.read_text(encoding="utf-8", errors="replace")
    _, body, _ = parse(text, source=path)

    heading = next(
        (line[2:].strip() for line in body.splitlines() if line.startswith("# ")),
        None,
    )
    out["title"] = heading or path.stem.replace("-", " ").replace("_", " ").title()

    rel = path.relative_to(root)
    out["id"] = str(rel.with_suffix("")).replace(os.sep, "/")

    lowered = f"{rel} {out['title']}".lower()
    if "changelog" in lowered or "release" in lowered:
        out["type"] = "changelog"
    elif any(
        word in lowered for word in ("how-to", "howto", "guide", "tutorial", "getting-started")
    ):
        out["type"] = "procedure"
    elif any(word in lowered for word in ("api", "reference", "cli", "config")):
        out["type"] = "reference"
    elif rel.name in ("index.md", "overview.md"):
        out["type"] = "overview"
    else:
        out["type"] = "concept"

    out["managed"] = "manual"  # only the writer promotes a file to generated
    return out


def _git(root, *args):
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return proc.stdout if proc.returncode == 0 else ""


def from_git(path, root, front):
    """Last touched date, and an owner guess when nothing better exists."""
    rel = str(path.relative_to(root))
    out = {}
    date = _git(root, "log", "-1", "--format=%aI", "--", rel).strip()
    if date:
        out["lastUpdated"] = date[:10]
    if not front.get("owner"):
        authors = _git(root, "shortlog", "-sne", "HEAD", "--", rel).strip().splitlines()
        if authors:
            match = re.search(r"<([^>]+)>", authors[0])
            if match:
                out["owner"] = match.group(1)
    return out


def from_context(path, root, front, context):
    """Provenance from the git-context and relevance artifacts."""
    if not context:
        return {}
    out = {"generator": context.get("generator", "docs-gen/0.1")}
    head = context.get("head")
    if head:
        out["source_sha"] = head[:12]

    declared = front.get("source_modules")
    if declared:
        return out

    rel = str(path.relative_to(root))
    inferred = [
        module for module, entry in context.get("modules", {}).items() if entry.get("doc") == rel
    ]
    if inferred:
        out["source_modules"] = sorted(inferred)
    return out


# ----------------------------------------------------------------------- mark


def mark(root, sources, force=False, write=False, docs_dir=None, context=None):
    changed, unchanged, skipped = [], 0, []
    for path in walk(root, docs_dir):
        try:
            original = path.read_text(encoding="utf-8", errors="replace")
            front, body, _ = parse(original, source=path)
        except (OSError, UnicodeDecodeError, MetaError) as exc:
            # Guarded the way the sweep and the staleness join are. One page
            # nobody can parse must not leave every other page unstamped, and
            # the caller allows this command's exit codes, so the page is
            # named in the result rather than dropped.
            skipped.append({"doc": str(path.relative_to(root)), "reason": str(exc)})
            continue
        merged = dict(front)

        derived = {}
        if "file" in sources:
            derived.update(from_file(path, root, front))
        if "git" in sources:
            derived.update(from_git(path, root, front))
        if "context" in sources:
            derived.update(from_context(path, root, front, context))

        for key, value in derived.items():
            # Fill-when-absent is what keeps descriptions and tags from churning
            # across runs. --force is the deliberate override, except that
            # source inspection must never demote an explicitly managed file.
            if key == "managed" and key in merged:
                continue
            if force or key not in merged or merged[key] in (None, "", []):
                merged[key] = value

        updated = render(merged, body)
        if updated == original:
            unchanged += 1
            continue
        changed.append(str(path.relative_to(root)))
        if write:
            path.write_text(updated, encoding="utf-8")

    return {"changed": changed, "unchanged": unchanged, "skipped": skipped, "written": write}


# ------------------------------------------------------------------- validate


def validate(root, strict=False, docs_dir=None):
    errors, warnings = [], []
    seen_ids = {}

    for path in walk(root, docs_dir):
        rel = str(path.relative_to(root))
        try:
            front, _, had = parse(path.read_text(encoding="utf-8", errors="replace"), source=rel)
        except MetaError as exc:
            errors.append(str(exc))
            continue
        if not had:
            errors.append(f"{rel}: no frontmatter")
            continue

        for field in REQUIRED:
            if not front.get(field):
                errors.append(f"{rel}: missing required field '{field}'")

        kind = front.get("type")
        if kind and kind in LEGACY_TYPES:
            warnings.append(
                f"{rel}: type '{kind}' was renamed to '{LEGACY_TYPES[kind]}'; "
                "it still validates, and the next write will update it"
            )
        elif kind and kind not in TYPES:
            errors.append(f"{rel}: type '{kind}' not in {list(TYPES)}")
        if front.get("managed") and front["managed"] not in MANAGED:
            errors.append(f"{rel}: managed '{front['managed']}' not in {list(MANAGED)}")
        if front.get("source_sha") and not SHA.match(str(front["source_sha"])):
            errors.append(f"{rel}: source_sha is not a hex SHA")

        if front.get("managed") in ("generated", "assisted"):
            if not front.get("source_modules"):
                warnings.append(
                    f"{rel}: {front['managed']} without source_modules; "
                    "staleness cannot be detected"
                )
            if not front.get("source_sha"):
                warnings.append(f"{rel}: {front['managed']} without source_sha")

        doc_id = front.get("id")
        if doc_id:
            if doc_id in seen_ids:
                errors.append(f"{rel}: duplicate id, also in {seen_ids[doc_id]}")
            seen_ids[doc_id] = rel

        description = front.get("description") or ""
        if description and len(description) > 300:
            warnings.append(f"{rel}: description over 300 characters")

    if strict:
        errors.extend(warnings)
        warnings = []
    return {"errors": errors, "warnings": warnings, "checked": len(seen_ids)}


# ---------------------------------------------------------------------- index


def build_index(root, docs_dir=None):
    entries = []
    for path in walk(root, docs_dir):
        try:
            front, _, had = parse(path.read_text(encoding="utf-8", errors="replace"), source=path)
        except (OSError, UnicodeDecodeError, MetaError):
            # A page nobody can parse is one the index cannot describe. The
            # reviewer reports it; listing it here would be a lie.
            continue
        if not had:
            continue
        entries.append(
            {
                "path": str(path.relative_to(root)),
                "title": front.get("title", path.stem),
                "description": front.get("description", ""),
                "type": canonical_type(front.get("type", "concept")),
                "managed": front.get("managed", "manual"),
            }
        )
    return sorted(entries, key=lambda e: (e["type"], e["path"]))


def render_index(entries):
    lines = [INDEX_BEGIN, "", "## Documentation index", ""]
    for kind in TYPES:
        group = [e for e in entries if canonical_type(e["type"]) == kind]
        if not group:
            continue
        lines.append(f"### {kind.title()}")
        lines.append("")
        for entry in group:
            summary = f" — {entry['description']}" if entry["description"] else ""
            lines.append(f"- [{entry['title']}]({entry['path']}){summary}")
        lines.append("")
    lines.append(INDEX_END)
    return "\n".join(lines)


def write_index(root, out_path, docs_dir=None):
    """Replace only the marked region, so hand-written surroundings survive."""
    entries = build_index(root, docs_dir)
    block = render_index(entries)
    target = Path(root) / out_path

    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if INDEX_BEGIN in existing and INDEX_END in existing:
            start = existing.index(INDEX_BEGIN)
            end = existing.index(INDEX_END) + len(INDEX_END)
            updated = existing[:start] + block + existing[end:]
        else:
            updated = existing.rstrip("\n") + "\n\n" + block + "\n"
    else:
        updated = block + "\n"

    changed = not target.exists() or target.read_text(encoding="utf-8") != updated
    if changed:
        target.write_text(updated, encoding="utf-8")
    return {"path": str(out_path), "entries": len(entries), "changed": changed}


# -------------------------------------------------------------------- staleness


def stale(root, relevance, docs_dir=None):
    """Join source_modules against the relevance verdict."""
    rebuild = set(relevance.get("rebuild", []))
    queued, flagged = [], []
    for path in walk(root, docs_dir):
        try:
            front, _, had = parse(path.read_text(encoding="utf-8", errors="replace"), source=path)
        except (OSError, UnicodeDecodeError, MetaError):
            # This join gates the whole incremental chain, so one page nobody
            # can parse must not end the run for every page that parses.
            # `MetaError` subclasses `RuntimeError`, which is why catching
            # `ValueError` elsewhere did not cover it.
            continue
        if not had:
            continue
        modules = set(front.get("source_modules") or [])
        if not modules & rebuild:
            continue
        record = {
            "doc": str(path.relative_to(root)),
            "modules": sorted(modules & rebuild),
            "managed": front.get("managed", "manual"),
        }
        (queued if record["managed"] in ("generated", "assisted") else flagged).append(record)
    return {"queued": queued, "flagged": flagged}


# ------------------------------------------------------------------- commands


def emit(payload, out=None):
    text = json.dumps(payload, indent=2)
    if out:
        Path(out).write_text(text + "\n")
        print(json.dumps({"written": out}, indent=2))
    else:
        print(text)


def cmd_mark(args):
    context = json.loads(Path(args.context).read_text()) if args.context else None
    result = mark(
        args.repo, set(args.source.split(",")), args.force, args.write, args.docs_dir, context
    )
    emit(result, args.out)
    return 0


def cmd_validate(args):
    result = validate(args.repo, args.strict, args.docs_dir)
    emit(result, args.out)
    return 3 if result["errors"] else 0


def cmd_index(args):
    emit(write_index(args.repo, args.out_file, args.docs_dir))
    return 0


def cmd_stale(args):
    relevance = json.loads(Path(args.relevance).read_text())
    emit(stale(args.repo, relevance, args.docs_dir), args.out)
    return 0


def cmd_show(args):
    path = Path(args.file)
    front, body, had = parse(path.read_text(encoding="utf-8"), source=path)
    emit({"had_frontmatter": had, "frontmatter": front, "body_lines": len(body.splitlines())})
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-dir", help="Limit the walk to this subdirectory")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("mark", help="Fill absent metadata fields")
    p.add_argument("--repo", default=".")
    p.add_argument("--source", default="file,git", help="Comma-separated: file, git, context")
    p.add_argument("--context", help="git-context.json, required for the context source")
    p.add_argument("--force", action="store_true", help="Overwrite fields that already exist")
    p.add_argument("--write", action="store_true", help="Apply changes; otherwise dry run")
    p.add_argument("--out")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("validate", help="Check the corpus against the schema")
    p.add_argument("--repo", default=".")
    p.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    p.add_argument("--out")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("index", help="Write the documentation index")
    p.add_argument("--repo", default=".")
    p.add_argument("--out", dest="out_file", default="AGENTS.md")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("stale", help="Join source_modules against a relevance verdict")
    p.add_argument("--repo", default=".")
    p.add_argument("--relevance", required=True)
    p.add_argument("--out")
    p.set_defaults(func=cmd_stale)

    p = sub.add_parser("show", help="Print one file's frontmatter")
    p.add_argument("file")
    p.set_defaults(func=cmd_show)

    args = parser.parse_args()
    if yaml is None:
        print(json.dumps({"error": "PyYAML is required"}))
        return 1
    try:
        return args.func(args)
    except (MetaError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

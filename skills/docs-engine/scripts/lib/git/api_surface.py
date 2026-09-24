#!/usr/bin/env python3
"""Content-addressed public API snapshots."""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMA = "api-surface/1"

# Extensions we can fingerprint natively. Everything else needs --api-dir.
NATIVE = {".py"}

# A module whose changed files are all prose needs no rebuild on that alone.
DOC_SUFFIXES = {".md", ".rst", ".txt"}

WS = re.compile(r"\s+")


# --------------------------------------------------------------- fingerprints


def normalize(signature):
    """Collapse formatting so a reflow does not read as an API change."""
    return WS.sub(" ", (signature or "").strip())


def fingerprint(symbol):
    """Stable hash over the parts of a symbol a reader would notice changing."""
    payload = "|".join(
        [
            symbol.get("kind", ""),
            symbol.get("name", ""),
            normalize(symbol.get("signature", "")),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def rollup(fingerprints):
    """Order-independent hash of a symbol set."""
    joined = "".join(sorted(fingerprints))
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


# ------------------------------------------------------------ python extractor


def signature_of(node):
    args = node.args
    parts = []

    def expression(value):
        try:
            return ast.unparse(value)
        except Exception:
            return ast.dump(value, include_attributes=False)

    def parameter(arg, default=None, has_default=False):
        text = arg.arg
        if arg.annotation is not None:
            text += f": {expression(arg.annotation)}"
        if has_default:
            text += f"={expression(default)}"
        return text

    positional = args.posonlyargs + args.args
    default_offset = len(positional) - len(args.defaults)
    for index, arg in enumerate(positional):
        has_default = index >= default_offset
        default = args.defaults[index - default_offset] if has_default else None
        parts.append(parameter(arg, default, has_default))
        if args.posonlyargs and index == len(args.posonlyargs) - 1:
            parts.append("/")
    if args.vararg:
        parts.append("*" + parameter(args.vararg))
    elif args.kwonlyargs:
        parts.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        parts.append(parameter(arg, default, default is not None))
    if args.kwarg:
        parts.append("**" + parameter(args.kwarg))
    returns = ""
    if node.returns is not None:
        returns = " -> " + expression(node.returns)
    return f"{node.name}({', '.join(parts)}){returns}"


def extract_python(path, rel):
    """Public functions and classes via stdlib ast. Underscore names are private."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return []
    symbols = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            symbols.append(
                {
                    "name": node.name,
                    "kind": "function",
                    "file": rel,
                    "line": node.lineno,
                    "signature": signature_of(node),
                }
            )
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            bases = []
            for base in node.bases:
                try:
                    bases.append(ast.unparse(base))
                except Exception:
                    pass
            symbols.append(
                {
                    "name": node.name,
                    "kind": "class",
                    "file": rel,
                    "line": node.lineno,
                    "signature": f"class {node.name}({', '.join(bases)})",
                }
            )
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("_") and child.name != "__init__":
                        continue
                    symbols.append(
                        {
                            "name": f"{node.name}.{child.name}",
                            "kind": "method",
                            "file": rel,
                            "line": child.lineno,
                            "signature": signature_of(child),
                        }
                    )
    return symbols


# ------------------------------------------------------------------- registry


def usable_modules(out_dir):
    """This run's `api-surface.json`, or `{}` plus why it was not usable."""
    out_dir = Path(out_dir)
    surface_path = out_dir / "api-surface.json"
    if not surface_path.is_file():
        return {}, "no api-surface.json for this run"
    try:
        surface = json.loads(surface_path.read_text())
    except json.JSONDecodeError:
        return {}, "api-surface.json is not valid JSON"

    return surface, ""


# ------------------------------------------------------------------- registry


def load_registry(path):
    data = json.loads(Path(path).read_text())
    mapping = {}
    if isinstance(data, dict) and isinstance(data.get("modules"), dict):
        data = data["modules"]
    if isinstance(data, list):
        for entry in data:
            name = entry.get("name") or entry.get("module")
            prefixes = entry.get("paths") or entry.get("path") or name
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            if name and prefixes:
                mapping[name] = [p.rstrip("/") for p in prefixes]
    else:
        for name, prefixes in data.items():
            if isinstance(prefixes, dict):
                prefixes = prefixes.get("paths") or prefixes.get("path") or name
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            if isinstance(prefixes, (list, tuple)):
                mapping[name] = [p.rstrip("/") for p in prefixes if isinstance(p, str)]
    return mapping


def registry_hash(mapping):
    """Hash of module boundaries alone."""
    canonical = json.dumps({k: sorted(v) for k, v in sorted(mapping.items())}, sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def walk_module(root, prefixes, excludes=()):
    for prefix in prefixes:
        base = Path(root) / prefix
        if not base.exists():
            continue
        if base.is_file():
            yield base
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in excludes and not d.startswith(".")]
            for filename in filenames:
                yield Path(dirpath) / filename


# ------------------------------------------------------------------- snapshot


def ingest_api_dir(path):
    """Read pre-extracted API JSON produced by a language-specific extractor."""
    result = {}
    target = Path(path)
    if target.is_file():
        data = json.loads(target.read_text())
        for module, symbols in data.items():
            result[module] = symbols if isinstance(symbols, list) else symbols.get("public_api", [])
        return result
    for file in sorted(target.glob("*.json")):
        data = json.loads(file.read_text())
        if isinstance(data, list):
            result[file.stem] = data
            continue
        symbols = data.get("public_api") or data.get("exports") or []
        result[data.get("module") or file.stem] = symbols
    return result


def build_snapshot(root, mapping, api_dir=None, excludes=("node_modules", "vendor", "__pycache__")):
    external = ingest_api_dir(api_dir) if api_dir else {}
    modules = {}
    for module, prefixes in sorted(mapping.items()):
        symbols = list(external.get(module, []))
        covered = {s.get("file") for s in symbols}
        for file in walk_module(root, prefixes, excludes):
            if file.suffix not in NATIVE:
                continue
            rel = str(file.relative_to(root))
            if rel in covered:
                continue
            symbols.extend(extract_python(file, rel))
        entries = {}
        for symbol in symbols:
            key = f"{symbol.get('kind')}:{symbol.get('name')}"
            entries[key] = {
                "fp": fingerprint(symbol),
                "file": symbol.get("file"),
                "line": symbol.get("line"),
                "signature": normalize(symbol.get("signature", "")),
            }
        modules[module] = {
            "hash": rollup(e["fp"] for e in entries.values()),
            "symbol_count": len(entries),
            "symbols": dict(sorted(entries.items())),
            "source": "external" if module in external else "native",
        }
    return {
        "schema": SCHEMA,
        "registry_hash": registry_hash(mapping),
        "api_hash": rollup(m["hash"] for m in modules.values()),
        "modules": modules,
    }


def snapshot_at(repo, ref, mapping, api_dir=None):
    """Extract from a detached worktree so old surfaces can be rebuilt on demand."""
    resolved = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if resolved.returncode != 0:
        raise RuntimeError(f"Cannot resolve ref {ref!r} in {repo}")
    ref = resolved.stdout.strip()

    tmp = tempfile.mkdtemp(prefix="api-surface-")
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "--detach", tmp, ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"worktree add {ref}: {proc.stderr.strip()}")
        result = build_snapshot(tmp, mapping, api_dir)
        result["ref"] = ref
        return result
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", tmp],
            capture_output=True,
            check=False,
        )
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ commands


def diff_snapshots(before, after):
    modules = {}
    names = set(before["modules"]) | set(after["modules"])
    for module in sorted(names):
        old = before["modules"].get(module, {"symbols": {}, "hash": None})
        new = after["modules"].get(module, {"symbols": {}, "hash": None})
        if old["hash"] == new["hash"] and old["hash"] is not None:
            continue
        old_syms, new_syms = old.get("symbols", {}), new.get("symbols", {})
        added = sorted(set(new_syms) - set(old_syms))
        removed = sorted(set(old_syms) - set(new_syms))
        changed, moved = [], []
        for key in sorted(set(old_syms) & set(new_syms)):
            if old_syms[key]["fp"] != new_syms[key]["fp"]:
                changed.append(
                    {
                        "symbol": key,
                        "before": old_syms[key]["signature"],
                        "after": new_syms[key]["signature"],
                    }
                )
            elif old_syms[key].get("file") != new_syms[key].get("file"):
                moved.append(
                    {
                        "symbol": key,
                        "before": old_syms[key].get("file"),
                        "after": new_syms[key].get("file"),
                    }
                )
        modules[module] = {
            "added": added,
            "removed": removed,
            "changed": changed,
            "moved": moved,
            "before_hash": old["hash"],
            "after_hash": new["hash"],
        }
    return {
        "schema": "api-diff/1",
        # Modules present in the snapshot but absent from `modules` below had an
        # unchanged surface. Distinguishing that from "never analysed" is what
        # stops a whitespace reflow being escalated for review.
        "known_modules": sorted(set(before["modules"]) | set(after["modules"])),
        "registry_changed": before.get("registry_hash") != after.get("registry_hash"),
        "api_changed": before.get("api_hash") != after.get("api_hash"),
        "modules": modules,
    }


# ------------------------------------------------------------------ relevance


def classify(git_context, api_diff):
    """Decide, per module, whether documentation needs regenerating.

    Deterministic signals only. Anything genuinely ambiguous is marked `review`
    and handed upward rather than guessed at.
    """
    if api_diff.get("registry_changed"):
        return {
            "schema": "doc-relevance/1",
            "verdict": "full_rebuild",
            "reason": "Module boundaries moved. Prior attribution is untrustworthy.",
            "modules": {},
        }

    # git-context records breaking changes by short SHA and module commits by
    # full SHA, so compare on the shorter of the two.
    breaking_shas = {b["sha"] for b in git_context.get("summary", {}).get("breaking_changes", [])}

    def is_breaking(shas):
        return any(
            full.startswith(short) or short.startswith(full)
            for full in shas
            for short in breaking_shas
        )

    touched = git_context.get("modules", {})
    diffs = api_diff.get("modules", {})
    known = set(api_diff.get("known_modules", []))
    files = git_context.get("files", {})

    modules = {}
    for module, change in touched.items():
        surface = diffs.get(module)
        module_files = change.get("files", [])
        doc_only = module_files and all(Path(f).suffix in DOC_SUFFIXES for f in module_files)
        flagged = is_breaking(change.get("commits", []))

        surface_known = surface is not None or module in known

        if surface and (surface["removed"] or surface["changed"]):
            verdict, reason = "rebuild", "Public symbols removed or re-signed"
        elif surface and surface["added"]:
            verdict, reason = "rebuild", "Public symbols added"
        elif surface and surface["moved"]:
            verdict, reason = "update_refs", "Symbols moved file without changing signature"
        elif surface is None and module in known:
            # A commit-level BREAKING CHANGE marker applies to the repository,
            # not to every module the commit incidentally touched. When the
            # fingerprint says this module's surface held still, trust it.
            verdict, reason = "skip", "Public surface fingerprint is unchanged"
        elif doc_only:
            verdict, reason = "skip", "Only documentation files changed"
        elif flagged:
            verdict, reason = (
                "rebuild",
                "Commit declares a breaking change, no surface data to check",
            )
        elif module_files:
            verdict, reason = "review", "Source changed with no API surface data"
        else:
            verdict, reason = "skip", "Change did not reach the public surface"

        modules[module] = {
            "verdict": verdict,
            "reason": reason,
            "breaking": bool(surface and surface["removed"])
            or (flagged and (not surface_known or bool(surface and surface["changed"]))),
            "files_changed": len(module_files),
            "added": len(surface["added"]) if surface else 0,
            "removed": len(surface["removed"]) if surface else 0,
            "changed": len(surface["changed"]) if surface else 0,
            "commits": change.get("commits", []),
        }

    unattributed = sorted(p for p, v in files.items() if not v.get("module"))
    rebuild = [m for m, v in modules.items() if v["verdict"] in ("rebuild", "update_refs")]
    return {
        "schema": "doc-relevance/1",
        "verdict": "incremental" if rebuild else "no_op",
        "rebuild": sorted(rebuild),
        "review": sorted(m for m, v in modules.items() if v["verdict"] == "review"),
        "unattributed_files": unattributed[:50],
        "modules": dict(sorted(modules.items())),
    }


# ------------------------------------------------------------------ commands


def emit(payload, out=None):
    text = json.dumps(payload, indent=2)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n")
        print(json.dumps({"written": out, "bytes": len(text)}, indent=2))
    else:
        print(text)


def cmd_snapshot(args):
    mapping = load_registry(args.registry)
    if args.at:
        payload = snapshot_at(args.repo, args.at, mapping, args.api_dir)
    else:
        payload = build_snapshot(args.repo, mapping, args.api_dir)
    emit(payload, args.out)
    return 0


def cmd_diff(args):
    before = json.loads(Path(args.before).read_text())
    after = json.loads(Path(args.after).read_text())
    emit(diff_snapshots(before, after), args.out)
    return 0


def cmd_relevance(args):
    git_context = json.loads(Path(args.git_context).read_text())
    api_diff = json.loads(Path(args.api_diff).read_text())
    emit(classify(git_context, api_diff), args.out)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("snapshot", help="Fingerprint the public API surface")
    p.add_argument("--repo", default=".")
    p.add_argument("--registry", required=True)
    p.add_argument("--at", help="Snapshot a past ref via a temporary worktree")
    p.add_argument("--api-dir", help="Pre-extracted API JSON for non-native languages")
    p.add_argument("--out")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("diff", help="Compare two snapshots")
    p.add_argument("--before", required=True)
    p.add_argument("--after", required=True)
    p.add_argument("--out")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("relevance", help="Decide what needs regenerating")
    p.add_argument("--git-context", required=True)
    p.add_argument("--api-diff", required=True)
    p.add_argument("--out")
    p.set_defaults(func=cmd_relevance)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

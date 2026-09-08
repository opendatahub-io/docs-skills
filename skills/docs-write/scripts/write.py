#!/usr/bin/env python3
"""Generate or update one Markdown document per module.

Ownership is enforced here, in the script, not in the prompt. The four
`managed` behaviours are the contract:

    absent      create the file, stamp `managed: generated`
    generated   regenerate the body, preserve frontmatter a human set
    assisted    rewrite only the docs-gen fenced regions, byte-identical outside
    manual      never open the file for writing; emit a staleness finding

A `manual` file's path never reaches a write call, and an `assisted` file's
prose never reaches the model. No prompt wording can move either boundary,
which is the point of putting them here.

    python3 write.py --repo . --out .docs-gen --relevance .docs-gen/relevance.json \
        --llm-cmd "claude -p"
"""

import argparse
import json
import os
import sys
from pathlib import Path


def _find_engine():
    """Locate the docs-engine skill, which holds the generator's shared runtime.

    An installer copies each skill directory on its own and drops symlinks on
    the way, so a tree shared above the skills cannot be linked in and does not
    survive the copy. It does land every skill as a flat sibling, and that is
    what this walk uses: docs-engine sits two levels up from any generator
    skill's script, in an install and in a checkout alike.

    Nothing reads a plugin root from the environment, because no harness sets
    one.
    """
    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        if (base / "scripts" / "lib" / "run" / "step.py").exists():
            return base
        sibling = base / "docs-engine"
        if (sibling / "scripts" / "lib" / "run" / "step.py").exists():
            return sibling
    raise SystemExit(
        "docs-skills: cannot find the docs-engine skill. It ships alongside this "
        "one and carries the shared runtime; install it, or run from a checkout."
    )


ENGINE = _find_engine()
sys.path.insert(0, str(ENGINE / "scripts"))

PROMPTS = ENGINE / "prompts"
SCHEMAS = ENGINE / "schemas"
LANGUAGES = ENGINE / "languages"
CONFIG = ENGINE / "config"

from lib.md import docs_meta, fences, language_file, render  # noqa: E402
from lib.run import step  # noqa: E402

GENERATOR = "docs-skills/0.5.0"

SCHEMA = "docs-skills/write/1"


def slug(module):
    return module.replace("/", "__").replace("\\", "__") or "root"


# ------------------------------------------------------------------ ownership


def ownership(path):
    """Read a document's `managed` value. A file that is not there is `absent`."""
    if not path.exists():
        return "absent", {}, ""
    text = path.read_text()
    front, body, _ = docs_meta.parse(text)
    return front.get("managed", "manual"), front, text


def existing_summary(text, front, limit=12000):
    """What the writer may see of an existing document.

    An `assisted` file hands over only its fenced regions. The prose around
    them is the human's, and a model that never receives it cannot restate it,
    drift from it, or be talked into replacing it.
    """
    if front.get("managed") == "assisted":
        try:
            regions = fences.parse(text)
        except fences.FenceError as exc:
            raise WriteRefusedError(f"fence structure is broken: {exc}")
        return {
            "managed": "assisted",
            "regions": [
                {"section": r.section, "source": r.source, "body": r.body[:4000]} for r in regions
            ],
        }
    return {
        "managed": front.get("managed", "generated"),
        "frontmatter": front,
        "body": text[:limit],
    }


class WriteRefusedError(RuntimeError):
    """The ownership contract forbids this write."""


# --------------------------------------------------------------- writer input


def read_tests(repo, module_paths, globs, budget=20000):
    """Test files under the module, as usage evidence.

    Tests show the API being called for real, with the imports and setup a
    reader needs. An example lifted from a test breaks the test suite when it
    rots; an invented one rots silently.
    """
    found, used = [], 0
    for prefix in module_paths:
        base = Path(repo) / prefix
        if not base.is_dir():
            continue
        for pattern in globs or ["test_*.py", "*_test.go", "*.test.ts"]:
            for path in sorted(base.rglob(pattern)):
                try:
                    text = path.read_text(errors="replace")
                except OSError:
                    continue
                if used + len(text) > budget:
                    continue
                found.append({"file": str(path.relative_to(repo)), "content": text})
                used += len(text)
    return found


def build_input(repo, module, registry, out_dir, doc_type, target, git_context):
    entry = registry["modules"][module]
    api_path = Path(out_dir) / "api" / f"{slug(module)}.json"
    surface_path = Path(out_dir) / "api-surface.json"

    symbols = []
    if api_path.exists():
        symbols = json.loads(api_path.read_text()).get("public_api", [])
    elif surface_path.exists():
        surface = json.loads(surface_path.read_text())
        for key, value in (surface["modules"].get(module, {}).get("symbols") or {}).items():
            kind, _, name = key.partition(":")
            symbols.append(
                {
                    "name": name,
                    "kind": kind,
                    "file": value.get("file"),
                    "line": value.get("line"),
                    "signature": value.get("signature"),
                }
            )

    analysis_path = Path(out_dir) / "modules" / f"{slug(module)}.json"
    analysis = json.loads(analysis_path.read_text()) if analysis_path.exists() else None

    git_slice = {}
    if git_context:
        # Attribution lives in the top-level modules map as a SHA list; commit
        # records carry no module of their own.
        rollup = (git_context.get("modules") or {}).get(module, {})
        shas = set(rollup.get("commits") or [])
        commits = [
            {
                "subject": c.get("subject"),
                "type": c.get("type"),
                "scope": c.get("scope"),
                "breaking": c.get("breaking"),
                "pr": c.get("pr"),
                "issues": c.get("issues"),
                "short": c.get("short"),
            }
            for c in git_context.get("commits", [])
            if c.get("sha") in shas
        ]
        git_slice = {
            "commits": commits[:60],
            "files": rollup.get("files", [])[:100],
            "adds": rollup.get("adds", 0),
            "dels": rollup.get("dels", 0),
            "breaking_changes": git_context.get("summary", {}).get("breaking_changes", []),
        }

    return {
        "module": module,
        "kind": entry.get("kind", "library"),
        "language": registry["language"],
        "paths": entry["paths"],
        "doc_type": doc_type,
        "path": str(target),
        "public_api": symbols[:400],
        "analysis": analysis,
        "git": git_slice,
    }


# ---------------------------------------------------------------- write paths


def write_generated(target, payload, front_extra, floor):
    """Whole-file ownership. The writer owns the body; humans keep their keys."""
    existing_front = {}
    existing_text = None
    if target.exists():
        existing_text = target.read_text()
        existing_front, _, _ = docs_meta.parse(existing_text)

    front = render.merge_front(
        existing_front,
        {**(payload.get("frontmatter") or {}), **front_extra, "managed": "generated"},
        preserve=("owner", "tags"),
    )
    if existing_front.get("managed") == "manual":
        raise WriteRefusedError("file is managed: manual")

    text = render.document(payload, front_overrides=front)
    write, reason = render.worth_writing(existing_text, text, floor)
    if not write:
        return False, reason
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return True, reason


def write_assisted(target, payload, sha):
    """Within-file ownership. Only the fenced regions move."""
    text = target.read_text()
    try:
        regions = {r.section for r in fences.parse(text)}
    except fences.FenceError as exc:
        raise WriteRefusedError(f"fence structure is broken: {exc}")
    if not regions:
        raise WriteRefusedError("managed: assisted but the file has no docs-gen regions")

    original = text
    touched, skipped = [], []
    for section in payload.get("sections") or []:
        if section["id"] not in regions:
            skipped.append(section["id"])
            continue
        body = render.normalize(section.get("body") or "")
        text = fences.replace(text, section["id"], body, sha=sha)
        touched.append(section["id"])

    if text == original:
        return False, "no fenced region changed", skipped
    target.write_text(text)
    return True, f"rewrote {', '.join(touched)}", skipped


# ------------------------------------------------------------------- the pass


def write_module(repo, module, registry, out_dir, docs_dir, lang, args, git_context):
    entry = registry["modules"][module]
    doc_types = lang.doc_types(entry.get("kind", "library"))
    if not doc_types:
        return [{"module": module, "status": "skipped", "reason": "no doc types"}]

    prompt = (PROMPTS / "write-module.md").read_text()
    schema = json.loads((SCHEMAS / "write-out.json").read_text())
    results = []

    for doc_type in doc_types:
        if doc_type == "reference" and lang.generator:
            results.append(
                {
                    "module": module,
                    "doc_type": doc_type,
                    "status": "deferred",
                    "reason": f"{lang.generator['tool']} generates reference",
                }
            )
            continue

        name = slug(module) if doc_type == "concept" else f"{slug(module)}-{doc_type}"
        target = Path(repo) / docs_dir / f"{name}.md"
        managed, front, text = ownership(target)

        if managed == "manual":
            results.append(
                {
                    "module": module,
                    "doc_type": doc_type,
                    "path": str(target.relative_to(repo)),
                    "status": "refused",
                    "reason": "managed: manual",
                }
            )
            continue

        payload = build_input(
            repo,
            module,
            registry,
            out_dir,
            doc_type,
            target.relative_to(repo),
            git_context,
        )
        try:
            if managed != "absent":
                payload["existing"] = existing_summary(text, front)
            payload["tests"] = read_tests(repo, entry["paths"], lang.front.get("test_globs"))
        except WriteRefusedError as exc:
            results.append(
                {
                    "module": module,
                    "doc_type": doc_type,
                    "path": str(target.relative_to(repo)),
                    "status": "refused",
                    "reason": str(exc),
                }
            )
            continue

        print(f"docs-write: {module} -> {target.relative_to(repo)}", file=sys.stderr)
        try:
            result, _ = step.run_step(
                prompt,
                payload,
                schema,
                args.llm_cmd,
                args.timeout,
                values={"language_body": lang.body, "doc_type": doc_type},
            )
        except (step.StepError, RuntimeError) as exc:
            results.append(
                {
                    "module": module,
                    "doc_type": doc_type,
                    "status": "failed",
                    "reason": str(exc)[:400],
                }
            )
            continue

        sha = (git_context or {}).get("head", "")[:7]
        record = {
            "module": module,
            "doc_type": doc_type,
            "path": str(target.relative_to(repo)),
            "evidence": result.get("evidence", []),
            "gaps": result.get("gaps", []),
        }
        try:
            if managed == "assisted":
                wrote, reason, skipped = write_assisted(target, result, sha)
                record["unmatched_sections"] = skipped
            else:
                wrote, reason = write_generated(
                    target,
                    result,
                    {
                        "source_modules": [module],
                        "source_sha": sha,
                        "generator": GENERATOR,
                    },
                    args.floor,
                )
        except (WriteRefusedError, fences.FenceError) as exc:
            record.update(status="refused", reason=str(exc))
        else:
            record.update(status="written" if wrote else "unchanged", reason=reason)
        results.append(record)

    return results


# ------------------------------------------------------------------------ cli


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write Markdown docs per module")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", default=".docs-gen")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--relevance", help="Write only the modules in rebuild[]")
    parser.add_argument("--modules", nargs="*", help="Write these modules explicitly")
    parser.add_argument("--llm-cmd", default=os.environ.get("DOCS_LLM_CMD", "claude -p"))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--floor", type=int, default=render.DEFAULT_FLOOR)
    parser.add_argument("--max-modules", type=int, default=0, help="0 means no cap")
    parser.add_argument("--languages-dir", default=str(LANGUAGES))
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out)
    registry_path = out_dir / "registry.json"
    if not registry_path.exists():
        print(f"docs-write: no registry at {registry_path}", file=sys.stderr)
        return 2
    registry = json.loads(registry_path.read_text())

    try:
        lang = language_file.for_language(registry["language"], args.languages_dir)
    except language_file.LanguageFileError as exc:
        print(f"docs-write: {exc}", file=sys.stderr)
        return 2

    if args.modules:
        modules = [m for m in args.modules if m in registry["modules"]]
    elif args.relevance:
        relevance = json.loads(Path(args.relevance).read_text())
        modules = list(relevance.get("rebuild") or [])
    else:
        modules = list(registry["modules"])

    if not modules:
        print("docs-write: nothing to write", file=sys.stderr)
        return 1
    if args.max_modules:
        modules = modules[: args.max_modules]

    context_path = out_dir / "git-context.json"
    git_context = json.loads(context_path.read_text()) if context_path.exists() else {}

    results = []
    for module in modules:
        if module not in registry["modules"]:
            results.append({"module": module, "status": "skipped", "reason": "not in registry"})
            continue
        results.extend(
            write_module(repo, module, registry, out_dir, args.docs_dir, lang, args, git_context)
        )

    report = {
        "schema": SCHEMA,
        "docs_dir": args.docs_dir,
        "written": [r for r in results if r.get("status") == "written"],
        "unchanged": [r for r in results if r.get("status") == "unchanged"],
        "refused": [r for r in results if r.get("status") == "refused"],
        "failed": [r for r in results if r.get("status") == "failed"],
        "deferred": [r for r in results if r.get("status") == "deferred"],
        "results": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "write-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(
        "docs-write: {written} written, {unchanged} unchanged, {refused} refused, "
        "{failed} failed".format(
            written=len(report["written"]),
            unchanged=len(report["unchanged"]),
            refused=len(report["refused"]),
            failed=len(report["failed"]),
        ),
        file=sys.stderr,
    )
    if report["failed"]:
        return 3
    return 0 if report["written"] else 1


if __name__ == "__main__":
    sys.exit(main())

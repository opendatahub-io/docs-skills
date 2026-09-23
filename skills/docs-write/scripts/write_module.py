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

    python3 write.py --repo . --out .docs-gen --modules pkg/queue pkg/scheduler \
        --llm-cmd "claude -p"
"""

import argparse
import json
import os
import sys
from pathlib import Path

# docs-engine carries the shared runtime and lands as a flat sibling of this
# skill, in an install and in a checkout alike. Saying so here, rather than
# letting the import fail, names what is missing when it is missing.
ENGINE = Path(__file__).resolve().parents[2] / "docs-engine"
if not (ENGINE / "scripts" / "lib" / "run" / "step.py").exists():
    raise SystemExit(
        "docs-skills: the docs-engine skill is missing. It ships alongside this one "
        "and carries the shared runtime; install it, or run from a checkout."
    )
sys.path.insert(0, str(ENGINE / "scripts"))

from lib.md import docs_meta, fences, language_file, render  # noqa: E402
from lib.md.ownership import (  # noqa: E402
    WriteRefusedError,
    existing_summary,
    ownership,
    write_assisted,
)
from lib.run import step  # noqa: E402
from lib.run.engine import LANGUAGES, PROMPTS, SCHEMAS  # noqa: E402
from lib.run.report import logger  # noqa: E402
from lib.vale import check  # noqa: E402
from lib.vale.repair import lint_document, repair_request  # noqa: E402

log = logger("docs-write")

GENERATOR = "docs-skills/0.4.0"

SCHEMA = "docs-skills/write/1"


def slug(module):
    return module.replace("/", "__").replace("\\", "__") or "root"


# ------------------------------------------------------------------ ownership


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


# ---------------------------------------------------------------------- prose


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

        log(f"{module} -> {target.relative_to(repo)}")
        sha = (git_context or {}).get("head", "")[:7]
        attempts = max(1, getattr(args, "vale_attempts", 1))
        wrote_any = False
        wrote_reason = ""
        vale_config = getattr(args, "vale_config", None)
        level = getattr(args, "vale_level", "error")
        attempt_prompt = prompt
        attempt_payload = payload
        attempt_values = {"language_body": lang.body, "doc_type": doc_type}
        record = None

        for attempt in range(1, attempts + 1):
            try:
                result, _ = step.run_step(
                    attempt_prompt,
                    attempt_payload,
                    schema,
                    args.llm_cmd,
                    args.timeout,
                    values=attempt_values,
                )
            except (step.StepError, RuntimeError) as exc:
                record = {
                    "module": module,
                    "doc_type": doc_type,
                    "status": "failed",
                    "reason": str(exc)[:400],
                }
                break

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
                break
            # Whether any attempt put text on disk, not whether the last one
            # did: a repair pass that repeats itself places the same bytes and
            # reports `unchanged`, which describes the attempt correctly and
            # the run wrongly now that the page is kept rather than discarded.
            wrote_any = wrote_any or wrote
            wrote_reason = reason if wrote else wrote_reason
            record.update(
                status="written" if wrote_any else "unchanged",
                reason=wrote_reason if wrote_any else reason,
            )

            # An unchanged first attempt is a previous run's file, which that
            # run already gated, so linting it again learns nothing. A later
            # attempt coming back unchanged is the model repeating itself,
            # and that copy is dirty prose this loop just wrote.
            if not wrote and attempt == 1:
                break

            alerts = lint_document(target, vale_config, level, log=log)
            if alerts is None:
                record["prose"] = "skipped"
                break

            record["prose_attempts"] = attempt

            # The alerts that carry their own answer are applied here, so the
            # model is only ever sent the ones that need a writer.
            if alerts:
                applied = check.apply_fixes(target, alerts)
                if applied:
                    record["prose_autofixed"] = record.get("prose_autofixed", 0) + len(applied)
                    alerts = lint_document(target, vale_config, level, log=log)
                    if alerts is None:
                        record["prose"] = "skipped"
                        break

            if not alerts:
                record["prose"] = "clean"
                break

            if attempt == attempts:
                # The draft stands and the alerts travel with it, the same
                # policy the topic writer follows. A rule surviving this many
                # repair passes is usually a rule reading the document wrong,
                # and throwing the page away spent every model call that
                # produced it for nothing a person can look at.
                named = "; ".join(f"{a.check} line {a.line}" for a in alerts[:5])
                record.update(
                    prose="dirty",
                    prose_unresolved=[f"{a.check} line {a.line}: {a.message}" for a in alerts],
                    prose_reason=f"prose still fails after {attempt} attempt(s): {named}",
                )
                break

            attempt_prompt, attempt_payload = repair_request(
                result, target.relative_to(repo), alerts, level
            )
            attempt_values = {}

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
    parser.add_argument(
        "--vale-config",
        default=os.environ.get("DOCS_VALE_CONFIG"),
        help="Composed Vale config. Omit to write without a prose gate",
    )
    parser.add_argument(
        "--vale-level",
        default="error",
        choices=sorted(check.SEVERITY_RANK),
        help="Lowest severity that sends the writer back",
    )
    parser.add_argument(
        "--vale-attempts",
        type=int,
        default=3,
        help="Total model calls per document, including the first",
    )
    parser.add_argument("--languages-dir", default=str(LANGUAGES))
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out)
    registry_path = out_dir / "registry.json"
    if not registry_path.exists():
        log(f"no registry at {registry_path}", "error")
        return 2
    registry = json.loads(registry_path.read_text())

    try:
        lang = language_file.for_language(registry["language"], args.languages_dir)
    except language_file.LanguageFileError as exc:
        log(f"{exc}", "error")
        return 2

    if args.modules:
        # Named modules are passed through whole, unknown ones included: the
        # per-module loop below records "not in registry" for each, which a
        # silent filter here turned into the indistinguishable "nothing to
        # write" -- the same message a run with genuinely nothing to do gives.
        unknown = [m for m in args.modules if m not in registry["modules"]]
        if unknown:
            log(f"not in the registry: {', '.join(unknown)}", "warning")
        modules = list(args.modules)
    elif args.relevance:
        relevance = json.loads(Path(args.relevance).read_text())
        modules = list(relevance.get("rebuild") or [])
    else:
        modules = list(registry["modules"])

    if not modules:
        log("nothing to write", "warning")
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
        # A module named on the command line that the registry does not carry
        # lands here. Without its own bucket it appeared only in `results`,
        # which is the one field a reader scanning the report skips.
        "skipped": [r for r in results if r.get("status") == "skipped"],
        "results": results,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "write-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    log(
        "{written} written, {unchanged} unchanged, {refused} refused, "
        "{failed} failed, {skipped} skipped".format(
            written=len(report["written"]),
            unchanged=len(report["unchanged"]),
            refused=len(report["refused"]),
            failed=len(report["failed"]),
            skipped=len(report["skipped"]),
        )
    )
    if report["failed"]:
        return 3
    return 0 if report["written"] else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Generate new Markdown topics or update published sections from a plan."""

import argparse
import json
import os
import re
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

from lib.run.engine import GENERATOR, LANGUAGES, PROMPTS, SCHEMAS  # noqa: E402

REFERENCE = Path(__file__).resolve().parents[1] / "reference"

from lib.foundation import evidence as foundation_evidence  # noqa: E402
from lib.git import api_surface, commit_select  # noqa: E402
from lib.md import changeset, docs_meta, fences, render  # noqa: E402
from lib.md.ownership import (  # noqa: E402
    WriteRefusedError,
    existing_summary,
    ownership,
    write_assisted,
)
from lib.run import step  # noqa: E402
from lib.run.report import logger  # noqa: E402
from lib.vale import check  # noqa: E402
from lib.vale.repair import lint_document, repair_request  # noqa: E402

log = logger("docs-write")


SCHEMA = "docs-skills/write/1"

# Lower than commit_select.DEFAULT_LIMIT of 30, the run-wide cut plan.py
# forwards. A deliverable is a narrower subject than the run, and by the
# time a commit reaches this payload it sits behind the published excerpts and
# up to 400 API symbols. More would crowd out what already carries the page.
CHANGES_LIMIT = 8

ARCHETYPES = {
    "concept": "markdown-concept.md",
    "procedure": "markdown-task.md",
    "task": "markdown-task.md",
    "reference": "markdown-reference.md",
}

FOUNDATION_ARCHETYPES = {
    "readme": "foundation-readme.md",
    "get-started": "foundation-get-started.md",
    "architecture": "foundation-architecture.md",
    "security": "foundation-security.md",
    "roadmap": "foundation-roadmap.md",
}

# Module paths that are not API. A test names the thing it tests, so it scores
# well against any subject and is exactly what a document must not cite.
_TEST_PATHS = ("/test", "test/", "tests/", "/tests", "conftest", "_test", "benchmark")

# Words that match everything and therefore select nothing.
_SUBJECT_STOP = {
    "the",
    "and",
    "for",
    "with",
    "how",
    "use",
    "using",
    "from",
    "into",
    "not",
    "does",
    "this",
    "that",
    "its",
    "can",
    "are",
    "was",
}


def _escapes(path, base):
    """Whether `path` resolves outside `base`."""
    try:
        path.resolve().relative_to(base.resolve())
        return False
    except ValueError:
        return True


def archetype_for(doc_type, foundation=None):
    """The plain Markdown example that gives a page its shape.

    A foundation stem picks the archetype written for that document. Anything
    else falls back to the archetype for its type, which is what a `--topic`
    deliverable has always used.
    """
    name = FOUNDATION_ARCHETYPES.get(foundation) if foundation else None
    name = name or ARCHETYPES.get(doc_type)
    if not name:
        return ""
    return (REFERENCE / name).read_text()


# ---------------------------------------------------------------- write paths


def write_generated(target, payload, front_extra, floor, marker=None):
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
    if marker:
        marked_front, body, _ = docs_meta.parse(text)
        wrapped = render.wrap_marker(body, marker)
        text = docs_meta.render(marked_front, wrapped) if marked_front else wrapped
    write, reason = render.worth_writing(existing_text, text, floor)
    if not write:
        return False, reason
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return True, reason


# ------------------------------------------------------------------- the pass


def run_with_repair(prompt, payload, schema, args, values, place, lint_path):
    """Call the model, place the result, lint it, and send it back until clean."""
    attempts = max(1, getattr(args, "vale_attempts", 1))
    config = getattr(args, "vale_config", None)
    level = getattr(args, "vale_level", "error")
    attempt_prompt, attempt_payload, attempt_values = prompt, payload, values
    fields = {}
    result = None
    # Whether any attempt put text on disk, rather than whether the last one
    # did. A repair pass that repeats itself places the same bytes and reports
    # `unchanged`, which is true of the attempt and false of the run.
    wrote_any = False
    # And what that write reported. A repeat attempt reports `identical`,
    # which is true of the attempt and says nothing about a run that created
    # the file on its first pass.
    wrote_reason = ""

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
            return {"status": "failed", "reason": str(exc)[:400]}, None

        try:
            wrote, reason, extra = place(result)
        except (WriteRefusedError, fences.FenceError) as exc:
            return {"status": "refused", "reason": str(exc)}, result
        wrote_any = wrote_any or wrote
        wrote_reason = reason if wrote else wrote_reason
        fields = {
            **extra,
            "status": "written" if wrote_any else "unchanged",
            "reason": wrote_reason if wrote_any else reason,
        }

        # An unchanged first attempt is the file a previous run already gated.
        if not wrote and attempt == 1:
            return fields, result

        alerts = lint_document(lint_path(), config, level, log=log)
        if alerts is None:
            return {**fields, "prose": "skipped"}, result
        fields["prose_attempts"] = attempt

        # The alerts that carry their own answer are applied here, so the model
        # is only ever sent the ones that need a writer.
        if alerts:
            applied = check.apply_fixes(lint_path(), alerts)
            if applied:
                fields["prose_autofixed"] = fields.get("prose_autofixed", 0) + len(applied)
                alerts = lint_document(lint_path(), config, level, log=log)
                if alerts is None:
                    return {**fields, "prose": "skipped"}, result

        if not alerts:
            return {**fields, "prose": "clean"}, result

        if attempt == attempts:
            # The draft stands and the alerts travel with it. A rule that has
            # survived this many repair passes is usually reading the document
            # wrong, and the reviewer runs the same rules over the file where
            # a person can act on them. Discarding the page here would spend
            # every model call that produced it for nothing.
            named = "; ".join(f"{a.check} line {a.line}" for a in alerts[:5])
            return (
                {
                    **fields,
                    "prose": "dirty",
                    "prose_unresolved": [f"{a.check} line {a.line}: {a.message}" for a in alerts],
                    "prose_reason": f"prose still fails after {attempt} attempt(s): {named}",
                },
                result,
            )

        attempt_prompt, attempt_payload = repair_request(result, lint_path(), alerts, level)
        attempt_values = {}
    return fields, result


# `write-out.json` holds the same pattern as a JSON Schema string and is
# edited by hand, so review.py and this file judge a citation the same way.
URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def sourced(entries, urls, repo):
    """Split a writer's evidence into what this run can stand over, and what not.

    The prompt asks for a source behind every claim, and a prompt is a request.
    A URL the model never received reads exactly like one it did. What the run
    fetched is known here, and a file either exists or does not, so both halves
    of the contract are decided rather than trusted.

    Dropped entries stay beside the record: the coverage gate reads them to
    tell a documented requirement from one that only looks documented.
    """
    kept, unsupported = [], []
    known = set(urls)
    for raw in entries or []:
        entry = (raw or "").strip()
        if not entry:
            continue
        if URL_SCHEME.match(entry):
            (kept if entry in known else unsupported).append(entry)
            continue
        path, _, _line = entry.rpartition(":")
        (kept if path and (Path(repo) / path).exists() else unsupported).append(entry)
    return kept, unsupported


def cited_urls(findings, excerpts):
    """Every page this deliverable was actually shown."""
    urls = {f.get("url") for f in findings or [] if f.get("url")}
    urls |= {s.get("url") for s in excerpts or [] if s.get("url")}
    return urls


def record_evidence(record, result, urls, repo):
    """Put the checked evidence on a write record, and name what fell away."""
    kept, unsupported = sourced(result.get("evidence"), urls, repo)
    record["evidence"] = kept
    record["evidence_unsupported"] = unsupported
    for entry in unsupported:
        log(
            f"{record.get('path') or record.get('deliverable')}: "
            f"dropped evidence {entry}, which is not a source this run read",
            "warning",
        )
    return record


def generate(
    target,
    repo,
    prompt,
    payload,
    schema,
    args,
    sha,
    values,
    identity,
    managed,
    front_extra,
    marker=None,
    urls=(),
):
    """Render a document, lint it, and send the writer back until it passes."""
    captured = {}

    def place(result):
        captured["result"] = result
        if managed == "assisted":
            wrote, reason, skipped = write_assisted(target, result, sha)
            return wrote, reason, {"unmatched_sections": skipped}
        wrote, reason = write_generated(
            target,
            result,
            # `sha` is None in topic mode, where a document is written from
            # published sources and a repository's HEAD does not date it.
            {**front_extra, **({"source_sha": sha} if sha else {}), "generator": GENERATOR},
            args.floor,
            marker=marker,
        )
        return wrote, reason, {}

    fields, result = run_with_repair(
        prompt,
        payload,
        schema,
        args,
        values,
        place,
        lambda: target,
    )
    record = {**identity, **fields}
    if result is not None:
        record.setdefault("path", str(target.relative_to(repo)))
        record["gaps"] = result.get("gaps", [])
        record_evidence(record, result, urls, repo)
    return record


_REPORTED = set()


def report_once(message):
    """One cause, one line. code_context runs per page; its refusals are the run's."""
    if message not in _REPORTED:
        _REPORTED.add(message)
        print(message, file=sys.stderr)


def code_context(out_dir, subject="", limit=400):
    """The public symbols most likely to matter to this page."""
    surface, skipped = api_surface.usable_modules(out_dir)
    modules = surface.get("modules") or {}
    if not modules:
        # The reason was discarded, so a page drafted with no symbol list at
        # all looked exactly like a page whose subject matched none. The prompt
        # still tells the writer that every backticked identifier must appear
        # in `code`, and review.py reports this same value.
        if skipped:
            report_once(f"docs-write: no code grounding. {skipped}")
        return {}

    wanted = {
        word
        for word in re.findall(r"[a-z0-9]+", subject.lower())
        if len(word) > 2 and word not in _SUBJECT_STOP
    }

    scored = []
    for module, entry in modules.items():
        lowered = module.lower()
        # A test names the thing it tests, so it scores well and is exactly
        # what a page must not cite: `TestTieringOffloadingManager` is not API.
        if any(part in lowered for part in _TEST_PATHS):
            continue
        module_hit = sum(1 for word in wanted if word in lowered)
        for key, value in (entry.get("symbols") or {}).items():
            kind, _, name = key.partition(":")
            if not name:
                continue
            hit = module_hit + sum(1 for word in wanted if word in name.lower())
            scored.append((hit, module, name, kind, (value or {}).get("signature", "")))

    total = len(scored)
    if wanted:
        scored = [row for row in scored if row[0]]
    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    # The signature is why the merged surface keeps anything beyond names: a
    # writer naming a function should see what it takes.
    symbols = [
        f"{module}: {signature or name} ({kind})"
        for _, module, name, kind, signature in scored[:limit]
    ]
    return {
        "modules": sorted({row[1] for row in scored[:limit]}),
        "symbols": symbols,
        "total": total,
        "matched": len(scored),
    }


def relevant_changes(commits, subject):
    """The commits worth grounding this deliverable in, or `[]` for none."""
    if not commits:
        return []
    return commit_select.select_commits(commits, subject, CHANGES_LIMIT)


def foundation_payload(item, repo, out_dir):
    """The model input for one foundation deliverable.

    A foundation document is grounded in the slice its gate chose. The symbol
    list a topic deliverable carries is the wrong evidence here: ARCHITECTURE
    wants the dependency graph, and a signature in its payload is a signature
    in its prose.
    """
    stem = item["foundation"]
    payload = {
        "title": item["title"],
        "doc_type": item["type"],
        "path": item["path"],
        "rationale": item["rationale"],
        "foundation": stem,
        "archetype": archetype_for(item["type"], stem),
    }
    payload.update(foundation_evidence.payload(stem, repo, out_dir, item.get("sources") or []))
    return payload


def foundation_frontmatter(stem, sources):
    """What a foundation document carries beyond the writer's usual keys.

    `source_modules` is what `docs_meta.stale()` joins against a relevance
    verdict, so a changed module rewrites the documents citing it and nothing
    else.
    """
    return {"foundation": stem, "source_modules": sorted(sources)}


def write_deliverable(
    repo,
    item,
    out_dir,
    docs_dir,
    args,
    commits=(),
    marker=None,
):
    """Write one planned document from what the repository shows."""
    target = Path(repo) / docs_dir / item["path"]
    identity = {"deliverable": item["path"], "doc_type": item["type"]}
    base_dir = Path(repo) / docs_dir
    if _escapes(target, base_dir):
        return {
            **identity,
            "path": item["path"],
            "status": "refused",
            "reason": f"deliverable path escapes the changeset: {item['path']}",
        }
    managed, _, _ = ownership(target)
    if managed == "manual":
        return {
            **identity,
            "path": str(target.relative_to(repo)),
            "status": "refused",
            "reason": "managed: manual",
        }

    if not getattr(args, "llm_cmd", None):
        return {
            **identity,
            "path": str(target.relative_to(repo)),
            "status": "refused",
            "reason": "no --llm-cmd, so nothing can be drafted",
        }

    if item.get("foundation"):
        # The gate that queued this deliverable already established its
        # evidence; the "no code or commit evidence" refusal below is about a
        # topic page invented from a title, which does not apply here.
        payload = foundation_payload(item, repo, out_dir)
        extra_front = foundation_frontmatter(item["foundation"], item.get("sources") or [])
    else:
        code = code_context(out_dir, f"{item['title']} {item['rationale']}")
        changes = relevant_changes(commits, f"{item['title']} {item['rationale']}")
        if not code and not changes:
            # A page with neither a symbol nor a commit behind it has only its
            # own title to be written from, and drafting from a title is
            # invention.
            return {
                **identity,
                "path": str(target.relative_to(repo)),
                "status": "refused",
                "reason": "no code or commit evidence grounds a new page",
            }
        payload = {
            "title": item["title"],
            "doc_type": item["type"],
            "path": item["path"],
            "rationale": item["rationale"],
            "archetype": archetype_for(item["type"]),
        }
        if code:
            payload["code"] = code
        if changes:
            payload["changes"] = changes
        extra_front = {}

    if managed == "assisted":
        # Without this the model never learns which section ids exist, emits
        # ids that match nothing, and every region is skipped: a permanent
        # no-op reported as "unchanged".
        _, front, text = ownership(target)
        payload["existing"] = existing_summary(text, front)
    log(f"{item['path']} ({item['type']})")
    return generate(
        target,
        repo,
        (PROMPTS / "write-topic.md").read_text(),
        payload,
        json.loads((SCHEMAS / "write-out.json").read_text()),
        args,
        None,
        {**{"doc_type": item["type"]}, **extra_front},
        identity,
        managed,
        extra_front,
        marker=marker,
        urls=set(),
    )


def update_deliverable(
    repo,
    item,
    out_dir,
    docs_dir,
    args,
    commits=(),
    marker=None,
):
    """Rewrite a page that is already in this repository's documentation tree.

    An update target is a path under `docs_dir`, and it produces the same kind
    of document a new page does, so it takes the same prompt and the same
    schema. `ownership()` is the only thing that decides what may happen to
    the file: a `manual` page is never opened, an `assisted` page has only its
    fenced regions rewritten, and a `generated` page has its body regenerated
    with human-set frontmatter preserved.
    """
    identity = {"deliverable": item["path"], "doc_type": item["type"], "kind": "update"}
    docs_root = Path(repo) / docs_dir
    target = docs_root / item["path"]
    # `path` comes from a model, so it is joined and then checked rather than
    # trusted: enough `..` segments resolve anywhere the process can read.
    if _escapes(target, docs_root):
        return {
            **identity,
            "path": item["path"],
            "status": "refused",
            "reason": f"the target escapes {docs_dir}: {item['path']}",
        }
    rel = str(target.relative_to(repo))
    if not target.is_file():
        # An update names a page that exists. A plan built before someone
        # deleted it is the ordinary way here, and writing the page back would
        # undo that deletion without anyone asking for it.
        return {
            **identity,
            "path": rel,
            "status": "refused",
            "reason": f"the target does not exist: {rel}",
        }

    try:
        managed, front, text = ownership(target)
    except (OSError, UnicodeDecodeError) as exc:
        return {**identity, "path": rel, "status": "refused", "reason": str(exc)[:200]}
    if managed == "manual":
        return {**identity, "path": rel, "status": "refused", "reason": "managed: manual"}

    # Past every refusal that costs nothing, so a run with no model still
    # reports what it would have refused rather than falling over first.
    if not getattr(args, "llm_cmd", None):
        return {
            **identity,
            "path": rel,
            "status": "refused",
            "reason": "no --llm-cmd, so nothing can be drafted",
        }

    payload = {
        "title": item["title"],
        "doc_type": item["type"],
        "path": item["path"],
        "rationale": item["rationale"],
        "archetype": archetype_for(item["type"]),
        "existing": existing_summary(text, front),
    }
    code = code_context(out_dir, f"{item['title']} {item['rationale']}")
    if code:
        payload["code"] = code
    changes = relevant_changes(commits, f"{item['title']} {item['rationale']}")
    if changes:
        payload["changes"] = changes

    log(f"{item['path']} (update, {managed})")
    return generate(
        target,
        repo,
        (PROMPTS / "write-topic.md").read_text(),
        payload,
        json.loads((SCHEMAS / "write-out.json").read_text()),
        args,
        front.get("source_sha") or None,
        {"doc_type": item["type"]},
        identity,
        managed,
        {},
        marker=marker,
        urls=set(),
    )


# ------------------------------------------------------------------------ cli


def summarize(results):
    """One bullet per document this run actually produced."""
    lines = []
    for record in results:
        if record.get("status") not in ("written", "unchanged"):
            continue
        path = record.get("path") or record.get("deliverable", "")
        kind = "updated" if record.get("kind") == "update" else "new page"
        lines.append(f"- {path}: {kind}")
        # Written with prose the repair loop could not clear. The page is on
        # disk either way, so the one thing that must not happen is it going
        # out without the alerts being said out loud.
        for alert in record.get("prose_unresolved") or []:
            lines.append(f"  warning {alert}")
    return lines


def write_report(out_dir, docs_dir, results, plan=None):
    """One report shape for both chains, and one exit code."""
    report = {
        "schema": SCHEMA,
        "docs_dir": docs_dir,
        "written": [r for r in results if r.get("status") == "written"],
        "unchanged": [r for r in results if r.get("status") == "unchanged"],
        "refused": [r for r in results if r.get("status") == "refused"],
        "failed": [r for r in results if r.get("status") == "failed"],
        "deferred": [r for r in results if r.get("status") == "deferred"],
        "results": results,
    }
    # Inside the report, so `written` is never read without what it left out.
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "write-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    log(
        "{written} written, {unchanged} unchanged, {refused} refused, {failed} failed".format(
            written=len(report["written"]),
            unchanged=len(report["unchanged"]),
            refused=len(report["refused"]),
            failed=len(report["failed"]),
        )
    )
    for line in summarize(results):
        print(line, file=sys.stderr)
    if report["failed"]:
        return report, 3
    return report, (0 if report["written"] else 1)


def run_plan(
    repo,
    plan,
    docs_dir,
    llm_cmd,
    out,
    changeset_dir=None,
    args=None,
    commits=(),
    marker=None,
):
    """Write every deliverable in `plan`, and report one record per attempt.

    The seam both entry points and the tests go through. `args` carries the
    writer's own knobs and is built here when a caller has none; `llm_cmd` of
    `None` means no model is available, which every deliverable refuses on
    before a prompt is built.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if args is None:
        args = argparse.Namespace()
    args.llm_cmd = llm_cmd
    for name, value in (
        ("timeout", 900),
        ("floor", render.DEFAULT_FLOOR),
        ("vale_config", None),
        ("vale_level", "error"),
        ("vale_attempts", 3),
        ("docs_dir", docs_dir),
        ("out", str(out)),
    ):
        if not hasattr(args, name):
            setattr(args, name, value)

    results = []
    for item in plan.get("deliverables") or []:
        try:
            if item.get("kind") == "update":
                results.append(update_deliverable(repo, item, out, docs_dir, args, commits, marker))
            else:
                if item.get("foundation"):
                    # A fixed destination, not a page staged for review: it
                    # writes at its repo-relative path, `docs/README.md`, and
                    # never enters the changeset directory. `docs_dir` (here
                    # ".") makes `write_deliverable`'s join a no-op and its
                    # `_escapes` backstop guard the repository root instead.
                    where = "."
                else:
                    where = (
                        os.path.relpath(Path(changeset_dir) / "new", repo)
                        if changeset_dir
                        else docs_dir
                    )
                results.append(write_deliverable(repo, item, out, where, args, commits, marker))
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            # One deliverable that raises used to end the step and lose every
            # document already drafted beside it, at the model cost they were
            # drafted for.
            log(f"{item.get('path')} failed: {exc}", "error")
            results.append(
                {
                    "deliverable": item.get("path", ""),
                    "title": item.get("title", ""),
                    "kind": item.get("kind") or "new",
                    "status": "failed",
                    "reason": str(exc)[:300],
                }
            )
    written = sum(1 for r in results if r.get("status") == "written")
    return {"written": written, "results": results}


def write_from_plan(repo, out_dir, args):
    """The plan-driven writer: one document per planned deliverable."""
    plan_path = Path(args.plan)
    if not plan_path.is_file():
        log(f"no plan at {plan_path}", "error")
        return 2
    plan = json.loads(plan_path.read_text())
    if not (plan.get("deliverables") or []):
        log("the plan has no deliverables", "warning")
        return 1

    # No default. It used to be `<repo>/<docs_dir>`, and `prune` below deletes
    # from `<changeset_dir>/new`, so a direct invocation emptied a real
    # `docs/new/` of anything this plan did not account for.
    changeset_dir = getattr(args, "changeset", None)

    # Loaded defensively: an absent file, an absent `commits` key and an empty
    # list all mean the same thing, which is nothing to ground a page in beyond
    # what the code surface already carries.
    commits = []
    changes_path = getattr(args, "changes", None)
    if changes_path and Path(changes_path).is_file():
        try:
            commits = json.loads(Path(changes_path).read_text()).get("commits") or []
        except json.JSONDecodeError:
            commits = []

    # The identity named in each document's `docs-gen` comment markers, and
    # the changeset directory's own name, computed the same way.
    marker = changeset.marker_id("", getattr(args, "topic", None) or "")

    outcome = run_plan(
        repo,
        plan,
        args.docs_dir,
        args.llm_cmd,
        out_dir,
        changeset_dir=changeset_dir,
        args=args,
        commits=commits,
        marker=marker,
    )
    results = outcome["results"]
    if getattr(args, "prune_orphans", False):
        pruned = prune_orphans(repo, args.docs_dir, plan)
        if pruned:
            log(f"pruned {len(pruned)} orphaned document(s)")
        results = results + pruned
    report, code = write_report(out_dir, args.docs_dir, results, plan)
    if not changeset_dir:
        # Writing in place: there is no changeset to prune and no index to put
        # beside documents that are already where they belong.
        return code
    removals = changeset.prune(repo, changeset_dir, results)
    index_path = Path(changeset_dir) / "index.md"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(changeset.index(report, removals))
    return code


def prune_orphans(repo, docs_dir, plan):
    """Delete pages this tool generated that the plan no longer claims.

    `docs-review` reports these and never removes them, because a generated
    page can carry inbound links from hand-written ones. Deleting is a
    separate, asked-for act, which is what this flag is.

    The `generator` stamp is what separates a page this tool wrote from one
    somebody marked `generated` by hand, and a `manual` page is never touched.
    """
    root = Path(repo) / docs_dir
    if not root.is_dir():
        return []
    claimed = {item["path"] for item in (plan.get("deliverables") or []) if item.get("path")}
    removed = []
    for path in sorted(root.rglob("*.md")):
        rel = str(path.relative_to(repo))
        if rel in claimed:
            continue
        try:
            front, _, had = docs_meta.parse(path.read_text())
        except (OSError, UnicodeDecodeError, docs_meta.MetaError):
            continue
        if not had or front.get("managed") != "generated":
            continue
        if not str(front.get("generator", "")).startswith("docs-skills/"):
            continue
        path.unlink()
        removed.append({"path": rel, "status": "pruned", "reason": "no deliverable claims it"})
    return removed


def _deliverable_from_document(repo, rel):
    """A `--documents` path turned into a deliverable, or a refusal record.

    Everything a foundation deliverable needs already lives in the document's
    own frontmatter, stamped there the run that first wrote it: `foundation`
    names which of the five documents this is, `type` and `title` are its
    own, and `source_modules` is what a changed module was joined against to
    queue it here. A path whose frontmatter carries no `foundation` key names
    something this writer no longer owns the shape of, so it is refused with
    that as the reason rather than guessed at.
    """
    identity = {"deliverable": rel, "path": rel}
    target = Path(repo) / rel
    if _escapes(target, Path(repo)):
        reason = f"path escapes the repository: {rel}"
        return None, {**identity, "status": "refused", "reason": reason}
    if not target.is_file():
        return None, {**identity, "status": "refused", "reason": f"no such document: {rel}"}
    try:
        front, _, _ = docs_meta.parse(target.read_text())
    except OSError as exc:
        return None, {**identity, "status": "refused", "reason": str(exc)[:200]}

    stem = front.get("foundation")
    if not stem:
        return None, {**identity, "status": "refused", "reason": "no foundation key in frontmatter"}

    deliverable = {
        "path": rel,
        "type": front.get("type", ""),
        "title": front.get("title", stem),
        "kind": "new",
        "rationale": "a changed module this document cites",
        "sources": front.get("source_modules") or [],
        "foundation": stem,
    }
    return deliverable, None


def write_from_documents(repo, out_dir, args):
    """Rewrite already-published documents named explicitly, by their path.

    This is what an incremental run takes: `sync.py` turns a relevance
    verdict into the document paths a changed module is cited by, through
    `docs_meta.stale()`, and hands them here rather than a plan. A plan names
    what does not exist yet; this names what already does.
    """
    deliverables, refusals = [], []
    for rel in args.documents:
        deliverable, refusal = _deliverable_from_document(repo, rel)
        if refusal is not None:
            refusals.append(refusal)
        else:
            deliverables.append(deliverable)

    commits = []
    changes_path = getattr(args, "changes", None)
    if changes_path and Path(changes_path).is_file():
        try:
            commits = json.loads(Path(changes_path).read_text()).get("commits") or []
        except json.JSONDecodeError:
            commits = []

    outcome = run_plan(
        repo,
        {"deliverables": deliverables},
        args.docs_dir,
        args.llm_cmd,
        out_dir,
        changeset_dir=None,
        args=args,
        commits=commits,
        marker=changeset.marker_id("", getattr(args, "topic", None) or ""),
    )
    report, code = write_report(out_dir, args.docs_dir, refusals + outcome["results"])
    return code


def build_parser():
    """One parser for both modes.

    Plan mode and document mode differ in what decides the document set, not
    in what a writer does with it, so a flag of either has to be reachable
    through the one entry point.
    """
    parser = argparse.ArgumentParser(description="Write Markdown documents from a code repository")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", default=".docs-gen")
    parser.add_argument("--docs-dir", default="docs")

    picks = parser.add_argument_group("what to write")
    picks.add_argument("--plan", default=None, help="plan.json. Defaults to <out>/plan.json")
    picks.add_argument(
        "--documents",
        nargs="*",
        help="Rewrite these existing documents, named by their path under the repo root",
    )
    picks.add_argument(
        "--changeset",
        default=None,
        help=(
            "Where this run's new documents land, and the only directory pruned. "
            "Omit to write in place and prune nothing"
        ),
    )
    picks.add_argument(
        "--prune-orphans",
        action="store_true",
        help="Delete pages this tool generated that the plan no longer claims",
    )
    picks.add_argument("--changes", default=None, help="changes.json, for commit evidence")
    picks.add_argument(
        "--topic", default=None, help="Named in each document's docs-gen marker, slugified"
    )

    model = parser.add_argument_group("the model and the prose gate")
    model.add_argument("--llm-cmd", default=os.environ.get("DOCS_LLM_CMD", "pi -p"))
    model.add_argument("--timeout", type=int, default=900)
    model.add_argument("--floor", type=int, default=render.DEFAULT_FLOOR)
    model.add_argument("--languages-dir", default=str(LANGUAGES))
    model.add_argument(
        "--vale-config",
        default=os.environ.get("DOCS_VALE_CONFIG"),
        help="Composed Vale config. Omit to write without a prose gate",
    )
    model.add_argument(
        "--vale-level",
        default="error",
        choices=sorted(check.SEVERITY_RANK),
        help="Lowest severity that sends the writer back",
    )
    model.add_argument(
        "--vale-attempts",
        type=int,
        default=3,
        help="Total model calls per document, including the first",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out)

    # `--documents` with no values parses as `[]`, which is falsy, so document
    # mode is chosen on the flag being present rather than on what it carries.
    if args.documents is not None:
        return write_from_documents(repo, out_dir, args)

    if not args.plan:
        args.plan = str(out_dir / "plan.json")
    return write_from_plan(repo, out_dir, args)


if __name__ == "__main__":
    sys.exit(main())

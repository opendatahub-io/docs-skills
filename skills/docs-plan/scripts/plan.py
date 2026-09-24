#!/usr/bin/env python3
"""Decide what documents to write, from what the repository shows."""

import argparse
import json
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

from lib.foundation import gates  # noqa: E402
from lib.md import docs_meta  # noqa: E402
from lib.run import step  # noqa: E402
from lib.run.engine import PROMPTS, SCHEMAS  # noqa: E402
from lib.run.report import logger  # noqa: E402

log = logger("docs-plan")

SCHEMA = "docs-skills/plan/1"
TYPES = ("concept", "procedure", "reference")
# Kebab case, no directory, no traversal. The writer joins a `new` path onto
# the changeset directory, so a separator in it decides where the file lands.
NEW_PATH = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")


def validate(deliverables, known_paths):
    """Split a model's deliverables into the usable, the rejected and the adjusted."""
    kept, rejected, adjusted = [], [], []
    seen = set()
    for item in deliverables:
        path = (item.get("path") or "").strip()
        kind = item.get("kind") or "new"
        reason = None
        if kind == "update":
            # An update names a page that is already there, and docs trees have
            # subdirectories: `docs_inventory` hands the planner nested paths,
            # so the flat rule would reject every real update target. Requiring
            # the path verbatim is a tighter gate than a shape ever was, and
            # the writer's `_escapes` stays as the backstop.
            if path not in known_paths:
                reason = "update path names no page in the docs tree"
        elif not NEW_PATH.match(path):
            reason = "path is not a kebab-case .md file name without a directory"
        if reason:
            pass
        elif path in seen:
            reason = "duplicate path"
        elif item.get("type") not in TYPES:
            reason = f"type must be one of {', '.join(TYPES)}"
        elif not (item.get("title") or "").strip():
            reason = "no title"
        elif not (item.get("rationale") or "").strip():
            reason = "no rationale"

        if reason:
            rejected.append({"path": path or "(none)", "reason": reason})
            continue

        # An invented module would reach the writer as evidence for a claim
        # nothing supports, so it goes rather than the whole deliverable.
        sources = [name for name in (item.get("sources") or []) if name in known_paths]
        dropped = [name for name in (item.get("sources") or []) if name not in known_paths]
        if dropped:
            adjusted.append(
                {"path": path, "reason": f"dropped {len(dropped)} source(s) naming no module"}
            )
        seen.add(path)
        kept_item = {
            "path": path,
            "type": item["type"],
            "title": item["title"].strip(),
            "rationale": item["rationale"].strip(),
            "sources": sources,
        }
        if item.get("kind") is not None:
            kept_item["kind"] = item["kind"]
        kept.append(kept_item)
    return kept, rejected, adjusted


def render(topic, deliverables, covered, rejected):
    """`plan.md`, one line per deliverable."""
    lines = [
        "---",
        "title: Plan",
        "type: reference",
        "managed: generated",
        "---",
        "",
        f"# Plan: {topic}",
        "",
        "## Deliverables",
        "",
    ]
    if deliverables:
        for item in deliverables:
            first = item["sources"][0] if item["sources"] else "registry.json"
            sources = f" [src:{first}]"
            lines.append(
                f"- `{item['path']}` ({item['type']}): {item['title']}."
                f" {item['rationale'].rstrip('.')}.{sources}"
            )
    else:
        lines.append("- Nothing to write; the code supported no deliverable [src:registry.json]")

    if covered:
        lines += ["", "## Already covered", ""]
        lines += [f"- {item.rstrip('.')} [src:registry.json]" for item in covered]
    if rejected:
        lines += ["", "## Rejected", ""]
        lines += [f"- `{item['path']}`: {item['reason']} [src:plan]" for item in rejected]
    return "\n".join(lines) + "\n"


def docs_inventory(repo, docs_dir):
    """Every page already in the docs tree, as the planner needs to see it.

    A planner that cannot see what exists proposes a page that is already
    there, and the writer then either duplicates it or refuses it. Reading the
    frontmatter is enough: what a page covers and who owns it decide whether it
    is a target, and its prose decides nothing here.
    """
    found = []
    root = Path(repo) / docs_dir
    if not root.is_dir():
        return found
    for page in sorted(root.rglob("*.md")):
        try:
            front, _, _ = docs_meta.parse(page.read_text())
        except (OSError, UnicodeDecodeError, docs_meta.MetaError):
            # A page this step cannot parse is one the writer will refuse for
            # the same reason. Leaving it out of the inventory is the honest
            # answer: the planner cannot be told what it says.
            continue
        found.append(
            {
                "path": str(page.relative_to(root)),
                "title": front.get("title", ""),
                # The writer's own default for an unmarked file. Two answers to
                # who owns a page is how a plan targets one the writer refuses.
                "managed": front.get("managed", "manual"),
            }
        )
    return found


def module_evidence(out_dir):
    """The modules this repository has, and what each one exposes."""
    # The shape check and its wording belong to the gates, which read the same
    # file. Two copies of it drifted apart the moment one was reworded.
    registry, modules = gates.registry_modules(out_dir, strict=True)

    surface = {}
    surface_path = Path(out_dir) / "api-surface.json"
    if surface_path.is_file():
        try:
            surface = (json.loads(surface_path.read_text()).get("modules")) or {}
        except json.JSONDecodeError:
            surface = {}

    summaries = {}
    summary_dir = Path(out_dir) / "modules"
    if summary_dir.is_dir():
        for record in sorted(summary_dir.glob("*.json")):
            try:
                data = json.loads(record.read_text())
            except json.JSONDecodeError:
                continue
            if data.get("module"):
                summaries[data["module"]] = data

    evidence = []
    for name, entry in sorted(modules.items()):
        symbols = sorted((surface.get(name) or {}).get("symbols") or {})
        summary = summaries.get(name) or {}
        evidence.append(
            {
                "module": name,
                "kind": entry.get("kind", ""),
                "files": entry.get("file_count", 0),
                # Names alone. Each symbol also carries a fingerprint, a file
                # and a line, which nothing in a plan reads and which are many
                # times the size of the name.
                "symbols": symbols[:60],
                "symbol_count": len(symbols),
                "purpose": summary.get("purpose", ""),
                "responsibilities": summary.get("responsibilities") or [],
            }
        )
    return registry, evidence


def _foundation(args, out_dir):
    """Plan the foundation set. Deterministic, so no model call is made."""
    try:
        written, skipped = gates.evaluate(
            args.repo, out_dir, args.docs_dir, skip=tuple(args.skip_doc)
        )
    except ValueError as exc:
        log(f"{exc}", "error")
        return 2

    for entry in skipped:
        log(f"skipped {entry['doc']}: {entry['reason']}", "warning")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "foundation.json").write_text(
        json.dumps(
            {
                "schema": "docs-skills/foundation/1",
                "written": [
                    {"doc": item["path"], "sources": item["sources"], "gate": "pass"}
                    for item in written
                ],
                "skipped": skipped,
            },
            indent=2,
        )
        + "\n"
    )
    (out_dir / "plan.md").write_text(render("the foundation set", written, [], []))
    (out_dir / "plan.json").write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "topic": "",
                "deliverables": written,
                "covered": [],
                "rejected": [],
                "adjusted": [],
            },
            indent=2,
        )
        + "\n"
    )
    log(f"{len(written)} document(s) planned, {len(skipped)} skipped")
    return 0 if written else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Plan documents from what a repository shows")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--out", default=".docs-gen")
    parser.add_argument("--llm-cmd", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--topic", default="", help="Narrow the plan to a subject")
    parser.add_argument(
        "--foundation",
        action="store_true",
        help="Plan the foundation document set from the evidence, with no model call",
    )
    parser.add_argument(
        "--skip-doc",
        action="append",
        default=[],
        metavar="STEM",
        help="A foundation document to leave unwritten. Repeatable",
    )
    parser.add_argument("--context", help="git-context.md, the history the plan reads")
    parser.add_argument("--changes", help="changes.json, the commits matching the subject")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    registry_path = out_dir / "registry.json"
    if not registry_path.is_file():
        log(f"no registry.json at {registry_path}; run docs-repo-analyze first", "error")
        return 2
    # Ahead of `module_evidence`, which the foundation path then discards. It
    # parses every module summary and the whole API surface to build evidence
    # for a model call the foundation set never makes, and `gates.evaluate`
    # re-reads the same artifacts afterwards.
    if args.foundation:
        return _foundation(args, out_dir)

    try:
        registry, modules = module_evidence(out_dir)
    except (json.JSONDecodeError, ValueError) as exc:
        log(f"registry.json is not readable ({exc}); re-run docs-repo-analyze", "error")
        return 2

    if not modules:
        # Asking a model to plan from a topic phrase and nothing else is asking
        # it to invent, and the writer refuses every page it would produce.
        log("no modules in the registry; nothing to plan", "warning")
        return 1

    existing = docs_inventory(args.repo, args.docs_dir)

    prompt = (PROMPTS / "plan.md").read_text()
    schema = json.loads((SCHEMAS / "plan-out.json").read_text())
    topic = args.topic or ""
    payload = {
        "topic": topic,
        "language": registry.get("language", ""),
        "modules": modules,
        "existing": existing,
    }
    if args.context and Path(args.context).is_file():
        payload["history"] = Path(args.context).read_text()[:20000]
    if args.changes and Path(args.changes).is_file():
        changes = (json.loads(Path(args.changes).read_text()).get("commits")) or []
        if changes:
            payload["changes"] = changes

    try:
        result, _ = step.run_step(prompt, payload, schema, args.llm_cmd, args.timeout)
    except (step.StepError, RuntimeError) as exc:
        log(f"{exc}", "error")
        return 2

    known = {entry["module"] for entry in modules} | {entry["path"] for entry in existing}
    deliverables, rejected, adjusted = validate(result.get("deliverables") or [], known)
    for item in rejected:
        log(f"rejected {item['path']}: {item['reason']}", "warning")
    for item in adjusted:
        log(f"adjusted {item['path']}: {item['reason']}")

    covered = result.get("covered") or []
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.md").write_text(render(topic, deliverables, covered, rejected))
    (out_dir / "plan.json").write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "topic": topic,
                "deliverables": deliverables,
                "covered": covered,
                "rejected": rejected,
                "adjusted": adjusted,
            },
            indent=2,
        )
        + "\n"
    )
    log(
        f"{len(deliverables)} deliverable(s), {len(covered)} already covered, "
        f"{len(rejected)} rejected"
    )
    return 0 if deliverables else 1


if __name__ == "__main__":
    sys.exit(main())

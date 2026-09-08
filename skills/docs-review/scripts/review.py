#!/usr/bin/env python3
"""Check generated documentation against the code it claims to describe.

Deterministic first. Grounding, registry membership, staleness, fence
freshness, and frontmatter all resolve from artifacts already on disk, at zero
tokens. Most runs stop here.

A model sees one class of finding: a claim about behaviour that no symbol
name settles. One call per flagged document, and only when `--llm-cmd` is
given.

    python3 review.py --repo . --out .docs-gen --docs-dir docs

Exit codes:
    0  clean, or warnings only
    1  nothing to review
    3  errors found; the caller should block the run
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def _find_root():
    """Locate the shared lib, in the repository or vendored into this skill.

    Skill installers copy a skill directory to a harness-specific location and
    drop symlinks on the way, so a shared `lib/` cannot be linked in. A
    vendored copy under `scripts/` wins when it is there; otherwise the walk
    finds the repository root. Nothing reads a plugin root from the
    environment, because no harness sets one.
    """
    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        if (base / "lib" / "run" / "step.py").exists():
            return base
    raise SystemExit("docs-skills: cannot locate lib/. Run `make vendor` or invoke from a checkout")


ROOT = _find_root()
sys.path.insert(0, str(ROOT))

from lib.md import docs_meta, fences  # noqa: E402
from lib.run import step  # noqa: E402

PROMPTS = ROOT / "prompts"
SCHEMAS = ROOT / "schemas"

SCHEMA = "docs-skills/review/1"

# A backticked token worth checking against the API. Identifier-shaped only:
# prose backticks file names, flags, and literals too, and none of those are
# symbols. Dotted and ::-qualified names are split on the way in.
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:[.:]{1,2}[A-Za-z_][A-Za-z0-9_]*)*$")
INLINE_CODE = re.compile(r"`([^`\n]{1,120})`")
FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)

# Words that look like identifiers and are not. Flagging these buries the real
# findings, which is the failure mode that gets a check switched off.
COMMON_WORDS = {
    "true",
    "false",
    "null",
    "nil",
    "none",
    "yes",
    "no",
    "on",
    "off",
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "string",
    "int",
    "bool",
    "float",
    "list",
    "dict",
    "map",
    "array",
    "error",
    "err",
    "ok",
    "id",
    "name",
    "path",
    "url",
    "uri",
    "json",
    "yaml",
    "toml",
    "http",
    "https",
    "main",
    "init",
    "self",
    "this",
}


class Finding(dict):
    def __init__(self, kind, severity, doc, detail, **extra):
        super().__init__(kind=kind, severity=severity, doc=doc, detail=detail, **extra)


# ------------------------------------------------------------------ grounding


def prose_identifiers(body):
    """Backticked identifier-shaped tokens outside fenced code blocks.

    Code blocks are excluded deliberately. An example legitimately names a
    caller's own variables, and checking those against the module's API
    produces noise on every well-written example.
    """
    prose = FENCED_BLOCK.sub(" ", body)
    found = set()
    for token in INLINE_CODE.findall(prose):
        token = token.strip().rstrip("()")
        if not token or not IDENTIFIER.match(token):
            continue
        if token.lower() in COMMON_WORDS or len(token) < 3:
            continue
        found.add(token)
    return found


def known_symbols(surface):
    """Every public symbol name, qualified and bare.

    Methods are extracted as `Client.send`, and prose refers to them either way:
    "its `send` method" is correct English and correct documentation. Both forms
    count, so the check catches an invented name without flagging a real one.
    """
    names = set()
    for module in (surface.get("modules") or {}).values():
        for key in module.get("symbols") or {}:
            _, _, name = key.partition(":")
            if not name:
                continue
            names.add(name)
            if "." in name:
                names.add(name.rsplit(".", 1)[-1])
    return names


def check_grounding(doc, front, body, surface, module_names):
    """Every identifier a document names in prose must exist in the API."""
    if not surface:
        return []
    names = known_symbols(surface)
    findings = []
    for token in sorted(prose_identifiers(body)):
        tail = re.split(r"[.:]+", token)[-1]
        if token in names or tail in names or token in module_names:
            continue
        findings.append(
            Finding(
                "ungrounded-identifier",
                "error",
                doc,
                f"`{token}` appears in prose and in no extracted public API",
                symbol=token,
            )
        )
    return findings


# -------------------------------------------------------------- other checks


def check_registry(doc, front, registry):
    findings = []
    for module in front.get("source_modules") or []:
        if module not in (registry.get("modules") or {}):
            findings.append(
                Finding(
                    "unknown-module",
                    "error",
                    doc,
                    f"source_modules names {module!r}, which is not in the registry",
                    module=module,
                )
            )
    return findings


def check_frontmatter(doc, front):
    """Frontmatter shape, with a grace period for pages that predate the tool.

    A page with no `managed` field at all has not been onboarded yet, which is
    the normal state of a documentation tree on first contact. That is a
    warning, and it stays one until the repository decides its grace period is
    over. A `managed` field holding something the writer cannot act on is an
    error, because a typo there silently disables the ownership contract.
    """
    findings = []
    managed = front.get("managed")
    if managed is None:
        findings.append(
            Finding(
                "unonboarded",
                "warning",
                doc,
                "no managed field. Until one is set the writer treats this file "
                "as manual and never opens it for writing",
            )
        )
    elif managed not in ("generated", "assisted", "manual"):
        findings.append(
            Finding(
                "bad-frontmatter",
                "error",
                doc,
                f"managed is {managed!r}; expected generated, assisted, or manual",
            )
        )
    if not front.get("description"):
        findings.append(Finding("bad-frontmatter", "warning", doc, "description is empty"))
    if managed in ("generated", "assisted") and not front.get("source_sha"):
        findings.append(Finding("bad-frontmatter", "warning", doc, "no source_sha to date it"))
    return findings


def check_staleness(doc, front, relevance, head):
    """A document whose subject moved.

    Generated and assisted documents are queued for rewrite. A manual document
    is never written, so it becomes a finding for a human instead. That split
    is what lets hand-written pages take part in the pipeline without being
    overwritten by it.
    """
    rebuild = set(relevance.get("rebuild") or [])
    covered = set(front.get("source_modules") or [])
    moved = sorted(covered & rebuild)
    if not moved:
        return []
    managed = front.get("managed", "manual")
    if managed == "manual":
        return [
            Finding(
                "stale-manual",
                "warning",
                doc,
                f"covers {', '.join(moved)}, which changed. This file is never "
                "written automatically, so a human decides",
                modules=moved,
            )
        ]
    if front.get("source_sha") and head.startswith(front["source_sha"]):
        return []
    return [
        Finding(
            "stale-generated",
            "info",
            doc,
            f"covers {', '.join(moved)}, which changed. Queued for rewrite",
            modules=moved,
        )
    ]


def check_fences(doc, text, front, head):
    if front.get("managed") != "assisted":
        return []
    try:
        regions = fences.parse(text)
    except fences.FenceError as exc:
        return [Finding("broken-fence", "error", doc, str(exc))]
    findings = []
    for region in regions:
        if not region.sha:
            findings.append(
                Finding(
                    "stale-fence",
                    "warning",
                    doc,
                    f"region {region.section!r} carries no sha",
                    section=region.section,
                )
            )
        elif head and not head.startswith(region.sha):
            findings.append(
                Finding(
                    "stale-fence",
                    "info",
                    doc,
                    f"region {region.section!r} was generated at {region.sha}",
                    section=region.section,
                )
            )
    return findings


def check_evidence(doc, front, repo, report):
    """Evidence lines the writer cited must point at files that exist."""
    findings = []
    for entry in report.get("evidence") or []:
        path, _, line = entry.rpartition(":")
        if not path or not (Path(repo) / path).exists():
            findings.append(
                Finding(
                    "bad-evidence",
                    "warning",
                    doc,
                    f"evidence cites {entry}, and that file is not in the repo",
                )
            )
    return findings


# ---------------------------------------------------------------- model pass


def ambiguous_claims(body, names):
    """Sentences making a behavioural claim with no symbol to check it against.

    These are what the deterministic layer cannot settle: "the queue retries
    three times before giving up" names nothing checkable. One model call per
    document decides whether the cited evidence supports them.
    """
    claims = []
    for sentence in re.split(r"(?<=[.!?])\s+", FENCED_BLOCK.sub(" ", body)):
        sentence = " ".join(sentence.split())
        if len(sentence) < 40:
            continue
        if prose_identifiers(sentence) & names:
            continue
        if re.search(
            r"\b(always|never|automatically|by default|retries|guarantees|"
            r"ensures|must|cannot|will not|thread[- ]safe|atomic|idempotent)\b",
            sentence,
            re.IGNORECASE,
        ):
            claims.append(sentence)
    return claims[:12]


def review_claims(doc, claims, evidence, repo, llm_cmd, timeout):
    prompt = (PROMPTS / "review-claim.md").read_text()
    schema = json.loads((SCHEMAS / "review-claim-out.json").read_text())
    payload = {
        "document": doc,
        "claims": claims,
        "evidence": [
            {"reference": ref, "excerpt": read_evidence(repo, ref)} for ref in (evidence or [])[:20]
        ],
    }
    result, _ = step.run_step(prompt, payload, schema, llm_cmd, timeout)
    findings = []
    for verdict in result.get("verdicts", []):
        if verdict.get("supported"):
            continue
        findings.append(
            Finding(
                "unsupported-claim",
                "warning",
                doc,
                f"{verdict.get('claim', '')[:200]} — {verdict.get('reason', '')}",
            )
        )
    return findings


def read_evidence(repo, reference, span=6):
    path, _, line = reference.rpartition(":")
    target = Path(repo) / path
    if not target.exists() or not line.isdigit():
        return None
    lines = target.read_text(errors="replace").splitlines()
    index = int(line) - 1
    lo, hi = max(0, index - span), min(len(lines), index + span + 1)
    return "\n".join(f"{n + 1}: {lines[n]}" for n in range(lo, hi))


# ------------------------------------------------------------------------ cli


def load(path, default=None):
    target = Path(path)
    return json.loads(target.read_text()) if target.exists() else default


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review generated documentation")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", default=".docs-gen")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument(
        "--llm-cmd",
        default=os.environ.get("DOCS_LLM_CMD"),
        help="Enables the ambiguous-claim pass. Omit to stay deterministic",
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out)

    registry = load(out_dir / "registry.json", {})
    surface = load(out_dir / "api-surface.json", {})
    relevance = load(out_dir / "relevance.json", {})
    context = load(out_dir / "git-context.json", {})
    write_report = load(out_dir / "write-report.json", {})
    head = (context or {}).get("head", "")
    module_names = set((registry or {}).get("modules") or {})

    evidence_by_doc = {}
    for record in (write_report or {}).get("results", []):
        if record.get("path"):
            evidence_by_doc[record["path"]] = record

    docs = sorted((repo / args.docs_dir).rglob("*.md")) if (repo / args.docs_dir).is_dir() else []
    if not docs:
        print(f"docs-review: no documents under {args.docs_dir}", file=sys.stderr)
        return 1

    findings = []
    for path in docs:
        rel = str(path.relative_to(repo))
        text = path.read_text()
        front, body, _ = docs_meta.parse(text)
        findings += check_frontmatter(rel, front)
        findings += check_registry(rel, front, registry or {})
        findings += check_grounding(rel, front, body, surface, module_names)
        findings += check_staleness(rel, front, relevance or {}, head)
        findings += check_fences(rel, text, front, head)
        findings += check_evidence(rel, front, repo, evidence_by_doc.get(rel, {}))

    escalated = 0
    if args.llm_cmd and surface:
        names = known_symbols(surface)
        for path in docs:
            rel = str(path.relative_to(repo))
            front, body, _ = docs_meta.parse(path.read_text())
            if front.get("managed") == "manual":
                continue
            claims = ambiguous_claims(body, names)
            if not claims:
                continue
            escalated += 1
            print(f"docs-review: checking {len(claims)} claims in {rel}", file=sys.stderr)
            try:
                findings += review_claims(
                    rel,
                    claims,
                    evidence_by_doc.get(rel, {}).get("evidence"),
                    repo,
                    args.llm_cmd,
                    args.timeout,
                )
            except (step.StepError, RuntimeError) as exc:
                findings.append(Finding("review-failed", "warning", rel, str(exc)[:300]))

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    report = {
        "schema": SCHEMA,
        "documents": len(docs),
        "escalated_to_model": escalated,
        "counts": {
            "error": len(errors),
            "warning": len(warnings),
            "info": len(findings) - len(errors) - len(warnings),
        },
        "findings": findings,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "review.json").write_text(json.dumps(report, indent=2) + "\n")

    for finding in findings:
        if finding["severity"] != "info":
            print(
                f"{finding['severity']:<7} {finding['doc']}: {finding['detail']}",
                file=sys.stderr,
            )
    print(
        f"docs-review: {len(docs)} documents, {len(errors)} errors, "
        f"{len(warnings)} warnings, {escalated} sent to a model",
        file=sys.stderr,
    )

    if errors or (args.strict and warnings):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

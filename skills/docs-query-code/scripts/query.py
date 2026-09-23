#!/usr/bin/env python3
"""Answer a question about a repository the generator has already analyzed."""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
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

from lib.run import step  # noqa: E402
from lib.run.engine import PROMPTS, SCHEMAS  # noqa: E402
from lib.run.report import logger  # noqa: E402

log = logger("docs-query-code")

SCHEMA = "docs-skills/query/1"

# Words too common to narrow a search with. A question is mostly these.
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "can",
    "did",
    "do",
    "does",
    "for",
    "from",
    "get",
    "gets",
    "how",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "then",
    "there",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "you",
    "your",
}

SOURCE_SUFFIXES = {".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".pyi"}


def slug(text, limit=60):
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return out[:limit].rstrip("-") or "question"


def keywords(question):
    """Search terms from the question, longest first."""
    quoted = re.findall(r"`([^`]+)`", question)
    identifiers = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:[A-Z][a-z0-9_]*)+\b", question)
    identifiers += re.findall(r"\b[a-z]+_[a-z0-9_]+\b", question)
    words = [
        w for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", question) if w.lower() not in STOPWORDS
    ]
    seen, out = set(), []
    for term in quoted + identifiers + sorted(words, key=len, reverse=True):
        key = term.lower()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out[:12]


def search(repo, terms, budget=40000, per_file=40):
    """Source lines mentioning any search term, with their line numbers."""
    if not terms:
        return []
    pattern = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    hits, used = [], 0
    for path in sorted(Path(repo).rglob("*")):
        if used >= budget:
            break
        if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
            continue
        if any(part.startswith(".") or part in ("node_modules", "vendor") for part in path.parts):
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        matched = []
        for number, line in enumerate(lines, start=1):
            if pattern.search(line):
                matched.append({"line": number, "text": line[:300]})
                if len(matched) >= per_file:
                    break
        if matched:
            rel = str(path.relative_to(repo))
            hits.append({"file": rel, "matches": matched})
            used += sum(len(m["text"]) for m in matched)
    return hits


def load(path, default=None):
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text())
    except json.JSONDecodeError:
        return default


def gather(out_dir):
    """Everything the analysis left behind, or as much of it as exists."""
    registry = load(out_dir / "registry.json")
    if registry is None:
        return None
    modules = []
    module_dir = out_dir / "modules"
    if module_dir.is_dir():
        modules = [json.loads(p.read_text()) for p in sorted(module_dir.glob("*.json"))]
    graph = load(out_dir / "dep-pairs.json", {})
    onboarding = out_dir / "ONBOARDING.md"
    return {
        "language": registry.get("language"),
        "modules": {
            name: {
                "paths": entry.get("paths"),
                "kind": entry.get("kind"),
                "total_lines": entry.get("total_lines"),
            }
            for name, entry in registry.get("modules", {}).items()
        },
        "summaries": modules,
        "dependencies": graph.get("pairs", []),
        "onboarding": onboarding.read_text()[:20000] if onboarding.exists() else None,
    }


def render(question, answer, repo_name):
    front = [
        "---",
        f"question: {json.dumps(question)}",
        f"repo: {json.dumps(repo_name)}",
        f"date: {datetime.now(timezone.utc).date().isoformat()}",
        "managed: generated",
        "type: reference",
        "---",
        "",
    ]
    body = [f"# {answer.get('heading') or question}", "", answer["answer"].strip(), ""]
    if answer.get("evidence"):
        body += ["## Evidence", ""]
        body += [f"- `{item}`" for item in answer["evidence"]]
        body.append("")
    if answer.get("uncertain"):
        body += ["## What this does not settle", "", answer["uncertain"].strip(), ""]
    return "\n".join(front + body)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ask a question about analyzed code")
    parser.add_argument("question")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", default=None, help="Artifact directory. Default <repo>/.docs-gen")
    parser.add_argument("--llm-cmd", default=os.environ.get("DOCS_LLM_CMD", "claude -p"))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--write", help="Write the answer here instead of stdout")
    args = parser.parse_args(argv)

    if not args.question.strip():
        log("give me a question", "error")
        return 2

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out) if args.out else repo / ".docs-gen"

    context = gather(out_dir)
    if context is None:
        log(f"no analysis at {out_dir}. Run docs-repo-analyze first.", "error")
        return 1

    terms = keywords(args.question)
    payload = {
        "question": args.question,
        "repo": repo.name,
        "search_terms": terms,
        "analysis": context,
        "source": search(repo, terms),
    }

    prompt = (PROMPTS / "answer-question.md").read_text()
    schema = json.loads((SCHEMAS / "answer-out.json").read_text())
    log(f"{len(payload['source'])} file(s) matched {len(terms)} term(s)")

    try:
        answer, _ = step.run_step(prompt, payload, schema, args.llm_cmd, args.timeout)
    except (step.StepError, RuntimeError) as exc:
        log(f"{exc}", "error")
        return 3

    document = render(args.question, answer, repo.name)
    if args.write:
        target = Path(args.write)
        if target.is_dir():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            target = target / f"{slug(args.question)}_{stamp}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document)
        log(f"wrote {target}")
    else:
        sys.stdout.write(document)
    return 0


if __name__ == "__main__":
    sys.exit(main())

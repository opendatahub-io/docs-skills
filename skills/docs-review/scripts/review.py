#!/usr/bin/env python3
"""Check generated documentation against the code it claims to describe."""

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

from lib.foundation import commands as foundation_commands  # noqa: E402
from lib.git import api_surface  # noqa: E402
from lib.md import docs_meta, fences, render  # noqa: E402
from lib.run import step  # noqa: E402
from lib.run.engine import PROMPTS, SCHEMAS, TOPICS  # noqa: E402
from lib.run.report import logger  # noqa: E402
from lib.vale import check  # noqa: E402

log = logger("docs-review")

SCHEMA = "docs-skills/review/1"

# Below this many words a page cannot exercise the style guidance, so the
# call is spent for nothing.
STYLE_FLOOR = 40

# A backticked token shaped like a symbol. Dotted and ::-qualified names are
# split on the way in.
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:[.:]{1,2}[A-Za-z_][A-Za-z0-9_]*)*$")

# `README.md` and `build.py` satisfy IDENTIFIER and are file names. Splitting
# them on the dot leaves a tail no symbol table will hold, which used to make
# every backticked file name a finding.
FILE_SUFFIXES = frozenset(
    "md markdown txt rst adoc py pyi go ts tsx js jsx mjs cjs rs java rb sh bash "
    "yaml yml json toml ini cfg conf xml html css sql lock log".split()
)
INLINE_CODE = re.compile(r"`([^`\n]{1,120})`")
FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)

# An evidence entry naming a page rather than a file in this repository. The
# same pattern is a `pattern` string in `schemas/write-out.json`, which cannot
# import anything; that copy is edited by hand.
URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")

# A topic heading in the committed style topics. Trailing blanks are outside
# the group: the prompt and the schema enum must carry the same id, and they
# are cut from this one pattern.
TOPIC_HEADING = re.compile(r"^## +(.+?)[ \t]*$", re.M)

# Words that look like identifiers and never are. Every one of these reads as
# ordinary prose or as a literal, so a finding about one is noise.
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


_CHANGESET_SEGMENT = re.compile(r"^changeset-")


def in_changeset(rel):
    """Whether `rel` sits inside a `changeset-*` directory this tool made."""
    return any(_CHANGESET_SEGMENT.match(part) for part in Path(rel).parts)


_EDIT_SUFFIX = ".edit.md"


def is_update_draft(rel):
    """Whether `rel` is an update's `.edit.md` draft."""
    return Path(rel).name.endswith(_EDIT_SUFFIX)


class Page:
    """One document, read and parsed once."""

    __slots__ = ("path", "rel", "text", "front", "body")

    def __init__(self, path, rel, text, front, body):
        self.path, self.rel, self.text, self.front, self.body = path, rel, text, front, body

    @property
    def is_manual(self):
        managed = self.front.get("managed")
        if managed is not None:
            return managed == "manual"
        return not in_changeset(self.rel)


# Kinds that report and never fail the run. Each rests on matching text rather
# than on reading code, so each misfires on documents that are fine: a Vale
# rule measures a table row as a sentence, a backticked config key misses the
# symbol table. Blocking on that costs more than it catches. `--strict` still
# blocks on everything, for a caller that wants the gate.
ADVISORY_KINDS = frozenset(
    {
        "prose",
        "style",
        "style-failed",
        "style-unavailable",
        "vale-unavailable",
        "ungrounded-identifier",
    }
)

# Some style guidance is useful context but too tentative to elevate even to a
# warning. Keep this mapping next to the review policy rather than teaching the
# model a second severity vocabulary in the prompt.
STYLE_SEVERITIES = {"preview technology": "suggestion"}


class Finding(dict):
    def __init__(self, kind, severity, doc, detail, **extra):
        super().__init__(kind=kind, severity=severity, doc=doc, detail=detail, **extra)


# ---------------------------------------------------------------- what changed


def changed_span(page):
    """The text this run actually authored, or `None` when there is none to isolate."""
    spans = render.marked_spans(page.text)
    return "\n\n".join(spans) if spans else None


# ------------------------------------------------------------------ grounding


def _is_file_name(token):
    """Whether `token` is a file name wearing an identifier's shape."""
    head, _, tail = token.rpartition(".")
    return bool(head) and tail.lower() in FILE_SUFFIXES


def prose_identifiers(body):
    """Backticked identifier-shaped tokens outside fenced code blocks."""
    prose = FENCED_BLOCK.sub(" ", body)
    found = set()
    for token in INLINE_CODE.findall(prose):
        token = token.strip().rstrip("()")
        if not token or not IDENTIFIER.match(token):
            continue
        if token.lower() in COMMON_WORDS or len(token) < 3:
            continue
        if _is_file_name(token):
            continue
        found.add(token)
    return found


def known_symbols(surface):
    """Every public symbol name, qualified and bare."""
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


QUALIFIED = re.compile(r"[.:]")


def check_grounding(doc, front, body, surface, module_names):
    """Report identifiers a document names in prose and the API does not carry.

    A qualified name such as `client.reconnect` is an API path and nothing
    else, so a miss there is worth an error. A bare word is ambiguous: prose
    backticks config keys, CLI names and field names too, and this check has no
    way to tell those from an invented symbol. Those report as warnings.
    """
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
                "error" if QUALIFIED.search(token) else "warning",
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


def check_frontmatter(doc, front, in_changeset=False, is_update_draft=False):
    """Frontmatter shape, with a grace period for pages that predate the tool."""
    if is_update_draft:
        return []
    findings = []
    managed = front.get("managed")
    if managed is None:
        if not in_changeset:
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


SHELL_FENCES = ("bash", "sh", "shell", "console", "terminal")
# What separates one command from the next on a line. A reader runs every one
# of them, so every one is checked.
_SEPARATORS = ("&&", "||", "|", ";")
# A runner whose first argument names the thing being run, so the head is two
# words rather than one. `make build` is declared; `make` alone is not.
_SUBCOMMAND_RUNNERS = ("make", "npm", "uv", "go", "cargo", "just")


def command_heads(text):
    """`(line_number, head)` for every command inside a shell fence.

    A head is the command as a reader would type it, which for a declared
    target is two words. A leading `VAR=value` is environment rather than a
    command, so it is stepped over.
    """
    found = []
    fence = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            info = stripped[3:].strip().lower()
            fence = info if fence is None else None
            continue
        if fence not in SHELL_FENCES or not stripped:
            continue
        body = stripped[1:].strip() if stripped.startswith("$") else stripped
        for part in _split_commands(body):
            head = _command_head(part)
            if head:
                found.append((number, head))
    return found


def _split_commands(line):
    parts = [line]
    for separator in _SEPARATORS:
        split = []
        for part in parts:
            split.extend(part.split(separator))
        parts = split
    return [part.strip() for part in parts if part.strip()]


def _command_head(part):
    """What a fragment runs, with its subcommand where the runner takes one."""
    words = part.split()
    while words and "=" in words[0] and not words[0].startswith("-"):
        words = words[1:]
    if not words:
        return ""
    if len(words) >= 3 and words[0] == "npm" and words[1] == "run":
        return " ".join(words[:3])
    if len(words) >= 2 and words[0] in _SUBCOMMAND_RUNNERS:
        return " ".join(words[:2])
    return words[0]


def check_commands(doc, allowed):
    """Findings for every command head nothing in the repository declares.

    The writer is handed this same allowlist as evidence. This is the half
    that does not rest on the model having honoured it: a tutorial whose
    commands do not exist sends a reader somewhere that is not there.
    """
    text = Path(doc).read_text(encoding="utf-8", errors="replace")
    findings = []
    for number, head in command_heads(text):
        if head in allowed or head.split()[0] in foundation_commands.BUILTINS:
            continue
        findings.append(
            Finding(
                "command",
                "warning",
                str(doc),
                f"`{head}` is declared by no manifest in this repository. "
                "A reader running it gets an error.",
                line=number,
            )
        )
    return findings


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
        if URL_SCHEME.match(entry):
            continue
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


# ---------------------------------------------------------------------- prose


def prose_targets(pages, out_dir):
    """What to hand Vale for each page, and how to name it in a finding."""
    scratch_dir = Path(out_dir) / "vale-run" / "review"
    targets = []
    doc_names = {}
    for page in pages:
        span = changed_span(page)
        if span is not None:
            target = scratch_dir / page.rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(span + "\n")
        else:
            target = page.path
        targets.append(target)
        doc_names[str(target.resolve())] = page.rel
    return targets, doc_names


def check_prose(docs, repo, config, level="error", doc_names=None):
    """Vale's verdict on the whole document set, as findings."""
    if not docs:
        return []
    try:
        alerts = check.run(config, docs)
    except check.ValeError as exc:
        return [Finding("vale-unavailable", "warning", "", f"prose check skipped. {exc}")]

    findings = []
    for alert in alerts:
        if not check.at_or_above(alert.severity, level):
            continue
        resolved = str(Path(alert.file).resolve())
        if doc_names and resolved in doc_names:
            doc = doc_names[resolved]
        else:
            try:
                doc = str(Path(alert.file).resolve().relative_to(Path(repo).resolve()))
            except ValueError:
                doc = alert.file
        findings.append(
            Finding(
                "prose",
                "error" if alert.severity == "error" else "warning",
                doc,
                f"line {alert.line}: {alert.check} — {alert.message}",
                line=alert.line,
                check=alert.check,
            )
        )
    return findings


# ---------------------------------------------------------------- model pass


def ambiguous_claims(body, names):
    """Sentences making a behavioural claim with no symbol to check it against."""
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
            {
                "reference": ref,
                "excerpt": read_evidence(repo, ref),
            }
            for ref in (evidence or [])[:20]
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


# --------------------------------------------------------------- style judgment


def judgeable(pages, floor=STYLE_FLOOR):
    """Documents worth spending a style call on, and the text to send for each."""
    result = []
    for page in pages:
        if page.is_manual:
            continue
        span = changed_span(page)
        text = span if span is not None else page.body
        if len(text.split()) >= floor:
            result.append((page.rel, text))
    return result


def _clip(body, limit):
    """Cut on a line boundary and say so, rather than mid-table or mid-fence."""
    if len(body) <= limit:
        return body
    window = body[:limit]
    head = window.rsplit("\n", 1)[0] if "\n" in window else window.rsplit(" ", 1)[0] or window
    return head + "\n\n[truncated]\n"


def style_topic_ids(text):
    """Every topic id in the committed style topics, in order."""
    return TOPIC_HEADING.findall(text)


def _topics_body(text):
    """The topic sections alone, demoted to sit under the prompt's own heading.

    The file keeps the topics at `##` because it is read on its own too. In the
    prompt they belong under `## The guidance`, beside `## The page` rather than
    level with it.

    The heading text goes through the same pattern style_topic_ids uses, so the
    id the model is shown and the id the schema will accept cannot differ. They
    did: one heading carried a trailing space, which only the enum stripped.
    """
    match = TOPIC_HEADING.search(text)
    body = text[match.start() :].strip() if match else text.strip()
    return TOPIC_HEADING.sub(r"### \1", body)


class StyleUnavailableError(Exception):
    """The committed style files cannot be loaded.

    The cause is a damaged or partial install, which is the same for every page
    in the run, so the caller reports it once rather than once per document.
    """


def style_assets():
    """The prompt, topics and topic-constrained schema for the style pass.

    Loaded once per run: all three inputs are constant across pages, and the
    preflight in main() has to fail on exactly what judge_style needs.
    """
    prompt_path = PROMPTS / "judge-style.md"
    schema_path = SCHEMAS / "judge-style-out.json"
    missing = [p.name for p in (prompt_path, schema_path, TOPICS) if not p.is_file()]
    if missing:
        raise StyleUnavailableError(
            f"the committed style files are missing ({', '.join(missing)}); "
            "restore them or reinstall docs-skills"
        )

    topics = TOPICS.read_text()
    ids = style_topic_ids(topics)
    if not ids:
        raise StyleUnavailableError(
            f"{TOPICS.name} carries no topic headings; restore it or reinstall docs-skills"
        )

    # One source for both halves of the contract: the prompt receives the
    # topics as text, and the schema constrains the model to naming one of
    # them. A list kept in two files drifts, and a finding under a topic the
    # caller has never heard of is one it cannot render.
    try:
        schema = json.loads(schema_path.read_text())
        schema["properties"]["findings"]["items"]["properties"]["topic"]["enum"] = ids
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise StyleUnavailableError(
            f"{schema_path.name} has no findings[].topic to constrain ({exc}); "
            "restore it or reinstall docs-skills"
        ) from exc

    return {
        "prompt": prompt_path.read_text(),
        "schema": schema,
        "topics": _topics_body(topics),
    }


def judge_style(doc, body, llm_cmd, timeout, limit=12000, assets=None):
    """The style pass no linter can run, against the committed guidance."""
    if assets is None:
        try:
            assets = style_assets()
        except StyleUnavailableError as exc:
            return [Finding("style-unavailable", "warning", doc, str(exc))]

    result, _ = step.run_step(
        assets["prompt"],
        {"document": doc, "body": _clip(body, limit), "truncated": len(body) > limit},
        assets["schema"],
        llm_cmd,
        timeout,
        values={"topics": assets["topics"]},
    )
    findings = []
    for item in result.get("findings", []):
        topic = str(item.get("topic", "style"))
        quote = str(item.get("quote", ""))[:120]
        fix = str(item.get("fix", ""))[:160]
        findings.append(
            Finding(
                "style",
                STYLE_SEVERITIES.get(topic, "warning"),
                doc,
                f"{topic}: {quote} — {fix}",
                topic=topic,
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
    """One of this run's artifacts, or `default` when it is not readable.

    A review whose whole contract is findings and an exit code must not end in
    a traceback because an interrupted earlier step left half a JSON document
    behind. The missing artifact is reported and the checks that do not need
    it still run.
    """
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text())
    except (OSError, ValueError) as exc:
        log(f"{target.name} is unreadable: {exc}", "warning")
        return default


def _is_changeset_index(path, repo):
    """Whether `path` is `changeset.index()`'s own output."""
    if path.name != "index.md":
        return False
    try:
        rel = path.relative_to(repo)
    except ValueError:
        rel = path
    return in_changeset(str(rel))


def scoped_docs(repo, docs_dir, write_report):
    """Return documents produced by this run, falling back to every file under docs_dir."""
    results = (write_report or {}).get("results")
    if results is None:
        docs_path = repo / docs_dir
        docs = sorted(docs_path.rglob("*.md")) if docs_path.is_dir() else []
        docs = [d for d in docs if not _is_changeset_index(d, repo)]
        return docs, f"no write-report.json; scanning every file under {docs_dir} instead"

    seen = set()
    for record in results:
        if record.get("status") not in ("written", "unchanged"):
            continue
        path = record.get("path")
        if not path:
            continue
        candidate = repo / path
        if candidate.suffix == ".md" and candidate.is_file():
            seen.add(candidate)
    docs = sorted(d for d in seen if not _is_changeset_index(d, repo))
    return docs, ""


def stale_sweep(repo, docs_dir, relevance, head):
    """Every page under `docs_dir` whose modules moved, written by this run or not."""
    root = Path(repo) / docs_dir
    if not root.is_dir():
        return []
    found = []
    for path in sorted(root.rglob("*.md")):
        if _is_changeset_index(path, repo):
            continue
        try:
            front, _, _ = docs_meta.parse(path.read_text())
        except (OSError, UnicodeDecodeError, docs_meta.MetaError):
            # An unreadable page is reported by the main loop when it is in
            # scope, and is not this sweep's to complain about twice.
            # `MetaError` subclasses `RuntimeError`, so catching `ValueError`
            # here let one badly formatted page end the whole sweep.
            continue
        found += check_staleness(str(path.relative_to(repo)), front, relevance, head)
    return found


def orphans(repo, docs_dir, claimed):
    """Pages this tool wrote that no current deliverable claims.

    The `generator` stamp is what separates a page this tool wrote from one
    somebody marked `generated` by hand. Without it, dropping a writer would
    report every hand-managed page in the tree as rubbish.

    This reports and never deletes. Those files carry inbound links from
    hand-written pages, and breaking them unasked costs more than the stale
    prose it would remove. `docs-write --prune-orphans` is where a person
    asks for the deletion.
    """
    root = Path(repo) / docs_dir
    if not root.is_dir():
        return []
    found = []
    for path in sorted(root.rglob("*.md")):
        if _is_changeset_index(path, repo):
            continue
        rel = str(path.relative_to(repo))
        if rel in claimed:
            continue
        try:
            front, _, had = docs_meta.parse(path.read_text())
        except (OSError, UnicodeDecodeError, docs_meta.MetaError):
            # Reported by the main loop when it is in scope, and not this
            # sweep's to complain about twice.
            continue
        if not had or front.get("managed") != "generated":
            continue
        if not str(front.get("generator", "")).startswith("docs-skills/"):
            continue
        found.append(
            Finding(
                "orphan",
                "warning",
                rel,
                f"{rel} was generated by this tool and no deliverable claims it. "
                "Remove it with `docs-write --prune-orphans`, or mark it `managed: manual`.",
                source_sha=front.get("source_sha", ""),
            )
        )
    return found


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
    parser.add_argument(
        "--no-style",
        action="store_true",
        help="Skip the style judgment pass even when --llm-cmd is given",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on warnings, and on the style findings that otherwise only report",
    )
    parser.add_argument(
        "--vale-config",
        default=os.environ.get("DOCS_VALE_CONFIG"),
        help="Composed Vale config. Omit to skip prose checking entirely",
    )
    parser.add_argument(
        "--vale-level",
        default="error",
        choices=sorted(check.SEVERITY_RANK),
        help="Lowest severity worth reporting",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out)

    registry = load(out_dir / "registry.json", {})
    surface, surface_skipped = api_surface.usable_modules(out_dir)
    context = load(out_dir / "git-context.json", {})
    write_report = load(out_dir / "write-report.json", None)
    # Written by docs-sync and by nothing else. A /docs run has no watermark
    # to be stale against, so the check is skipped rather than fed an empty
    # verdict that would flag every page as current.
    relevance = load(out_dir / "relevance.json", {})
    head = (context or {}).get("head", "")
    module_names = set((registry or {}).get("modules") or {})

    if surface_skipped:
        log(f"grounding skipped. {surface_skipped}", "warning")

    evidence_by_doc = {}
    for record in (write_report or {}).get("results", []):
        if record.get("path"):
            evidence_by_doc[record["path"]] = record

    docs, fallback = scoped_docs(repo, args.docs_dir, write_report)
    if fallback:
        log(f"{fallback}")

    if not docs:
        log(f"no documents under {args.docs_dir}", "warning")
        return 1

    # Read and parse once. Three separate loops used to re-read every file,
    # and they disagreed about what an absent `managed` field means.
    pages = []
    unreadable = []
    for path in docs:
        rel = str(path.relative_to(repo))
        # A document this step cannot open or parse is a finding about that
        # document, which is what this step exists to produce. Raising here
        # abandoned the review of every other document in the changeset over
        # one broken frontmatter block.
        try:
            text = path.read_text()
            front, body, _ = docs_meta.parse(text)
        except (OSError, UnicodeDecodeError, docs_meta.MetaError) as exc:
            unreadable.append(
                Finding("unreadable", "error", rel, f"the document could not be read: {exc}")
            )
            continue
        pages.append(Page(path, rel, text, front, body))

    findings = list(unreadable)
    # Staleness is the one check that has to look outside what this run wrote.
    # A page the run wrote is current by construction; the page that matters is
    # the hand-written one whose subject moved under it, and scoping to the
    # write report is exactly what hides it. Reading frontmatter off every file
    # under docs_dir is cheap and reaches no model, so the sweep is its own.
    if relevance:
        findings += stale_sweep(repo, args.docs_dir, relevance, head)
    # A hand-written page is outside the pipeline's ownership, and every other
    # check here already exempts one. Prose is no different: blocking a sync on
    # a human's wording in a file the writer will never touch leaves nobody
    # able to clear the block.
    lintable = [page for page in pages if not page.is_manual]
    # Read once rather than per page: `declared_commands` opens four manifests
    # and only the getting-started document is checked against them.
    allowed_commands = foundation_commands.allowlist(foundation_commands.declared_commands(repo))
    for page in pages:
        path, rel, text, front, body = page.path, page.rel, page.text, page.front, page.body
        findings += check_frontmatter(
            rel, front, in_changeset=in_changeset(rel), is_update_draft=is_update_draft(rel)
        )
        findings += check_registry(rel, front, registry or {})
        span = changed_span(page)
        findings += check_grounding(
            rel, front, span if span is not None else body, surface, module_names
        )
        findings += check_fences(rel, text, front, head)
        findings += check_evidence(rel, front, repo, evidence_by_doc.get(rel, {}))
        if front.get("foundation") == "get-started":
            findings += check_commands(path, allowed_commands)

    # Pages this tool wrote that the current plan no longer claims. Guarded on
    # the plan existing: with no plan there is nothing to be unclaimed by, and
    # an empty `claimed` set would report every generated page in the tree.
    plan = load(out_dir / "plan.json", None)
    if plan is not None:
        claimed = {item["path"] for item in (plan.get("deliverables") or []) if item.get("path")}
        findings += orphans(repo, args.docs_dir, claimed)

    if args.vale_config:
        targets, doc_names = prose_targets(lintable, out_dir)
        findings += check_prose(
            targets, repo, args.vale_config, args.vale_level, doc_names=doc_names
        )

    escalated = 0
    if args.llm_cmd and surface:
        names = known_symbols(surface)
        for page in pages:
            if page.is_manual:
                continue
            rel, body = page.rel, page.body
            claims = ambiguous_claims(body, names)
            if not claims:
                continue
            escalated += 1
            log(f"checking {len(claims)} claims in {rel}")
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

    judged = 0
    if args.llm_cmd and not args.no_style:
        try:
            assets = style_assets()
        except StyleUnavailableError as exc:
            # Once per run, not once per document: the cause is the same for all.
            findings.append(Finding("style-unavailable", "warning", "", str(exc)))
        else:
            for rel, body in judgeable(pages):
                judged += 1
                try:
                    findings += judge_style(rel, body, args.llm_cmd, args.timeout, assets=assets)
                except (step.StepError, RuntimeError) as exc:
                    findings.append(Finding("style-failed", "warning", rel, str(exc)[:300]))

    errors = [f for f in findings if f["severity"] == "error"]
    warnings = [f for f in findings if f["severity"] == "warning"]
    suggestions = [f for f in findings if f["severity"] == "suggestion"]
    advisory = [f for f in errors if f["kind"] in ADVISORY_KINDS]
    blocking = [f for f in errors if f["kind"] not in ADVISORY_KINDS]
    report = {
        "schema": SCHEMA,
        "documents": len(docs),
        "escalated_to_model": escalated,
        "style_judged": judged,
        "counts": {
            "error": len(errors),
            "blocking": len(blocking),
            "advisory": len(advisory),
            "warning": len(warnings),
            "suggestion": len(suggestions),
            "info": len(findings) - len(errors) - len(warnings) - len(suggestions),
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
    said = f"{len(errors)} errors"
    if advisory:
        # Otherwise a run that passes while reporting errors looks like a run
        # that forgot to check its own exit code.
        said += f" ({len(advisory)} of them advisory, which do not fail the run)"
    log(
        f"{len(docs)} documents, {said}, "
        f"{len(warnings)} warnings, {len(suggestions)} suggestions, "
        f"{escalated} claim check(s), {judged} style pass(es)",
        "error" if blocking else None,
    )

    if args.strict:
        return 3 if errors or warnings else 0
    return 3 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())

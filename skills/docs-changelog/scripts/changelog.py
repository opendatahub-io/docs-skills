#!/usr/bin/env python3
"""Release notes from git-context.json.

A repository that writes conventional commits already carries its own changelog
in structured form. Grouping by type, hoisting breaking changes, and linking
pull request numbers is arithmetic, and the result is more accurate than any
paraphrase of the same commits.

Above a `conventional_ratio` of 0.7 this runs with no model at all. Below it,
the subjects are prose and one model call summarizes the range.

    python3 changelog.py --context .docs-gen/git-context.json --repo . \
        --out CHANGELOG.md

Exit codes:
    0  wrote a section
    1  nothing in range
    3  the model step failed
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
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

from lib.md import docs_meta  # noqa: E402
from lib.run import step  # noqa: E402
from lib.run.engine import GENERATOR  # noqa: E402

DETERMINISTIC_FLOOR = 0.7

# Conventional-commit types, in the order a reader cares about them. Types
# absent from this map are grouped under Other; types mapped to None never
# reach a changelog, because nobody upgrades for a lint fix.
SECTIONS = [
    ("feat", "Features"),
    ("fix", "Bug fixes"),
    ("perf", "Performance"),
    ("revert", "Reverts"),
    ("refactor", "Internal changes"),
    ("docs", "Documentation"),
    ("deps", "Dependencies"),
]
HIDDEN = {"chore", "style", "test", "ci", "build"}

MARKER = re.compile(r"<!-- changelog:begin -->.*?<!-- changelog:end -->", re.DOTALL)
RELEASE_HEADING = re.compile(r"^## (?!#).+$", re.MULTILINE)


# ------------------------------------------------------------- deterministic


def group(commits):
    """Commits by conventional type, breaking changes pulled out first."""
    breaking, buckets, other = [], {}, []
    for commit in commits:
        if commit.get("breaking"):
            breaking.append(commit)
            continue
        kind = (commit.get("type") or "").lower()
        if kind in HIDDEN:
            continue
        if any(kind == key for key, _ in SECTIONS):
            buckets.setdefault(kind, []).append(commit)
        elif commit.get("conventional"):
            other.append(commit)
        else:
            other.append(commit)
    return breaking, buckets, other


def entry(commit, repo_url=None):
    """One bullet: scope, subject, pull request link."""
    subject = commit.get("subject") or ""
    # Strip the conventional prefix; the section heading already says the type.
    subject = re.sub(r"^[a-z]+(\([^)]*\))?!?:\s*", "", subject).strip()
    number = commit.get("pr")
    # GitHub's squash merge appends "(#N)" to the subject. Drop it before
    # appending the link, or every squashed commit gets the number twice.
    if number:
        subject = re.sub(rf"\s*\(#{number}\)\s*$", "", subject).strip()
    scope = commit.get("scope")
    text = f"**{scope}:** {subject}" if scope else subject
    if number:
        link = f"[#{number}]({repo_url}/pull/{number})" if repo_url else f"#{number}"
        text += f" ({link})"
    for key in commit.get("issues") or []:
        text += f" [{key}]"
    return f"- {text}"


def render_sections(context, repo_url=None):
    commits = context.get("commits") or []
    breaking, buckets, other = group(commits)
    lines = []

    if breaking:
        lines.append("### Breaking changes")
        lines.append("")
        lines.extend(entry(c, repo_url) for c in breaking)
        lines.append("")

    for key, heading in SECTIONS:
        if not buckets.get(key):
            continue
        lines.append(f"### {heading}")
        lines.append("")
        lines.extend(entry(c, repo_url) for c in buckets[key])
        lines.append("")

    if other:
        lines.append("### Other")
        lines.append("")
        lines.extend(entry(c, repo_url) for c in other)
        lines.append("")

    return "\n".join(lines).strip()


def heading(context, version=None):
    rng = context.get("range") or {}
    label = version or rng.get("head_tag") or rng.get("tag") or context.get("head", "")[:7]
    return f"## {label} ({date.today().isoformat()})"


# -------------------------------------------------------------- model branch


def summarize(context, llm_cmd, timeout):
    """One call for a repository whose subjects are prose rather than types."""
    prompt = (PROMPTS / "changelog-summary.md").read_text()
    schema = json.loads((SCHEMAS / "changelog-out.json").read_text())
    payload = {
        "range": context.get("range"),
        "summary": context.get("summary"),
        "commits": [
            {
                "subject": c.get("subject"),
                "body": (c.get("body") or "")[:800],
                "pull_request": c.get("pr"),
                "breaking": c.get("breaking"),
            }
            for c in (context.get("commits") or [])[:300]
        ],
    }
    result, _ = step.run_step(prompt, payload, schema, llm_cmd, timeout)
    lines = []
    for section in result.get("sections", []):
        lines.append(f"### {section['heading']}")
        lines.append("")
        lines.extend(f"- {item}" for item in section.get("entries", []))
        lines.append("")
    return "\n".join(lines).strip()


# ------------------------------------------------------------------- merging


def release_key(block):
    """Version label from a generated release heading, without its date."""
    first = block.splitlines()[0] if block.splitlines() else ""
    if not first.startswith("## "):
        return None
    return re.sub(r" \(\d{4}-\d{2}-\d{2}\)$", "", first[3:])


def merge_releases(previous, block):
    """Prepend a new release, replacing that version if it already exists."""
    key = release_key(block)
    if key:
        headings = list(RELEASE_HEADING.finditer(previous))
        for index, match in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(previous)
            if release_key(previous[match.start() : end].strip()) == key:
                return previous[: match.start()] + block + previous[end:]

    previous = previous.strip()
    return f"{block}\n\n{previous}" if previous else block


def merge(existing, block):
    """Prepend a release section, keeping everything already written.

    A changelog is append-only history. The newest section goes directly after
    the marker, so a hand-written preamble above it and every prior release
    below it survive untouched.
    """
    if not existing:
        front = {
            "title": "Changelog",
            "description": "Release history, generated from commit history.",
            "type": "changelog",
            "managed": "generated",
            "generator": GENERATOR,
        }
        body = f"# Changelog\n\n<!-- changelog:begin -->\n{block}\n<!-- changelog:end -->\n"
        return docs_meta.render(front, body)

    if MARKER.search(existing):
        match = MARKER.search(existing)
        marked = match.group()
        previous = marked[len("<!-- changelog:begin -->") : -len("<!-- changelog:end -->")]
        releases = merge_releases(previous.strip(), block)
        replacement = f"<!-- changelog:begin -->\n{releases}\n<!-- changelog:end -->"
        return existing[: match.start()] + replacement + existing[match.end() :]

    front, body, had = docs_meta.parse(existing)
    lines = body.splitlines()
    insert = 0
    for index, line in enumerate(lines):
        if line.startswith("# "):
            insert = index + 1
            break
    before = "\n".join(lines[:insert]).strip()
    after = "\n".join(lines[insert:]).strip()
    marked = f"<!-- changelog:begin -->\n{block}\n<!-- changelog:end -->"
    merged = "\n\n".join(part for part in (before, marked, after) if part)
    return docs_meta.render(front, merged) if had else merged


def repo_url(repo):
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    match = re.match(r"(?:git@|https://)([^:/]+)[:/](.+?)(?:\.git)?$", out)
    return f"https://{match.group(1)}/{match.group(2)}" if match else None


# ----------------------------------------------------------------------- cli


def main(argv=None):
    parser = argparse.ArgumentParser(description="Release notes from git history")
    parser.add_argument("--context", default=".docs-gen/git-context.json")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", default="CHANGELOG.md")
    parser.add_argument("--version", help="Section heading. Defaults to the range tag")
    parser.add_argument("--llm-cmd", default=os.environ.get("DOCS_LLM_CMD"))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--floor", type=float, default=DETERMINISTIC_FLOOR)
    parser.add_argument("--stdout", action="store_true", help="Print, do not write")
    args = parser.parse_args(argv)

    try:
        context = json.loads(Path(args.context).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"changelog: cannot read context: {exc}", file=sys.stderr)
        return 2

    commits = context.get("commits") or []
    if not commits:
        print("changelog: no commits in range", file=sys.stderr)
        return 1

    ratio = (context.get("summary") or {}).get("conventional_ratio", 0)
    if ratio >= args.floor:
        block = render_sections(context, repo_url(args.repo))
        source = f"deterministic (conventional_ratio {ratio:.2f})"
    elif args.llm_cmd:
        try:
            block = summarize(context, args.llm_cmd, args.timeout)
        except (step.StepError, RuntimeError) as exc:
            print(f"changelog: {exc}", file=sys.stderr)
            return 3
        source = f"model (conventional_ratio {ratio:.2f} below {args.floor})"
    else:
        block = render_sections(context, repo_url(args.repo))
        source = f"deterministic fallback (ratio {ratio:.2f}, no --llm-cmd)"

    if not block:
        print("changelog: every commit in range was filtered out", file=sys.stderr)
        return 1

    block = f"{heading(context, args.version)}\n\n{block}"
    if args.stdout:
        print(block)
        print(f"changelog: {source}", file=sys.stderr)
        return 0

    target = Path(args.repo) / args.out
    existing = target.read_text() if target.exists() else None
    target.write_text(merge(existing, block))
    print(f"changelog: wrote {target}, {source}, {len(commits)} commits", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Render git-context.json as a short brief a model can read."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FRONT = "---\ntitle: Git context\ntype: reference\nmanaged: generated\n---\n"

# Enough of each ranking to show a shape, short enough to stay well inside the
# 2000-word budget. Twenty hotspots and fifteen modules rendered to 201 words
# against a 200-commit repository.
HOTSPOT_LIMIT = 20
CHANGE_LIMIT = 12
# Commit types worth naming to someone writing documentation. A chore or a
# style change moved no behaviour, so it tells a writer nothing.
INTERESTING = ("feat", "fix", "perf", "refactor")
MODULE_LIMIT = 15
BREAKING_LIMIT = 10


def _pairs(mapping, limit):
    return ", ".join(f"{key} {value}" for key, value in list((mapping or {}).items())[:limit])


def _body_lines(context, hotspots=HOTSPOT_LIMIT, modules=MODULE_LIMIT, breaking=BREAKING_LIMIT):
    """The digest's sections, in order, without the frontmatter."""
    summary = context.get("summary") or {}
    rev_range = context.get("range") or {}
    head = (context.get("head") or "")[:7] or "unknown"
    lines = ["## Summary", ""]

    lines.append(
        f"- Head {head} on branch {context.get('branch') or 'unknown'} [src:git rev-parse HEAD]"
    )
    lines.append(
        f"- Range {rev_range.get('range') or 'none'} chosen by "
        f"{rev_range.get('basis') or 'none'} [src:git log]"
    )
    lines.append(
        f"- {summary.get('commit_count', 0)} commits, "
        f"{summary.get('conventional_ratio', 0)} of them conventional [src:git log]"
    )
    types = _pairs(summary.get("types"), 6)
    if types:
        lines.append(f"- Types: {types} [src:git log]")
    authors = _pairs(summary.get("authors"), 5)
    if authors:
        lines.append(f"- Authors: {authors} [src:git log]")
    prs = summary.get("pull_requests") or []
    if prs:
        lines.append(f"- {len(prs)} pull requests, newest #{max(prs)} [src:git log]")
    issues = summary.get("issues") or []
    if issues:
        lines.append(f"- Issues: {', '.join(str(i) for i in issues[:10])} [src:git log]")
    for change in (summary.get("breaking_changes") or [])[:breaking]:
        lines.append(
            f"- Breaking: {change.get('subject', '')} [src:{change.get('sha', 'git log')}]"
        )

    lines += ["", "## Modules", ""]
    registry = context.get("modules") or {}
    if not registry:
        lines.append("- There is no module registry for this range [src:registry.json]")
    for name, entry in sorted(
        registry.items(), key=lambda kv: -(kv[1].get("adds", 0) + kv[1].get("dels", 0))
    )[:modules]:
        files = entry.get("files") or []
        lines.append(
            f"- {name}: {len(files)} files, +{entry.get('adds', 0)}/-{entry.get('dels', 0)}, "
            f"{len(entry.get('commits') or [])} commits [src:{files[0] if files else name}]"
        )

    # What changed, not just how much. A breaking change and a new feature are
    # the two things a writer most needs to know about a repository, and the
    # counts in Summary do not say which commits they were.
    lines += ["", "## Changes", ""]
    changes = []
    for commit in context.get("commits") or []:
        if commit.get("breaking"):
            changes.append(("breaking", commit))
    for commit in context.get("commits") or []:
        if not commit.get("breaking") and (commit.get("type") or "").lower() in INTERESTING:
            changes.append((commit["type"], commit))
    if not changes:
        # Two different facts, and confusing them tells a writer the wrong
        # thing: a repository that does not write conventional commits has
        # changes nobody can classify, not an absence of changes.
        ratio = (context.get("summary") or {}).get("conventional_ratio", 0)
        lines.append(
            "- No behavioural change in this range [src:git log]"
            if ratio
            else "- Commit subjects are not conventional, so changes cannot be "
            "classified [src:git log]"
        )
    for kind, commit in changes[: breaking + CHANGE_LIMIT]:
        subject = (commit.get("subject") or "").rstrip(".")
        # A conventional subject already opens with its type, so prefixing it
        # again reads as "feat: feat: ...".
        head, sep, rest = subject.partition(": ")
        if sep and head.split("(")[0].lower() == kind.lower():
            subject = rest
        lines.append(f"- {kind}: {subject} [src:{commit.get('short', 'git log')}]")

    lines += ["", "## Hotspots", ""]
    ranked = (context.get("hotspots") or [])[:hotspots]
    if not ranked:
        lines.append("- No file changed in this range [src:git log --numstat]")
    for spot in ranked:
        lines.append(
            f"- {spot.get('commits', 0)} commits, churn {spot.get('churn', 0)} "
            f"[src:{spot.get('path', 'unknown')}]"
        )

    return lines


def render(context, hotspots=HOTSPOT_LIMIT, modules=MODULE_LIMIT, breaking=BREAKING_LIMIT):
    """One Markdown brief, sourced line by line."""
    return "\n".join([FRONT, *_body_lines(context, hotspots, modules, breaking)]) + "\n"


def render_many(
    named_contexts, hotspots=HOTSPOT_LIMIT, modules=MODULE_LIMIT, breaking=BREAKING_LIMIT
):
    """One digest across several repositories, labelled and sharing one budget."""
    count = max(len(named_contexts), 1)
    per_hotspots = max(1, hotspots // count)
    per_modules = max(1, modules // count)
    per_breaking = max(1, breaking // count)
    lines = [FRONT]
    for name, context in named_contexts:
        lines.append(f"# {name}")
        lines.append("")
        lines.extend(_body_lines(context, per_hotspots, per_modules, per_breaking))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Render git-context.json as Markdown")
    parser.add_argument(
        "--context",
        action="append",
        required=True,
        help="Path to a git-context.json. Repeatable, one per repository",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="Repository name for the --context given at the same position. "
        "Required once per --context when more than one is given",
    )
    parser.add_argument("--out", required=True, help="Path to write the brief to")
    parser.add_argument("--hotspots", type=int, default=HOTSPOT_LIMIT)
    parser.add_argument("--modules", type=int, default=MODULE_LIMIT)
    args = parser.parse_args(argv)

    if args.label and len(args.label) != len(args.context):
        print("docs-digest: pass one --label per --context, or none at all", file=sys.stderr)
        return 2
    if not args.label and len(args.context) > 1:
        print("docs-digest: more than one --context needs a --label for each", file=sys.stderr)
        return 2

    missing = [c for c in args.context if not Path(c).exists()]
    if missing:
        print(f"docs-digest: no context at {missing[0]}", file=sys.stderr)
        return 1

    contexts = [json.loads(Path(c).read_text()) for c in args.context]
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    if args.label:
        text = render_many(list(zip(args.label, contexts)), args.hotspots, args.modules)
    else:
        text = render(contexts[0], args.hotspots, args.modules)
    target.write_text(text)
    print(f"docs-digest: {target}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

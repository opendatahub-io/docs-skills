#!/usr/bin/env python3
"""Deterministic git history extraction for documentation generation.

Single-pass `git log` parsing. No network, no model, no third-party deps.
Every subcommand writes JSON to stdout.

Usage:
    python3 git_context.py range   --repo . [--since-tag | --since-sha SHA | --since-watermark FILE]
    python3 git_context.py commits --repo . --range v1.2.0..HEAD
    python3 git_context.py changes --repo . --range v1.2.0..HEAD [--registry registry.json]
    python3 git_context.py churn   --repo . --range v1.2.0..HEAD
    python3 git_context.py context --repo . [--range R] [--registry F] [--out git-context.json]
    python3 git_context.py clone   <url> --out DIR [--ref REF] [--pr-url URL]
    python3 git_context.py watermark read  --file .docs-state.json
    python3 git_context.py watermark write --file .docs-state.json --repo . \
        --module M --sha SHA --doc PATH
"""

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RS = "\x1e"  # record separator
FS = "\x1f"  # field separator

LOG_FORMAT = f"%x1e%H{FS}%h{FS}%P{FS}%an{FS}%ae{FS}%aI{FS}%s{FS}%b{FS}%(trailers:only,unfold){FS}"

CONVENTIONAL = re.compile(
    r"^(?P<type>build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?:\s*(?P<desc>.+)$",
    re.IGNORECASE,
)

# GitHub merge, GitHub squash, GitLab merge
PR_PATTERNS = [
    re.compile(r"Merge pull request #(\d+)\b"),
    re.compile(r"\(#(\d+)\)\s*$"),
    re.compile(r"See merge request [^!]*!(\d+)"),
]

ISSUE_TRAILERS = ("refs", "fixes", "closes", "resolves", "relates-to", "jira")
BREAKING = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)


# ---------------------------------------------------------------- git plumbing


class GitError(RuntimeError):
    pass


def git(repo, *args, check=True):
    """Run a git command in repo and return stdout as text."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def is_repo(repo):
    return (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--git-dir"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def is_shallow(repo):
    return git(repo, "rev-parse", "--is-shallow-repository").strip() == "true"


def ensure_history(repo):
    """Deepen a shallow checkout. CI checkouts are shallow by default."""
    if not is_shallow(repo):
        return {"deepened": False}
    git(repo, "fetch", "--unshallow", "--tags", check=False)
    return {"deepened": True, "still_shallow": is_shallow(repo)}


def sha_exists(repo, sha):
    return (
        subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


# ------------------------------------------------------------------ range


def last_tag(repo):
    out = git(repo, "describe", "--tags", "--abbrev=0", check=False).strip()
    return out or None


def previous_tag(repo, tag):
    out = git(repo, "describe", "--tags", "--abbrev=0", f"{tag}^", check=False).strip()
    return out or None


def default_range(repo, fallback_count=200):
    """Best available range when the caller gives no hint.

    Prefers the span since the most recent tag. Untagged repos fall back to a
    commit count so the tool still returns something useful.
    """
    tag = last_tag(repo)
    if tag:
        ahead = git(repo, "rev-list", "--count", f"{tag}..HEAD", check=False).strip()
        if ahead and ahead != "0":
            return {"range": f"{tag}..HEAD", "basis": "since_last_tag", "base": tag}
        prev = previous_tag(repo, tag)
        if prev:
            return {"range": f"{prev}..{tag}", "basis": "last_tag_span", "base": prev}
    return {
        "range": f"-n{fallback_count}",
        "basis": "commit_count_fallback",
        "base": None,
    }


def resolve_range(repo, args):
    if args.range:
        return {"range": args.range, "basis": "explicit", "base": args.range.split("..")[0]}
    if args.since_sha:
        if not sha_exists(repo, args.since_sha):
            return {
                "range": None,
                "basis": "orphaned_sha",
                "base": args.since_sha,
                "warning": "SHA not reachable (rebase or force-push). Full rebuild advised.",
            }
        return {"range": f"{args.since_sha}..HEAD", "basis": "since_sha", "base": args.since_sha}
    if args.since_watermark:
        state = read_watermark(args.since_watermark)
        shas = {m["sha"] for m in state.get("modules", {}).values() if m.get("sha")}
        reachable = [s for s in shas if sha_exists(repo, s)]
        if not reachable:
            return {
                "range": None,
                "basis": "no_valid_watermark",
                "base": None,
                "warning": "No watermark SHA is reachable. Full rebuild advised.",
            }
        base = oldest_of(repo, reachable)
        return {"range": f"{base}..HEAD", "basis": "since_watermark", "base": base}
    if args.since_tag:
        return default_range(repo)
    return default_range(repo)


def oldest_of(repo, shas):
    """Return whichever SHA is the earliest ancestor, so nothing is missed."""
    oldest = shas[0]
    for sha in shas[1:]:
        merge_base = git(repo, "merge-base", oldest, sha, check=False).strip()
        oldest = merge_base or oldest
    return oldest


# ------------------------------------------------------------- commit corpus


def parse_numstat(block):
    """Parse the NUL-delimited numstat tail of one log record.

    Ordinary entries are `adds\tdels\tpath`. Renames under -z emit
    `adds\tdels\t` followed by two further NUL-separated tokens.
    """
    files = []
    tokens = [t for t in block.split("\0") if t != ""]
    i = 0
    while i < len(tokens):
        tok = tokens[i].lstrip("\n")
        parts = tok.split("\t")
        if len(parts) < 3:
            i += 1
            continue
        adds, dels, path = parts[0], parts[1], parts[2]
        entry = {
            "path": path,
            "adds": None if adds == "-" else int(adds),
            "dels": None if dels == "-" else int(dels),
            "binary": adds == "-",
        }
        if path == "" and i + 2 < len(tokens):
            entry["path"] = tokens[i + 2]
            entry["renamed_from"] = tokens[i + 1]
            i += 2
        files.append(entry)
        i += 1
    return files


TRAILER_LINE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9 ._-]{0,40}):[ \t]*(?P<value>.+)$")


def parse_trailers(raw, body=""):
    """Parse trailers, falling back to the final body paragraph.

    Git's own `%(trailers)` refuses any block containing a key with a space,
    so a commit carrying `BREAKING CHANGE:` loses its `Fixes:` and
    `Co-authored-by:` lines too. Conventional-commits repos hit this
    constantly, so parse the body directly when git returns nothing.

    The scan walks paragraphs from the end and merges every one that parses
    wholly as trailers, stopping at the first that does not. A commit-msg hook
    that appends its own footer (rh-pre-commit, Gerrit Change-Id, DCO tooling)
    otherwise buries the real trailers behind a block the last-paragraph-only
    reading never gets past.
    """
    out = {}
    for line in raw.splitlines():
        match = TRAILER_LINE.match(line.strip())
        if match:
            out.setdefault(match.group("key").strip().lower(), []).append(
                match.group("value").strip()
            )
    if out or not body:
        return out

    paragraphs = [p for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    blocks = []
    for para in reversed(paragraphs):
        lines = [line for line in para.splitlines() if line.strip()]
        matches = [TRAILER_LINE.match(line.strip()) for line in lines]
        if not lines or not all(matches):
            break
        blocks.append(matches)
    for matches in reversed(blocks):
        for match in matches:
            out.setdefault(match.group("key").strip().lower(), []).append(
                match.group("value").strip()
            )
    return out


def classify_subject(subject, body):
    m = CONVENTIONAL.match(subject.strip())
    result = {
        "conventional": bool(m),
        "type": m.group("type").lower() if m else None,
        "scope": m.group("scope") if m else None,
        "breaking": bool(m and m.group("bang")) or bool(BREAKING.search(body or "")),
    }
    return result


def extract_pr(subject, body):
    for pattern in PR_PATTERNS:
        for text in (subject, body or ""):
            match = pattern.search(text)
            if match:
                return int(match.group(1))
    return None


def extract_issues(trailers, subject, body, prefixes=None):
    """Issue keys from trailers always; from free text only for declared prefixes.

    Unscoped scanning for `[A-Z]+-\\d+` matches CWE-22, SHA-256, and UTF-8, so
    body scanning stays opt-in via --issue-prefix.
    """
    issues = []
    for key in ISSUE_TRAILERS:
        issues.extend(trailers.get(key, []))
    if prefixes:
        pattern = re.compile(r"\b(" + "|".join(re.escape(p) for p in prefixes) + r")-\d+\b")
        for text in (subject, body or ""):
            issues.extend(match.group(0) for match in pattern.finditer(text))
    seen, unique = set(), []
    for item in issues:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def read_commits(repo, rev_range, paths=None, max_count=None, issue_prefixes=None):
    args = ["log", "--numstat", "-M", "-z", f"--pretty=format:{LOG_FORMAT}"]
    if max_count:
        args.append(f"-n{max_count}")
    if rev_range and rev_range.startswith("-n"):
        args.append(rev_range)
    elif rev_range:
        args.append(rev_range)
    if paths:
        args.append("--")
        args.extend(paths)

    raw = git(repo, *args)
    commits = []
    for chunk in raw.split(RS):
        if not chunk.strip():
            continue
        fields = chunk.split(FS)
        if len(fields) < 9:
            continue
        sha, short, parents, an, ae, date, subject, body, trailers_raw = fields[:9]
        tail = fields[9] if len(fields) > 9 else ""
        trailers = parse_trailers(trailers_raw, body)
        parent_list = parents.split() if parents else []
        commits.append(
            {
                "sha": sha,
                "short": short,
                "parents": parent_list,
                "is_merge": len(parent_list) > 1,
                "author": {"name": an, "email": ae},
                "date": date,
                "subject": subject,
                "body": body.strip(),
                "trailers": trailers,
                "pr": extract_pr(subject, body),
                "issues": extract_issues(trailers, subject, body, issue_prefixes),
                **classify_subject(subject, body),
                "files": parse_numstat(tail),
            }
        )
    return commits


# ------------------------------------------------------ registry / attribution


def load_registry(path):
    """Accept a docs-learn-code registry.json or a simple {module: [prefixes]} map."""
    if not path:
        return None
    data = json.loads(Path(path).read_text())
    mapping = {}
    if isinstance(data, list):
        for entry in data:
            name = entry.get("name") or entry.get("module")
            prefixes = entry.get("paths") or entry.get("path") or name
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            if name and prefixes:
                mapping[name] = [p.rstrip("/") for p in prefixes]
    elif isinstance(data, dict):
        for name, prefixes in data.items():
            if isinstance(prefixes, str):
                prefixes = [prefixes]
            mapping[name] = [p.rstrip("/") for p in prefixes]
    return mapping


def attribute(path, mapping):
    if not mapping:
        return None
    best, best_len = None, -1
    for name, prefixes in mapping.items():
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                if len(prefix) > best_len:
                    best, best_len = name, len(prefix)
    return best


def load_excludes(path):
    """Read newline or YAML-ish list of regex patterns. Comments start with #."""
    if not path or not Path(path).exists():
        return []
    patterns = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.lstrip("- ").strip().strip("'\"")
        if line.endswith(":"):
            continue
        try:
            patterns.append(re.compile(line))
        except re.error:
            continue
    return patterns


def excluded(path, patterns):
    return any(p.search(path) for p in patterns)


# ------------------------------------------------------------------ aggregates


def build_changes(commits, mapping, excludes):
    files = defaultdict(
        lambda: {"adds": 0, "dels": 0, "commits": 0, "renamed_from": None, "module": None}
    )
    for commit in commits:
        if commit["is_merge"]:
            continue  # merge diffs double-count against both parents
        for entry in commit["files"]:
            path = entry["path"]
            if excluded(path, excludes):
                continue
            record = files[path]
            record["adds"] += entry["adds"] or 0
            record["dels"] += entry["dels"] or 0
            record["commits"] += 1
            if entry.get("renamed_from"):
                record["renamed_from"] = entry["renamed_from"]
    modules = defaultdict(lambda: {"files": [], "adds": 0, "dels": 0, "commits": set()})
    for path, record in files.items():
        record["module"] = attribute(path, mapping)
        if record["module"]:
            bucket = modules[record["module"]]
            bucket["files"].append(path)
            bucket["adds"] += record["adds"]
            bucket["dels"] += record["dels"]
    for commit in commits:
        if commit["is_merge"]:
            continue
        for entry in commit["files"]:
            module = attribute(entry["path"], mapping)
            if module:
                modules[module]["commits"].add(commit["sha"])
    return (
        dict(sorted(files.items())),
        {k: {**v, "commits": sorted(v["commits"])} for k, v in modules.items()},
    )


def build_churn(files, limit=30):
    ranked = sorted(
        (
            {
                "path": p,
                "churn": r["adds"] + r["dels"],
                "commits": r["commits"],
                "module": r["module"],
            }
            for p, r in files.items()
        ),
        key=lambda r: (r["commits"], r["churn"]),
        reverse=True,
    )
    return ranked[:limit]


def summarize(commits):
    types = defaultdict(int)
    authors = defaultdict(int)
    prs, issues, breaking = set(), set(), []
    for commit in commits:
        if commit["type"]:
            types[commit["type"]] += 1
        authors[commit["author"]["name"]] += 1
        if commit["pr"]:
            prs.add(commit["pr"])
        issues.update(commit["issues"])
        if commit["breaking"]:
            breaking.append({"sha": commit["short"], "subject": commit["subject"]})
    conventional = sum(1 for c in commits if c["conventional"])
    return {
        "commit_count": len(commits),
        "conventional_ratio": round(conventional / len(commits), 3) if commits else 0.0,
        "types": dict(sorted(types.items(), key=lambda kv: -kv[1])),
        "authors": dict(sorted(authors.items(), key=lambda kv: -kv[1])),
        "pull_requests": sorted(prs),
        "issues": sorted(issues),
        "breaking_changes": breaking,
    }


# ------------------------------------------------------------------ watermark


def read_watermark(path):
    file = Path(path)
    if not file.exists():
        return {"registry_hash": None, "modules": {}}
    return json.loads(file.read_text())


def write_watermark(path, module, sha, doc, registry_hash=None):
    state = read_watermark(path)
    state["modules"][module] = {"sha": sha, "doc": doc}
    if registry_hash:
        state["registry_hash"] = registry_hash
    Path(path).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state


# ---------------------------------------------------------------------- clone


def normalize_url(url):
    return url[:-4] if url.endswith(".git") else url


def pr_number_from_url(url):
    if not url:
        return None
    match = re.search(r"/(?:pull|merge_requests)/(\d+)", url)
    return int(match.group(1)) if match else None


def clone(url, out, ref=None, pr_url=None, blobless=True):
    """Treeless clone keeps full commit history at a fraction of the size."""
    if Path(out).exists() and is_repo(out):
        info = ensure_history(out)
        return {"status": "existing", "path": str(out), **info}
    args = ["clone"]
    if blobless:
        args.append("--filter=blob:none")
    if ref:
        args.extend(["--branch", ref])
    args.extend([url, str(out)])
    proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        return {
            "status": "cloned",
            "path": str(out),
            "ref": ref,
            "method": "branch" if ref else "default",
        }

    # Ref may live in a fork, or the branch was deleted post-merge.
    args = ["clone"]
    if blobless:
        args.append("--filter=blob:none")
    args.extend([url, str(out)])
    proc = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return {"status": "error", "message": proc.stderr.strip()}

    if ref and git(out, "fetch", "origin", ref, check=False) is not None:
        if (
            subprocess.run(
                ["git", "-C", str(out), "checkout", "FETCH_HEAD"], capture_output=True, check=False
            ).returncode
            == 0
        ):
            return {"status": "cloned", "path": str(out), "ref": ref, "method": "fetch"}

    number = pr_number_from_url(pr_url)
    if number:
        pr_ref = (
            f"refs/merge-requests/{number}/head" if "gitlab" in url else f"refs/pull/{number}/head"
        )
        git(out, "fetch", "origin", pr_ref, check=False)
        if (
            subprocess.run(
                ["git", "-C", str(out), "checkout", "FETCH_HEAD"], capture_output=True, check=False
            ).returncode
            == 0
        ):
            return {"status": "cloned", "path": str(out), "ref": pr_ref, "method": "pr_ref"}

    return {"status": "cloned", "path": str(out), "ref": None, "method": "default_fallback"}


# ------------------------------------------------------------------ commands


def emit(payload, out=None):
    text = json.dumps(payload, indent=2)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text + "\n")
        print(json.dumps({"written": out, "bytes": len(text)}, indent=2))
    else:
        print(text)


def cmd_range(args):
    emit(resolve_range(args.repo, args))
    return 0


def cmd_commits(args):
    resolved = resolve_range(args.repo, args)
    if not resolved["range"]:
        emit(resolved)
        return 1
    commits = read_commits(
        args.repo, resolved["range"], args.path, args.max_count, args.issue_prefix
    )
    emit({"range": resolved, "summary": summarize(commits), "commits": commits}, args.out)
    return 0


def cmd_changes(args):
    resolved = resolve_range(args.repo, args)
    if not resolved["range"]:
        emit(resolved)
        return 1
    commits = read_commits(
        args.repo, resolved["range"], args.path, args.max_count, args.issue_prefix
    )
    mapping = load_registry(args.registry)
    files, modules = build_changes(commits, mapping, load_excludes(args.excludes))
    emit({"range": resolved, "files": files, "modules": modules}, args.out)
    return 0


def cmd_churn(args):
    resolved = resolve_range(args.repo, args)
    commits = read_commits(
        args.repo, resolved["range"], args.path, args.max_count, args.issue_prefix
    )
    files, _ = build_changes(commits, load_registry(args.registry), load_excludes(args.excludes))
    emit({"range": resolved, "hotspots": build_churn(files, args.limit)}, args.out)
    return 0


def cmd_context(args):
    """Everything downstream steps need, in one artifact."""
    ensure_history(args.repo)
    resolved = resolve_range(args.repo, args)
    if not resolved["range"]:
        emit({"repo": str(args.repo), "range": resolved, "commits": [], "files": {}}, args.out)
        return 1
    commits = read_commits(
        args.repo, resolved["range"], args.path, args.max_count, args.issue_prefix
    )
    mapping = load_registry(args.registry)
    files, modules = build_changes(commits, mapping, load_excludes(args.excludes))
    payload = {
        "schema": "git-context/1",
        "repo": str(Path(args.repo).resolve()),
        "head": git(args.repo, "rev-parse", "HEAD").strip(),
        "branch": git(args.repo, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "range": resolved,
        "summary": summarize(commits),
        "modules": modules,
        "hotspots": build_churn(files, args.limit),
        "files": files,
        "commits": commits
        if args.full
        else [{k: v for k, v in c.items() if k != "files"} for c in commits],
    }
    emit(payload, args.out)
    return 0


def cmd_clone(args):
    emit(clone(args.url, args.out_dir, args.ref, args.pr_url, not args.full_clone))
    return 0


def cmd_watermark(args):
    if args.action == "read":
        emit(read_watermark(args.file))
        return 0
    sha = args.sha or git(args.repo, "rev-parse", "HEAD").strip()
    emit(write_watermark(args.file, args.module, sha, args.doc, args.registry_hash))
    return 0


def add_range_flags(parser):
    parser.add_argument("--repo", default=".")
    parser.add_argument("--range", help="Explicit revision range, e.g. v1.2.0..HEAD")
    parser.add_argument("--since-tag", action="store_true", help="Span since the most recent tag")
    parser.add_argument("--since-sha")
    parser.add_argument("--since-watermark", help="Path to .docs-state.json")
    parser.add_argument("--path", nargs="*", help="Limit to these pathspecs")
    parser.add_argument("--max-count", type=int)
    parser.add_argument(
        "--issue-prefix",
        nargs="*",
        help="Project keys to scan for in commit text, e.g. RHOAIENG PROJ",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("range", help="Resolve which revision range to document")
    add_range_flags(p)
    p.set_defaults(func=cmd_range)

    p = sub.add_parser("commits", help="Structured commit corpus")
    add_range_flags(p)
    p.add_argument("--out")
    p.set_defaults(func=cmd_commits)

    p = sub.add_parser("changes", help="Per-file and per-module change rollup")
    add_range_flags(p)
    p.add_argument("--registry", help="docs-learn-code registry.json or {module: [prefix]} map")
    p.add_argument("--excludes", help="Pattern file, e.g. git_filters.yaml")
    p.add_argument("--out")
    p.set_defaults(func=cmd_changes)

    p = sub.add_parser("churn", help="Hotspot ranking")
    add_range_flags(p)
    p.add_argument("--registry")
    p.add_argument("--excludes")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--out")
    p.set_defaults(func=cmd_churn)

    p = sub.add_parser("context", help="Write the combined git-context.json artifact")
    add_range_flags(p)
    p.add_argument("--registry")
    p.add_argument("--excludes")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--full", action="store_true", help="Include per-commit file lists")
    p.add_argument("--out", default="git-context.json")
    p.set_defaults(func=cmd_context)

    p = sub.add_parser("clone", help="Treeless clone that preserves full history")
    p.add_argument("url")
    p.add_argument("--out", dest="out_dir", required=True)
    p.add_argument("--ref")
    p.add_argument("--pr-url")
    p.add_argument("--full-clone", action="store_true", help="Download all blobs up front")
    p.set_defaults(func=cmd_clone)

    p = sub.add_parser("watermark", help="Read or update the documented-SHA state file")
    p.add_argument("action", choices=["read", "write"])
    p.add_argument("--file", default=".docs-state.json")
    p.add_argument("--repo", default=".")
    p.add_argument("--module")
    p.add_argument("--sha")
    p.add_argument("--doc")
    p.add_argument("--registry-hash")
    p.set_defaults(func=cmd_watermark)

    args = parser.parse_args()
    if getattr(args, "repo", None) and not is_repo(args.repo) and args.command != "clone":
        print(json.dumps({"error": f"Not a git repository: {args.repo}"}))
        return 1
    try:
        return args.func(args)
    except GitError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

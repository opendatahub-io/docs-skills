#!/usr/bin/env python3
"""Run the whole artifact chain, in order, and stop early when nothing moved.

The CI entry point. Composes git-context, repo-analyze, the fingerprint layer,
docs-write, docs-review, and the metadata pass. Every arrow between steps is a
file under `.docs-gen/`, so a run can stop anywhere and resume from disk.

    sync.py --repo . --since-watermark .docs-state.json --llm-cmd "claude -p"
    sync.py --repo . --bootstrap --max-modules 20

Exit codes:
    0  wrote documentation
    1  nothing to do
    3  review findings blocked the run
    5  a write was refused by the ownership contract
"""

import argparse
import json
import os
import subprocess
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

try:
    import yaml
except ImportError:
    yaml = None

SCHEMA = "docs-skills/sync/1"

LIB = ENGINE / "scripts" / "lib"
# Every generator skill is a flat sibling of docs-engine, in an install and
# in a checkout alike, so one parent reaches all of them.
SKILLS = ENGINE.parent
CONFIG_NAME = ".docs-gen.yaml"
ARTIFACT_DIR = ".docs-gen"

DEFAULTS = {
    "llm_cmd": "claude -p",
    "docs_dir": "docs",
    "issue_prefixes": [],
    "bot_author": "",
    "max_modules_per_run": 20,
    "token_budget": 400000,
    "write_doc_comments": False,
    "language": "auto",
    "changelog": True,
    "modules": {"include": [], "exclude": []},
}


def log(message):
    print(f"docs-sync: {message}", file=sys.stderr)


# ------------------------------------------------------------------- config


def load_config(repo):
    """`.docs-gen.yaml` at the repository root. One config surface, not two."""
    config = dict(DEFAULTS)
    path = Path(repo) / CONFIG_NAME
    if not path.exists():
        return config
    if yaml is None:
        log(f"{CONFIG_NAME} found but PyYAML is missing; using defaults")
        return config
    data = yaml.safe_load(path.read_text()) or {}
    generate = data.get("generate") or {}
    for key, value in generate.items():
        config[key] = value
    return config


# --------------------------------------------------------------- loop guard


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    ).stdout.strip()


def loop_guard(repo, config, docs_dir):
    """Whether this run is looking at its own last commit.

    A docs pull request merges to main and becomes a push, which retriggers the
    workflow. Three independent signals stop that: the bot's own authorship,
    a change set confined to paths this tool writes, and a watermark already
    level with HEAD. Artifact paths belong in the second because `.docs-gen/`
    is committed, so a docs merge touches it on the way back.
    """
    author = git(repo, "log", "-1", "--format=%ae")
    bot = (config.get("bot_author") or "").strip()
    if bot and author and author.lower() == bot.lower():
        return f"HEAD was authored by the bot identity {bot}"

    changed = [
        line for line in git(repo, "diff", "--name-only", "HEAD~1", "HEAD").splitlines() if line
    ]
    if changed:
        owned = (f"{docs_dir}/", f"{ARTIFACT_DIR}/", ".docs-state.json", "CHANGELOG.md")
        if all(path.startswith(owned) or path in owned for path in changed):
            return f"every changed path is one this tool writes ({len(changed)} files)"
    return None


# ------------------------------------------------------------------- runner


def run(argv, label, allowed=(0,)):
    """Run one step. Returns its exit code; raises only on an unexpected one."""
    log(f"{label}")
    completed = subprocess.run([sys.executable, *[str(a) for a in argv]])
    if completed.returncode not in allowed:
        raise StepFailedError(label, completed.returncode)
    return completed.returncode


class StepFailedError(RuntimeError):
    def __init__(self, label, code):
        super().__init__(f"{label} exited {code}")
        self.label = label
        self.code = code


def boundaries_file(out_dir):
    """The `{module: [prefix]}` view api_surface.load_registry wants.

    registry.json carries kind and file lists too, and load_registry reads a
    plain mapping, so the projection is written out once per run.
    """
    registry = json.loads((out_dir / "registry.json").read_text())
    mapping = {name: entry["paths"] for name, entry in registry["modules"].items()}
    path = out_dir / "boundaries.json"
    path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n")
    return path, registry


# --------------------------------------------------------------------- main


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sync documentation with code")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", default=None, help=f"Default {ARTIFACT_DIR}")
    parser.add_argument("--docs-dir", default=None)
    parser.add_argument("--since-watermark", help="Path to .docs-state.json")
    parser.add_argument("--range", help="Explicit REV..REV, overriding the watermark")
    parser.add_argument("--llm-cmd", default=None)
    parser.add_argument("--max-modules", type=int, default=None)
    parser.add_argument("--token-budget", type=int, default=None)
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="First run: no watermark, every module in rebuild[]",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Shard rebuild[] across N writer invocations where the harness allows it",
    )
    parser.add_argument("--no-changelog", action="store_true")
    parser.add_argument("--no-review", action="store_true")
    parser.add_argument("--force", action="store_true", help="Skip the loop guard")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no writes")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    config = load_config(repo)
    docs_dir = args.docs_dir or config["docs_dir"]
    llm_cmd = args.llm_cmd or os.environ.get("DOCS_LLM_CMD") or config["llm_cmd"]
    max_modules = (
        args.max_modules if args.max_modules is not None else config["max_modules_per_run"]
    )
    out_dir = Path(args.out) if args.out else repo / ARTIFACT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    watermark = args.since_watermark or str(repo / ".docs-state.json")

    if not args.force and not args.bootstrap:
        reason = loop_guard(repo, config, docs_dir)
        if reason:
            log(f"nothing to do: {reason}")
            return 1

    # 1. Registry and per-module API. Runs before history, because attributing
    # a commit to a module needs the boundaries, and a first run has none.
    # Skipped entirely when the registry hash has not moved.
    analyze = [
        SKILLS / "docs-repo-analyze" / "scripts" / "analyze.py",
        "--repo",
        repo,
        "--out",
        out_dir,
    ]
    if not args.bootstrap:
        analyze.append("--skip-cached")
    for pattern in (config.get("modules") or {}).get("exclude") or []:
        analyze += ["--exclude", pattern]
    try:
        cached = run(analyze, "mapping modules", allowed=(0, 1)) == 1
    except StepFailedError as exc:
        log(str(exc))
        return 3
    if cached:
        log("registry_hash unchanged, module analysis skipped")

    boundaries, registry = boundaries_file(out_dir)

    # 2. History, attributed against those boundaries.
    context_args = [
        LIB / "git" / "git_context.py",
        "context",
        "--repo",
        repo,
        "--registry",
        boundaries,
        "--excludes",
        CONFIG / "path_filters.txt",
        "--out",
        out_dir / "git-context.json",
    ]
    if args.range:
        context_args += ["--range", args.range]
    elif not args.bootstrap and Path(watermark).exists():
        context_args += ["--since-watermark", watermark]
    for prefix in config.get("issue_prefixes") or []:
        context_args += ["--issue-prefix", prefix]
    try:
        run(context_args, "reading history")
    except StepFailedError as exc:
        log(str(exc))
        return 3

    context = json.loads((out_dir / "git-context.json").read_text())
    head = context.get("head", "")
    if context.get("range") is None:
        log("watermark is unreachable; treat this as a full rebuild")

    # 3. Fingerprints, then the relevance verdict.
    surface = out_dir / "api-surface.json"
    api_dir = out_dir / "api"

    def snapshot_args(out, at=None):
        """One snapshot invocation. `at` rebuilds a past surface in a worktree."""
        argv = [
            LIB / "git" / "api_surface.py",
            "snapshot",
            "--repo",
            repo,
            "--registry",
            boundaries,
            "--out",
            out,
        ]
        if api_dir.is_dir():
            argv += ["--api-dir", api_dir]
        if at:
            argv += ["--at", at]
        return argv

    if args.bootstrap:
        rebuild = list(registry["modules"])
        relevance = {
            "verdict": "bootstrap",
            "rebuild": rebuild,
            "update_refs": [],
            "skip": [],
            "review": [],
        }
        (out_dir / "relevance.json").write_text(json.dumps(relevance, indent=2) + "\n")
        run(snapshot_args(surface), "fingerprinting the public API")
        log(f"bootstrap: every module queued ({len(rebuild)})")
    else:
        base = (context.get("range") or {}).get("base")
        before = out_dir / "api-before.json"
        try:
            if base:
                run(
                    snapshot_args(before, at=base),
                    f"fingerprinting the API at {base[:7]}",
                )
            run(snapshot_args(surface), "fingerprinting the public API")
            if base and before.exists():
                run(
                    [
                        LIB / "git" / "api_surface.py",
                        "diff",
                        "--before",
                        before,
                        "--after",
                        surface,
                        "--out",
                        out_dir / "api-diff.json",
                    ],
                    "diffing the API surface",
                )
                run(
                    [
                        LIB / "git" / "api_surface.py",
                        "relevance",
                        "--git-context",
                        out_dir / "git-context.json",
                        "--api-diff",
                        out_dir / "api-diff.json",
                        "--out",
                        out_dir / "relevance.json",
                    ],
                    "deciding what to regenerate",
                )
            else:
                (out_dir / "relevance.json").write_text(
                    json.dumps(
                        {
                            "verdict": "no-base",
                            "rebuild": list(registry["modules"]),
                            "update_refs": [],
                            "skip": [],
                            "review": [],
                        },
                        indent=2,
                    )
                    + "\n"
                )
        except StepFailedError as exc:
            log(str(exc))
            return 3
        relevance = json.loads((out_dir / "relevance.json").read_text())

    rebuild = list(relevance.get("rebuild") or [])
    if relevance.get("verdict") == "full_rebuild":
        rebuild = list(registry["modules"])
        log("registry hash moved; every module rebuilds")

    if not rebuild:
        log(f"nothing to do: no module changed ({len(relevance.get('skip') or [])} skipped)")
        write_watermark(repo, watermark, head, registry, {})
        return 1

    if max_modules and len(rebuild) > max_modules:
        log(f"capping {len(rebuild)} modules at {max_modules}; resume from the watermark")
        rebuild = rebuild[:max_modules]

    log(f"{len(rebuild)} module(s) to write: {', '.join(rebuild[:10])}")
    if args.dry_run:
        return 0

    # 4. Write. Ownership guards live inside write.py, not here.
    write_args = [
        SKILLS / "docs-write" / "scripts" / "write.py",
        "--repo",
        repo,
        "--out",
        out_dir,
        "--docs-dir",
        docs_dir,
        "--llm-cmd",
        llm_cmd,
        "--modules",
        *rebuild,
    ]
    try:
        code = run(write_args, f"writing {len(rebuild)} document set(s)", allowed=(0, 1, 3))
    except StepFailedError as exc:
        log(str(exc))
        return 3

    report = json.loads((out_dir / "write-report.json").read_text())
    if report["refused"]:
        for record in report["refused"]:
            log(f"refused {record.get('path')}: {record.get('reason')}")
    if code == 3 and not report["written"]:
        log("every write failed")
        return 3
    if report["refused"] and not report["written"]:
        return 5

    # 5. Metadata, then review. Both deterministic unless a claim needs judging.
    # docs_meta takes --docs-dir on the parser, before the subcommand.
    run(
        [
            LIB / "md" / "docs_meta.py",
            "--docs-dir",
            docs_dir,
            "mark",
            "--repo",
            repo,
            "--source",
            "file,git,context",
            "--context",
            out_dir / "git-context.json",
            "--write",
        ],
        "filling frontmatter",
        allowed=(0, 1, 3),
    )

    review_code = 0
    if not args.no_review:
        review_code = run(
            [
                SKILLS / "docs-review" / "scripts" / "review.py",
                "--repo",
                repo,
                "--out",
                out_dir,
                "--docs-dir",
                docs_dir,
            ],
            "reviewing",
            allowed=(0, 1, 3),
        )

    run(
        [
            LIB / "md" / "docs_meta.py",
            "--docs-dir",
            docs_dir,
            "index",
            "--repo",
            repo,
            "--out",
            str(repo / "AGENTS.md"),
        ],
        "indexing",
        allowed=(0, 1, 3),
    )

    # 6. Changelog. Free when the repository writes conventional commits.
    if config.get("changelog") and not args.no_changelog:
        run(
            [
                SKILLS / "docs-changelog" / "scripts" / "changelog.py",
                "--context",
                out_dir / "git-context.json",
                "--repo",
                repo,
            ],
            "writing release notes",
            allowed=(0, 1, 3),
        )

    # 7. Watermark and the pull request body.
    written = {r["module"]: r.get("path") for r in report["written"] if r.get("module")}
    write_watermark(repo, watermark, head, registry, written)
    render_pr_body(out_dir, relevance, report, context)

    if review_code == 3:
        log("review found errors; the pull request body records them")
        return 3
    return 0 if report["written"] else 1


def write_watermark(repo, path, head, registry, written):
    """Record what is now documented, per module.

    Only modules whose documents were actually written advance. A module that
    was capped out of this run keeps its old SHA, so the next run picks it up
    where this one stopped.
    """
    target = Path(path)
    state = {"registry_hash": registry["registry_hash"], "modules": {}}
    if target.exists():
        try:
            state.update(json.loads(target.read_text()))
        except json.JSONDecodeError:
            pass
    state["registry_hash"] = registry["registry_hash"]
    for module, doc in written.items():
        state.setdefault("modules", {})[module] = {"sha": head, "doc": doc}
    target.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    log(f"watermark: {len(written)} module(s) advanced to {head[:7]}")


def render_pr_body(out_dir, relevance, report, context):
    """Why each module was rebuilt, and what a human still has to look at.

    Reviewers who see the reasoning read the diff differently from reviewers
    handed only the diff.
    """
    review_path = out_dir / "review.json"
    review = json.loads(review_path.read_text()) if review_path.exists() else {}
    summary = context.get("summary") or {}
    rng = context.get("range") or {}

    lines = [
        "## What changed",
        "",
        f"Range `{rng.get('base', '')[:7]}..{context.get('head', '')[:7]}`, "
        f"{summary.get('commit_count', 0)} commits, "
        f"{len(summary.get('pull_requests') or [])} pull requests.",
        "",
    ]

    if report["written"]:
        lines += ["### Documents written", ""]
        modules = relevance.get("modules") or {}
        for record in report["written"]:
            why = (modules.get(record.get("module")) or {}).get("reason") or record.get(
                "reason", ""
            )
            lines.append(f"- `{record['path']}` — {record['module']}: {why}")
        lines.append("")

    for label, key in (("Unchanged", "unchanged"), ("Deferred to a native generator", "deferred")):
        if report.get(key):
            lines += [f"### {label}", ""]
            lines += [
                f"- {r.get('path') or r['module']}: {r.get('reason', '')}" for r in report[key]
            ]
            lines.append("")

    blocked = [f for f in review.get("findings", []) if f["severity"] == "error"]
    stale = [f for f in review.get("findings", []) if f["kind"] == "stale-manual"]
    if blocked:
        lines += ["### Findings that block this run", ""]
        lines += [f"- `{f['doc']}`: {f['detail']}" for f in blocked]
        lines.append("")
    if stale:
        lines += [
            "### Hand-written pages whose subject moved",
            "",
            "These were not written. A human decides what they need.",
            "",
        ]
        lines += [f"- `{f['doc']}`: {f['detail']}" for f in stale]
        lines.append("")

    if report["refused"]:
        lines += ["### Refused by the ownership contract", ""]
        lines += [f"- `{r.get('path')}`: {r.get('reason')}" for r in report["refused"]]
        lines.append("")

    unattributed = relevance.get("unattributed_files") or []
    if unattributed:
        lines += [
            "### Files no module claims",
            "",
            f"{len(unattributed)} file(s) fell outside every registry prefix, so "
            "their changes reached no document.",
            "",
        ]

    (out_dir / "pr-body.md").write_text("\n".join(lines).rstrip() + "\n")


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Document a code repository: history, analysis, plan, write, review."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
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

from lib.git import commit_select, git_context  # noqa: E402
from lib.md import changeset as changeset_lib  # noqa: E402
from lib.pipeline import workspace  # noqa: E402
from lib.pipeline.config import (  # noqa: E402
    ARTIFACT_DIR,
    check_steps,
    llm_cmd_for,
    load_config,
    model_table,
    step_is_configured,
)
from lib.run import step  # noqa: E402
from lib.run.engine import LIB, PACKAGE_ROOT, SKILLS  # noqa: E402
from lib.run.report import logger  # noqa: E402
from lib.vale import check  # noqa: E402

SCHEMA = "docs-skills/sync/1"

log = logger("docs")


def seed_vale_config(template, target, styles):
    """Create the target config or append its missing default declarations."""
    template_text = Path(template).read_text()
    target = Path(target)
    if not target.exists():
        relative_styles = Path(os.path.relpath(styles, target.parent)).as_posix()
        template_text = template_text.replace(
            "StylesPath = ../styles", f"StylesPath = {relative_styles}", 1
        )
        target.write_text(template_text)
        return

    text = target.read_text()
    packages = next(line for line in template_text.splitlines() if line.startswith("Packages ="))
    markdown_styles = template_text[template_text.index("[*.md]") :].strip()
    missing = [part for part in (packages, markdown_styles) if part not in text]
    if missing:
        additions = "\n\n".join(missing)
        target.write_text(f"{text.rstrip()}\n\n{additions}\n")


def sync_styles(out_dir, repo=None):
    """Download the default Vale packages and seed the repository config."""
    template = PACKAGE_ROOT / "vale" / "docs.ini"
    if not template.is_file():
        log(f"Vale package config not found: {template}", "error")
        return 2

    out_dir = Path(out_dir).resolve()
    repo = Path(repo).resolve() if repo is not None else out_dir.parent
    repo.mkdir(parents=True, exist_ok=True)
    styles = out_dir / workspace.VALE_PACKAGES_DIR
    target_config = repo / ".vale.ini"
    seed_vale_config(template, target_config, styles)

    styles.mkdir(parents=True, exist_ok=True)
    packages = [line for line in template.read_text().splitlines() if line.startswith("Packages =")]
    if not packages:
        log(f"Vale package config names no packages: {template}", "error")
        return 2
    config = out_dir / "vale-sync.ini"
    config.write_text("\n".join([f"StylesPath = {styles}", *packages, ""]))

    try:
        completed = subprocess.run(["vale", "--config", str(config), "sync"])
    except FileNotFoundError:
        log("the vale binary is not on PATH", "error")
        return 2
    finally:
        config.unlink(missing_ok=True)
    return completed.returncode


# ------------------------------------------------------------------- config


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


# --------------------------------------------------------------- artifact gate

ALERT_CAP = 10


def report_alerts(alerts, cap=ALERT_CAP):
    """Log every alert up to `cap`, and say how many more there were."""
    for alert in alerts[:cap]:
        log(f"{Path(alert.file).name} line {alert.line}: {alert.check} - {alert.message[:80]}")
    if len(alerts) > cap:
        log(f"...{len(alerts) - cap} more alert(s) not shown")


def target_config(repo):
    """The repository's own Vale config, whichever of the names it uses."""
    for name in workspace.TARGET_CONFIGS:
        candidate = Path(repo) / name
        if candidate.is_file():
            return candidate
    return Path(repo) / ".vale.ini"


def existing_level(config, rule):
    """The line number and level a config already gives `rule`, if it gives one.

    Measured: Vale honours the first level it finds for a rule, so appending a
    second line for one the config already sets changes nothing. A message that
    says "add this line" is wrong for exactly the rules this tool sets levels
    for, which are the ones most likely to stop a run.
    """
    try:
        text = Path(config).read_text()
    except OSError:
        return None, ""
    # `[ \t]*` rather than `\s*`: `\s` matches a newline, so after a blank line
    # the match began one line early and the message named the blank line.
    pattern = re.compile(rf"^[ \t]*{re.escape(rule)}[ \t]*=[ \t]*(\S+)", re.MULTILINE)
    found = pattern.search(text)
    if not found:
        return None, ""
    return text[: found.start()].count("\n") + 1, found.group(1)


def explain_blocking(alerts, repo, cap=ALERT_CAP):
    """Name the rules that stopped the run, where they fired, and what to do.

    A run that ends on `a step failed` with a list of alerts above it leaves
    the reader to work out which of them was fatal and whether they are
    expected to rewrite the sentence or change the rule. Grouping by rule
    answers the first, and naming the config answers the second: a level set
    in the repository's own file is carried into every composed config and
    overrides the built-in one.
    """
    by_rule = {}
    for alert in alerts:
        by_rule.setdefault(alert.check, []).append(alert)
    rules = sorted(by_rule, key=lambda name: (-len(by_rule[name]), name))

    total = len(alerts)
    log(f"the run stopped on {len(rules)} rule(s), {total} error-level alert(s):")
    shown = 0
    for rule in rules:
        hits = by_rule[rule]
        log(f"  {rule} ({len(hits)}):")
        for alert in hits:
            if shown >= cap:
                break
            log(f"    {Path(alert.file).name} line {alert.line}: {alert.message[:100]}")
            shown += 1
    if total > shown:
        log(f"    ...{total - shown} more not shown")

    config = target_config(repo)
    log("")
    log(f"A rule that is wrong about these documents can be lowered in {config}:")
    log("")
    for rule in rules:
        line, level = existing_level(config, rule)
        if line:
            log(f"  {rule} = warning    (line {line}, currently `{level}`)")
        else:
            log(f"  {rule} = warning    (add it under [*.md])")
    log("")
    log("Then run again. `= NO` switches a rule off instead.")


def artifact_gate(root, vale_config, keys=None, files=None, repo=None):
    """Lint the chain's own artifacts; 3 if an error-level alert fired, else 0."""
    alerts, reason = workspace.lint_artifacts(root, vale_config, keys=keys, files=files)
    if reason:
        # A linter that never started reports no alerts. Passing the gate on
        # that is how a run reached write and review with prose checking off
        # and nothing in the log to say so.
        log(reason, "warning")
        return 0
    if not alerts:
        return 0
    # A budget is a target and warns; what an artifact must contain is a
    # contract and stops the run. Both are reported, so a reader sees the
    # overrun either way.
    blocking = [a for a in alerts if check.at_or_above(a.severity, "error")]
    if not blocking:
        report_alerts(alerts)
        return 0
    report_alerts([a for a in alerts if a not in blocking])
    explain_blocking(blocking, repo if repo is not None else Path.cwd())
    return 3


def issue_prefix_args(config):
    """`--issue-prefix` for the keys .docs-gen.yaml names, or nothing.

    Without this the flag was never passed, so `issue_prefixes` was a
    documented config key that changed nothing: keys written in a commit body
    were missed and only trailers were ever read.
    """
    prefixes = [str(p) for p in (config.get("issue_prefixes") or []) if str(p).strip()]
    return ["--issue-prefix", *prefixes] if prefixes else []


def has_history(repo):
    """Whether this is a git repository with at least one commit."""
    if not (Path(repo) / ".git").exists():
        return False
    done = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
    )
    return done.returncode == 0


def write_changes(named_contexts, subject, out_dir):
    """The commits most relevant to `subject`, across every context given."""
    commits = []
    for name, path in named_contexts:
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for commit in data.get("commits") or []:
            entry = dict(commit)
            if name:
                entry["repository"] = name
            commits.append(entry)

    selected = commit_select.select_commits(commits, subject)
    if not selected:
        return None

    changes_path = out_dir / "changes.json"
    changes_path.write_text(
        json.dumps(
            {
                "schema": "docs-skills/changes/1",
                "commits": [
                    {
                        "repository": c.get("repository"),
                        "sha": c.get("short"),
                        "subject": c.get("subject"),
                        "type": c.get("type"),
                        "scope": c.get("scope"),
                        "breaking": bool(c.get("breaking")),
                        "pr": c.get("pr"),
                        "date": c.get("date"),
                    }
                    for c in selected
                ],
            },
            indent=2,
        )
        + "\n"
    )
    return changes_path


def run_directory(root, args):
    """This run's own directory inside the artifact root.

    Keyed the same way the changeset under `docs/` is keyed, so a run's
    reasoning trail and its drafts carry one name. Every run used to write
    into the root itself, where the artifacts of one run sat beside another's,
    and a run that stopped early left its predecessor's `plan.json` looking
    like its own.
    """
    return Path(root) / (changeset_lib.marker_id("", args.topic or "") or "run")


def clear_run_directory(root, where):
    """Empty this run's directory, so a re-run starts from nothing.

    Re-running a topic wrote into whatever the last run had left. A run that
    stopped early kept its predecessor's `plan.json`, the
    steps after it read those as their own, and the artifacts then described a
    run that had not happened. Only what a run derives is removed: the clones
    and the Vale packages are in `root` and are shared, so nothing is
    downloaded again.
    """
    root, where = Path(root).resolve(), Path(where).resolve()
    # A wipe is worth one check that it is wiping what it thinks it is.
    if where == root or root not in where.parents:
        raise ValueError(f"{where} is not a run directory inside {root}")
    if not where.exists():
        return
    shutil.rmtree(where)
    log(f"cleared {where.name} from the last run")


def clear_changesets(repo, docs_dir, args):
    """Remove this subject's drafts from `docs/` before the run writes new ones.

    The same reason the run directory is emptied: a draft from a run that
    stopped halfway sat beside this run's as though both belonged to it. A
    draft marked `managed: manual` is kept, which is the promise the tool
    already makes about one.
    """
    name = changeset_lib.marker_id("", args.topic or "") or "run"
    records = changeset_lib.wipe(repo, docs_dir, name)
    removed = [r for r in records if r["status"] == "removed"]
    kept = [r for r in records if r["status"] == "kept"]
    if removed:
        log(f"cleared {len(removed)} draft(s) from the last run")
    for record in kept:
        log(f"kept {record['path']}: {record['reason']}")


def build(repo, root, docs_dir, config, args, env_cmd):
    """git context, repository analysis, plan, write, review.

    `root` is the artifact directory, `.docs-gen`. What this run derives goes
    in its own directory below it; what a run downloads rather than derives,
    the Vale packages, stays in the root and is shared.
    """
    out_dir = run_directory(root, args)
    clear_run_directory(root, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Every step in this run appends its working out to one file, in the
    # directory the rest of the run's artifacts land in. `setdefault`, so a
    # caller that named its own trail keeps it.
    os.environ.setdefault(step.TRAIL_ENV, str(out_dir / "reasoning.jsonl"))
    clear_changesets(repo, docs_dir, args)
    topic = args.topic or ""

    # The repository this run was pointed at. There is nothing else to read:
    # a run documents the code in front of it.
    context = None
    named_contexts = []
    if has_history(repo):
        try:
            run(
                [
                    LIB / "git" / "git_context.py",
                    "context",
                    "--repo",
                    repo,
                    # The per-commit file list, for the commit-to-file join.
                    "--full",
                    # Only the untagged fallback range was ever bounded; a
                    # repository that tags rarely could otherwise be read whole.
                    "--max-count",
                    str(git_context.MAX_COMMITS),
                    # Tests, vendored code and build output move constantly and
                    # tell a reader nothing, so they stay out of the churn
                    # ranking. Omitting this ranked them alongside source.
                    "--excludes",
                    ENGINE / "config" / "path_filters.txt",
                    *issue_prefix_args(config),
                    "--out",
                    out_dir / "git-context.json",
                ],
                "reading history",
            )
            run(
                [
                    LIB / "git" / "digest.py",
                    "--context",
                    out_dir / "git-context.json",
                    "--out",
                    out_dir / "git-context.md",
                ],
                "summarising history",
                allowed=(0, 1),
            )
            context = out_dir / "git-context.md"
            named_contexts = [(None, out_dir / "git-context.json")]
        except StepFailedError as exc:
            log(f"no repository context: {exc}", "warning")
    else:
        # A repository with no commits still has modules and a public API, and
        # those are what a page rests on. Only the history is missing.
        log("no repository context: nothing committed yet", "warning")

    changes_path = write_changes(named_contexts, topic, out_dir) if named_contexts else None

    if topic:
        log(f"topic: {topic}")

    analyze_argv = [
        SKILLS / "docs-repo-analyze" / "scripts" / "analyze.py",
        "--repo",
        repo,
        "--out",
        out_dir,
        "--llm-cmd",
        llm_cmd_for("analyze", config, args.llm_cmd, env_cmd),
    ]
    if topic:
        # Reading a large repository whole is minutes of work for symbols no
        # page uses. vllm took twelve minutes and produced 149,183 symbols.
        analyze_argv += ["--subject", topic]
    budget = (config.get("analyze") or {}).get("synthesis_budget")
    if budget:
        analyze_argv += ["--synthesis-budget", str(budget)]
    code = run(analyze_argv, "analyzing the repository", allowed=(0, 1, 2, 3))
    if code in (2, 3):
        log("the analysis step failed", "error")
        return 3
    if code == 1:
        # A repository this tool cannot read has nothing to plan from, and the
        # planner would refuse every page it produced. Saying so is exit 1.
        log("nothing to analyze; there is nothing to write", "warning")
        return 1

    plan_args = [
        SKILLS / "docs-plan" / "scripts" / "plan.py",
        "--repo",
        repo,
        "--docs-dir",
        docs_dir,
        "--out",
        out_dir,
        "--llm-cmd",
        llm_cmd_for("plan", config, args.llm_cmd, env_cmd),
    ]
    # Without a topic the run plans the foundation set, which is decided from
    # the evidence and spends no model call. A topic run keeps the planner
    # prompt, because a subject nobody named cannot be gated for.
    foundation = (config.get("generate") or {}).get("foundation") or {}
    if topic:
        plan_args += ["--topic", topic]
    elif foundation.get("enabled", True):
        plan_args.append("--foundation")
        for stem in foundation.get("skip") or []:
            plan_args += ["--skip-doc", str(stem)]
    if context and Path(context).is_file():
        plan_args += ["--context", context]
    if changes_path:
        plan_args += ["--changes", changes_path]
    code = run(plan_args, "planning", allowed=(0, 1, 2))
    if code:
        log("nothing planned", "warning")
        return 1 if code == 1 else 3

    # Late, because the workspace writes style files into the artifact
    # directory and nothing that scans the tree may run after it. Still ahead
    # of the dry-run check, because dry-run inspects the reasoning trail and
    # that is exactly when its budget should be checked.
    vale_config, note = workspace.build(
        repo,
        out_dir,
        config,
        PACKAGE_ROOT,
        packages_dir=Path(root) / workspace.VALE_PACKAGES_DIR,
    )
    if note:
        log(note)

    # Immediately before `write`, the expensive step: the reasoning trail is
    # checked before a model spends calls drafting from it.
    code = artifact_gate(out_dir, vale_config, repo=repo)
    if code:
        return code

    if args.dry_run:
        log("dry run: stopping before write")
        return 0

    write_args = [
        SKILLS / "docs-write" / "scripts" / "write.py",
        "--repo",
        repo,
        "--out",
        out_dir,
        "--docs-dir",
        docs_dir,
        "--plan",
        out_dir / "plan.json",
        "--llm-cmd",
        llm_cmd_for("write", config, args.llm_cmd, env_cmd),
    ]
    if vale_config:
        write_args += ["--vale-config", vale_config]
    if changes_path:
        write_args += ["--changes", changes_path]
    if topic:
        write_args += ["--topic", topic]
    where = changeset_lib.directory_for(docs_dir, "", topic, date.today().isoformat(), base=repo)
    write_args += ["--changeset", str(Path(repo) / where)]
    try:
        code = run(write_args, "writing the plan", allowed=(0, 1, 2, 3))
    except StepFailedError as exc:
        log(str(exc), "error")
        return 3
    if code == 2:
        log("the plan had nothing to write from", "warning")
        return 1
    if code == 1:
        log("nothing written", "warning")
        return 1
    if code == 3:
        log("the writer failed", "error")
        return 3

    # write.py produces index.md inside `where`, so it cannot exist at the
    # gate above. Linted by exact path rather than a glob, so a stale index
    # in a sibling changeset directory cannot fail this run.
    code = artifact_gate(None, vale_config, files=[Path(repo) / where / "index.md"], repo=repo)
    if code:
        return code

    if args.no_review:
        return 0
    review_args = [
        SKILLS / "docs-review" / "scripts" / "review.py",
        "--repo",
        repo,
        "--out",
        out_dir,
        "--docs-dir",
        docs_dir,
    ]
    if step_is_configured("review", config):
        review_args += ["--llm-cmd", llm_cmd_for("review", config, args.llm_cmd, env_cmd)]
    if vale_config:
        review_args += ["--vale-config", vale_config]
    return 3 if run(review_args, "reviewing", allowed=(0, 1, 3)) == 3 else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Document a code repository")
    parser.add_argument("--repo", default=".", help="Where documents are written")
    parser.add_argument(
        "--topic", help="Narrow the run to a subject. Without it, the whole repository"
    )
    parser.add_argument(
        "--out",
        default=None,
        help=f"The artifact root, one directory per run inside it. Default {ARTIFACT_DIR}",
    )
    parser.add_argument("--docs-dir", default=None)
    parser.add_argument("--llm-cmd", default=None)
    parser.add_argument(
        "--models", action="store_true", help="Print the resolved per-step models and exit"
    )
    parser.add_argument("--no-review", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, write nothing")
    parser.add_argument(
        "--sync-styles",
        action="store_true",
        help="Download the Vale packages used by the default prose checks",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out) if args.out else repo / ARTIFACT_DIR
    if args.sync_styles:
        sync_status = sync_styles(out_dir, repo)
        # Syncing is its own errand: it seeds `.vale.ini` and downloads the
        # packages, which is what someone does once in a new repository. A
        # topic alongside it says they meant to sync and then document, so
        # only that combination carries on into the chain.
        if sync_status != 0 or not args.topic:
            return sync_status

    config = load_config(repo)
    if config.get("_warning"):
        log(config["_warning"], "warning")
    docs_dir = args.docs_dir or config["docs_dir"]
    env_cmd = os.environ.get("DOCS_LLM_CMD")

    try:
        check_steps(config)
    except ValueError as exc:
        log(str(exc), "error")
        return 2
    if args.models:
        print(model_table(config, args.llm_cmd, env_cmd))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    where = run_directory(out_dir, args)
    log(f"artifacts: {os.path.relpath(where, repo)}")
    return build(repo, out_dir, docs_dir, config, args, env_cmd)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""action-comments helper: deterministic logic extracted from SKILL.md prose.

Stdlib-only. Each subcommand emits JSON to stdout so SKILL.md can act on it
instead of re-deriving procedure by hand on every run (important for the CI
cron use case, where prose drift under compaction is unacceptable).

Subcommands:
    resolve-mode        Decide CI vs interactive from flags + CI env vars.
    validate-url        Validate a PR/MR URL against the supported forge shapes.
    checkout-plan       Validate the head ref and decide the checkout action.
    workspace           Resolve the .agent_workspace dir and list artifacts.
    classify-outdated   Annotate reader comments JSON with an `outdated` flag.
    write-result        Write the step-result.json sidecar.

Usage:
    python3 action_comments.py resolve-mode [--ci] [--no-ci]
    python3 action_comments.py validate-url <url>
    python3 action_comments.py checkout-plan --head-ref <ref> [--current-branch <ref>]
    python3 action_comments.py workspace --repo-root <dir> [--base-path <dir>] [--pr <url>]
    python3 action_comments.py classify-outdated --repo-root <dir> [--comments-file <f>]
    python3 action_comments.py write-result --base-path <dir> --ticket <id> ...
"""

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Both public and self-hosted GitHub/GitLab.
PR_URL_RE = re.compile(r"^https://[^/]+/.+/(pull/\d+|merge_requests/\d+)")

# Safe git branch refs: alphanumerics, dot, hyphen, underscore, slash only.
BRANCH_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")

# Env vars set to "true" by common CI providers. GitHub Actions and GitLab CI
# both also set the generic CI var, but we check all three for robustness.
CI_ENV_VARS = ("CI", "GITHUB_ACTIONS", "GITLAB_CI")

# Workspace artifacts read for grounding (relative to the ticket dir).
WORKSPACE_ARTIFACTS = {
    "code_analysis": "code-analysis/ONBOARDING.md",
    "requirements": "requirements/requirements.md",
    "technical_review": "technical-review/review.md",
    "scope_audit": "scope-req-audit/step-result.json",
    "source_config": "source.yaml",
}


# ---------------------------------------------------------------------------
# Pure functions (unit-tested)
# ---------------------------------------------------------------------------


def resolve_mode(force_ci: bool, force_no_ci: bool, env: Dict[str, str]) -> Dict:
    """Decide whether to run in CI mode. Explicit flags win over env detection."""
    if force_ci and force_no_ci:
        raise ValueError("--ci and --no-ci are mutually exclusive")
    if force_no_ci:
        return {"ci_mode": False, "reason": "--no-ci flag"}
    if force_ci:
        return {"ci_mode": True, "reason": "--ci flag"}
    for var in CI_ENV_VARS:
        val = env.get(var, "")
        if val and val.strip().lower() not in ("0", "false"):
            return {"ci_mode": True, "reason": f"{var}={val}"}
    return {"ci_mode": False, "reason": "no CI flag or CI env var"}


def validate_pr_url(url: Optional[str]) -> bool:
    """True if the URL matches a supported GitHub PR or GitLab MR shape."""
    return bool(url and PR_URL_RE.match(url))


def plan_checkout(head_ref: str, current_branch: str) -> Dict:
    """Decide the branch-checkout action for Step 3.

    Validates head_ref against BRANCH_REF_RE (guards against injection into
    later git commands) and reports whether we are already on the target
    branch. Raises ValueError on an unsafe ref.
    """
    if not head_ref or not BRANCH_REF_RE.match(head_ref):
        raise ValueError(f"unsafe branch ref: {head_ref!r}")
    return {"head_ref": head_ref, "on_target_branch": head_ref == current_branch}


def _read_sidecar_url(sidecar: Path) -> Optional[str]:
    try:
        return json.loads(sidecar.read_text()).get("url")
    except (OSError, ValueError):
        return None


def select_workspace(
    repo_root: Optional[str],
    base_path: Optional[str],
    pr_url: Optional[str],
) -> Optional[str]:
    """Resolve the workspace ticket directory.

    --base-path wins. Otherwise look under <repo_root>/.agent_workspace: use the
    sole ticket dir if there is exactly one, else match by the create-merge-request
    sidecar `url` against pr_url. Returns None when nothing matches.
    """
    if base_path:
        return base_path
    if not repo_root:
        return None
    aw = Path(repo_root) / ".agent_workspace"
    if not aw.is_dir():
        return None
    tickets = sorted(d for d in aw.iterdir() if d.is_dir())
    if not tickets:
        return None
    if len(tickets) == 1:
        return str(tickets[0])
    if pr_url:
        for ticket in tickets:
            sidecar = ticket / "create-merge-request" / "step-result.json"
            if sidecar.is_file() and _read_sidecar_url(sidecar) == pr_url:
                return str(ticket)
    return None


def list_artifacts(workspace: Optional[str]) -> Dict:
    """Report which grounding artifacts exist under the workspace dir."""
    result: Dict = {"workspace": workspace, "artifacts": {}, "source_repo": None}
    if not workspace:
        return result
    ws = Path(workspace)
    for key, rel in WORKSPACE_ARTIFACTS.items():
        result["artifacts"][key] = (ws / rel).is_file()
    source_yaml = ws / "source.yaml"
    if source_yaml.is_file():
        repo_path = _parse_source_repo_path(source_yaml.read_text())
        if repo_path and Path(repo_path).is_dir():
            result["source_repo"] = repo_path
    return result


def _parse_source_repo_path(text: str) -> Optional[str]:
    """Extract `repo_path:` from source.yaml without a YAML dependency."""
    for line in text.splitlines():
        m = re.match(r"\s*repo_path:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip("'\"")
    return None


def classify_outdated(comment: Dict, repo_root: Optional[str]) -> bool:
    """True if the comment is outdated and should be auto-skipped.

    Uses the forge's own staleness signal (`position_outdated`, set when the
    diff hunk no longer maps the thread) plus a file-existence check — not a
    fragile verbatim text match on the reviewer's prose.
    """
    if comment.get("position_outdated"):
        return True
    path = comment.get("path")
    if not path:
        return False
    fp = Path(repo_root) / path if repo_root else Path(path)
    return not fp.is_file()


def build_sidecar(
    ticket: str,
    ci_mode: bool,
    comments_resolved: int,
    comments_skipped: int,
    comments_outdated: int,
    comments_replied: int,
    files_modified: List[str],
    now: Optional[str] = None,
) -> Dict:
    """Build the step-result.json payload conforming to action-comments-output.json."""
    return {
        "schema_version": 1,
        "step": "action-comments",
        "ticket": ticket,
        "completed_at": now
        or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ci_mode": ci_mode,
        "comments_resolved": comments_resolved,
        "comments_skipped": comments_skipped,
        "comments_outdated": comments_outdated,
        "comments_replied": comments_replied,
        "files_modified": files_modified,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_resolve_mode(args) -> int:
    try:
        result = resolve_mode(args.ci, args.no_ci, dict(os.environ))
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    print(json.dumps(result))
    return 0


def _cmd_validate_url(args) -> int:
    ok = validate_pr_url(args.url)
    print(json.dumps({"url": args.url, "valid": ok}))
    return 0 if ok else 1


def _cmd_checkout_plan(args) -> int:
    try:
        result = plan_checkout(args.head_ref, args.current_branch)
    except ValueError as e:
        print(json.dumps({"error": str(e)}))
        return 2
    print(json.dumps(result))
    return 0


def _cmd_workspace(args) -> int:
    workspace = select_workspace(args.repo_root, args.base_path, args.pr)
    print(json.dumps(list_artifacts(workspace)))
    return 0


def _cmd_classify_outdated(args) -> int:
    raw = Path(args.comments_file).read_text() if args.comments_file else sys.stdin.read()
    comments = json.loads(raw)
    for c in comments:
        c["outdated"] = classify_outdated(c, args.repo_root)
    print(json.dumps(comments))
    return 0


def _cmd_write_result(args) -> int:
    sidecar = build_sidecar(
        ticket=args.ticket,
        ci_mode=args.ci_mode,
        comments_resolved=args.comments_resolved,
        comments_skipped=args.comments_skipped,
        comments_outdated=args.comments_outdated,
        comments_replied=args.comments_replied,
        files_modified=args.files_modified or [],
    )
    out_dir = Path(args.base_path) / "action-comments"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "step-result.json"
    out_path.write_text(json.dumps(sidecar, indent=2) + "\n")
    print(json.dumps({"written": str(out_path)}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_mode = sub.add_parser("resolve-mode", help="Decide CI vs interactive mode")
    p_mode.add_argument("--ci", action="store_true", help="Force CI mode")
    p_mode.add_argument("--no-ci", dest="no_ci", action="store_true", help="Force interactive")
    p_mode.set_defaults(func=_cmd_resolve_mode)

    p_url = sub.add_parser("validate-url", help="Validate a PR/MR URL")
    p_url.add_argument("url")
    p_url.set_defaults(func=_cmd_validate_url)

    p_co = sub.add_parser("checkout-plan", help="Validate head ref and decide checkout action")
    p_co.add_argument("--head-ref", dest="head_ref", required=True)
    p_co.add_argument("--current-branch", dest="current_branch", default="")
    p_co.set_defaults(func=_cmd_checkout_plan)

    p_ws = sub.add_parser("workspace", help="Resolve workspace and list artifacts")
    p_ws.add_argument("--repo-root", dest="repo_root")
    p_ws.add_argument("--base-path", dest="base_path")
    p_ws.add_argument("--pr")
    p_ws.set_defaults(func=_cmd_workspace)

    p_cls = sub.add_parser("classify-outdated", help="Annotate comments with outdated flag")
    p_cls.add_argument("--repo-root", dest="repo_root")
    p_cls.add_argument("--comments-file", dest="comments_file", help="Default: stdin")
    p_cls.set_defaults(func=_cmd_classify_outdated)

    p_res = sub.add_parser("write-result", help="Write step-result.json sidecar")
    p_res.add_argument("--base-path", dest="base_path", required=True)
    p_res.add_argument("--ticket", required=True)
    p_res.add_argument("--ci-mode", dest="ci_mode", action="store_true")
    p_res.add_argument("--comments-resolved", dest="comments_resolved", type=int, default=0)
    p_res.add_argument("--comments-skipped", dest="comments_skipped", type=int, default=0)
    p_res.add_argument("--comments-outdated", dest="comments_outdated", type=int, default=0)
    p_res.add_argument("--comments-replied", dest="comments_replied", type=int, default=0)
    p_res.add_argument("--files-modified", dest="files_modified", nargs="*", default=[])
    p_res.set_defaults(func=_cmd_write_result)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

# /// script
# requires-python = ">=3.9"
# dependencies = ["requests"]
# ///
"""Assess JIRA ticket readiness for the docs-orchestrator workflow.

Runs mechanical checks (PR linkage, metadata, relationships) and outputs
structured JSON. Description quality assessment is handled by the SKILL.md
agent overlay — this script outputs description_quality: null.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_READY_STATUSES = [
    "Done",
    "Closed",
    "Resolved",
    "In Review",
    "Code Review",
    "Release Pending",
]
WARN_STATUSES = ["In Progress", "In Development", "In QE Review", "QE Review"]
PR_URL_PATTERN = re.compile(
    r"https?://(?:github\.com/.+/pull/\d+|gitlab\.com/.+/-/merge_requests/\d+)"
)
REPO_URL_PATTERN = re.compile(r"https?://(?:github\.com|gitlab\.com)/[^/]+/[^/]+")
_SAFE_JIRA_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")
_ALLOWED_JIRA_HOSTS = {"redhat.atlassian.net"}


def load_env():
    """Load .env files (project root then home), never overwriting existing vars."""
    for env_path in [
        Path.cwd() / ".env",
        Path.home() / ".env",
    ]:
        if not env_path.is_file():
            continue
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key not in os.environ:
                    os.environ[key] = value


def resolve_jira_reader(plugin_root: str) -> str:
    """Resolve path to jira_reader.py."""
    path = os.path.join(plugin_root, "skills", "jira-reader", "scripts", "jira_reader.py")
    if not os.path.isfile(path):
        print(json.dumps({"error": f"jira_reader.py not found at {path}"}), file=sys.stdout)
        sys.exit(1)
    return path


def run_jira_reader(jira_reader_path: str, args: list[str]) -> dict | list:
    """Call jira_reader.py as a subprocess and return parsed JSON."""
    cmd = ["uv", "run", "--script", jira_reader_path] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"error": f"Failed to invoke jira_reader.py: {e}"}
    if result.returncode != 0:
        error_msg = result.stderr.strip() or f"jira_reader.py exited with code {result.returncode}"
        return {"error": error_msg}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON from jira_reader.py: {result.stdout[:200]}"}


def fetch_issue_data(jira_reader_path: str, issue_key: str) -> dict:
    """Fetch ticket metadata via jira_reader.py --issue."""
    return run_jira_reader(jira_reader_path, ["--issue", issue_key])


def fetch_graph_data(jira_reader_path: str, issue_key: str) -> dict:
    """Fetch relationship graph via jira_reader.py --graph."""
    return run_jira_reader(jira_reader_path, ["--graph", issue_key])


def fetch_jql_data(jira_reader_path: str, jql: str, max_results: int = 10) -> list:
    """Fetch ticket list via jira_reader.py --jql."""
    data = run_jira_reader(jira_reader_path, ["--jql", jql, "--max-results", str(max_results)])
    if isinstance(data, dict) and "error" in data:
        return data
    if isinstance(data, dict):
        return [data]
    return data


def _collect_all_git_links(issue_data: dict, graph_data: dict) -> dict:
    """Collect git links from ticket, children, and grandchildren.

    Returns {"prs": [...urls], "commits": [...urls], "repos": [...urls],
             "sources": {"PROJ-123": [...], "PROJ-456": [...]}}
    """
    prs = []
    commits = []
    repos = set()
    sources = {}

    def classify_links(links, source_key):
        source_prs = []
        for url in links:
            if PR_URL_PATTERN.match(url):
                prs.append(url)
                source_prs.append(url)
                repo_match = REPO_URL_PATTERN.match(url)
                if repo_match:
                    repos.add(repo_match.group(0))
            elif REPO_URL_PATTERN.match(url):
                repos.add(REPO_URL_PATTERN.match(url).group(0))
                commits.append(url)
            else:
                commits.append(url)
        if source_prs:
            sources[source_key] = source_prs

    # Ticket's own git links
    classify_links(issue_data.get("git_links", []), issue_data.get("issue_key", ""))

    # Web links from graph (top-level)
    for wl in (graph_data.get("web_links") or {}).get("links", []):
        if wl.get("type") == "pull_request":
            url = wl["url"]
            if url not in prs:
                prs.append(url)
                sources.setdefault(issue_data.get("issue_key", ""), []).append(url)
                repo_match = REPO_URL_PATTERN.match(url)
                if repo_match:
                    repos.add(repo_match.group(0))

    # Children and their links
    for child in (graph_data.get("children") or {}).get("issues", []):
        classify_links(child.get("git_links", []), child["key"])
        for pr_url in (child.get("auto_discovered_urls") or {}).get("pull_requests", []):
            if pr_url not in prs:
                prs.append(pr_url)
                sources.setdefault(child["key"], []).append(pr_url)
                repo_match = REPO_URL_PATTERN.match(pr_url)
                if repo_match:
                    repos.add(repo_match.group(0))
        # Grandchildren via issue_links on children
        for link in (child.get("issue_links") or {}).get("links", []):
            classify_links(link.get("git_links", []), link["key"])

    return {"prs": prs, "commits": commits, "repos": list(repos), "sources": sources}


def check_pr_linkage(issue_data: dict, graph_data: dict, pr_states: dict | None = None) -> dict:
    """Dimension 2: PR/source linkage checks.

    pr_states is an optional dict of {url: state} for testing PR state checks.
    In production, PR state is not checked (would require GitHub/GitLab API calls).
    """
    collected = _collect_all_git_links(issue_data, graph_data)
    checks = {}

    # Check: git links present
    if collected["prs"]:
        source_details = []
        for src_key, src_prs in collected["sources"].items():
            source_details.append(f"{len(src_prs)} on {src_key}")
        detail = f"{len(collected['prs'])} PRs found ({', '.join(source_details)})"
        checks["git_links_present"] = {"status": "pass", "detail": detail}
    elif collected["commits"] or collected["repos"]:
        checks["git_links_present"] = {
            "status": "warn",
            "detail": (
                "Repo/commit links found but no PRs: "
                f"{', '.join(collected['repos'] or collected['commits'][:3])}"
            ),
        }
    else:
        checks["git_links_present"] = {
            "status": "fail",
            "detail": "No git-related links at any level (ticket, children, grandchildren)",
        }

    # Check: PR state (only if pr_states provided — used in testing)
    if collected["prs"]:
        if pr_states:
            states = [pr_states.get(url, "open") for url in collected["prs"]]
            if any(s in ("merged", "open") for s in states):
                merged = sum(1 for s in states if s == "merged")
                opened = sum(1 for s in states if s == "open")
                checks["pr_state"] = {"status": "pass", "detail": f"{merged} merged, {opened} open"}
            elif all(s == "draft" for s in states):
                checks["pr_state"] = {"status": "warn", "detail": "All PRs are draft"}
            else:
                checks["pr_state"] = {"status": "fail", "detail": "All PRs are closed/abandoned"}
        else:
            checks["pr_state"] = {
                "status": "pass",
                "detail": f"{len(collected['prs'])} PR(s) linked (state not verified)",
            }
    else:
        checks["pr_state"] = {"status": "fail", "detail": "No PRs to check state"}

    # Check: source repo identifiable
    if collected["repos"]:
        checks["source_repo"] = {"status": "pass", "detail": ", ".join(collected["repos"])}
    elif collected["commits"]:
        checks["source_repo"] = {
            "status": "warn",
            "detail": "Commit links found but no repo context",
        }
    else:
        checks["source_repo"] = {"status": "fail", "detail": "No source identifiable"}

    # Compute dimension status
    statuses = [c["status"] for c in checks.values()]
    if "fail" in statuses:
        dim_status = "fail"
    elif "warn" in statuses:
        dim_status = "warn"
    else:
        dim_status = "pass"

    return {"status": dim_status, "checks": checks}


def check_metadata(issue_data: dict, ready_statuses: list[str] | None = None) -> dict:
    """Dimension 3: Metadata completeness checks."""
    if ready_statuses is None:
        ready_statuses = DEFAULT_READY_STATUSES
    checks = {}

    # Fix versions
    fix_versions = (issue_data.get("custom_fields") or {}).get("fix_versions", [])
    if fix_versions:
        checks["fix_versions"] = {"status": "pass", "detail": ", ".join(fix_versions)}
    else:
        checks["fix_versions"] = {"status": "fail", "detail": "not set"}

    # Release note type
    rn_type = (issue_data.get("custom_fields") or {}).get("release_note_type")
    if rn_type:
        checks["release_note_type"] = {"status": "pass", "detail": rn_type}
    else:
        checks["release_note_type"] = {"status": "fail", "detail": "not set"}

    # Priority
    priority = issue_data.get("priority", "Undefined")
    if priority and priority != "Undefined":
        checks["priority"] = {"status": "pass", "detail": priority}
    else:
        checks["priority"] = {"status": "fail", "detail": "not set"}

    # Status
    status = issue_data.get("status", "")
    ready_lower = [s.lower() for s in ready_statuses]
    warn_lower = [s.lower() for s in WARN_STATUSES]
    if status.lower() in ready_lower:
        checks["ticket_status"] = {"status": "pass", "detail": status}
    elif status.lower() in warn_lower:
        checks["ticket_status"] = {"status": "warn", "detail": status}
    else:
        checks["ticket_status"] = {"status": "fail", "detail": status or "not set"}

    # Compute dimension status
    statuses = [c["status"] for c in checks.values()]
    if "fail" in statuses:
        dim_status = "fail"
    elif "warn" in statuses:
        dim_status = "warn"
    else:
        dim_status = "pass"

    return {"status": dim_status, "checks": checks}


def check_relationships(issue_data: dict, graph_data: dict) -> dict:
    """Dimension 4: Relationship context checks."""
    checks = {}
    issue_type = issue_data.get("issue_type", "").lower()
    is_container = issue_type in ("epic", "initiative", "feature")

    # Parent/Epic
    parent = graph_data.get("parent")
    if parent:
        checks["parent_epic"] = {
            "status": "pass",
            "detail": (
                f"{parent['key']} ({parent.get('issuetype', 'Unknown')}:"
                f" {parent.get('summary', 'N/A')})"
            ),
        }
    else:
        checks["parent_epic"] = {"status": "fail", "detail": "Orphan ticket (no parent or epic)"}

    # Children
    children = (graph_data.get("children") or {}).get("issues", [])
    child_count = (graph_data.get("children") or {}).get("total", 0)
    if is_container and child_count == 0:
        checks["children"] = {"status": "fail", "detail": f"{issue_type.title()} has no children"}
    elif child_count > 0:
        checks["children"] = {"status": "pass", "detail": f"{child_count} children"}
    else:
        checks["children"] = {
            "status": "pass",
            "detail": "No children (not required for this issue type)",
        }

    # Grandchildren PRs — check children's git links
    if children:
        with_prs = sum(
            1
            for c in children
            if c.get("git_links") or (c.get("auto_discovered_urls") or {}).get("pull_requests")
        )
        without_prs = len(children) - with_prs
        if without_prs == 0:
            checks["grandchildren_prs"] = {
                "status": "pass",
                "detail": f"All {len(children)} children have PRs",
            }
        elif with_prs > 0:
            checks["grandchildren_prs"] = {
                "status": "warn",
                "detail": f"{with_prs}/{len(children)} children have PRs",
            }
        else:
            checks["grandchildren_prs"] = {
                "status": "info",
                "detail": f"0/{len(children)} children have PRs",
            }
    else:
        checks["grandchildren_prs"] = {"status": "info", "detail": "No children to check"}

    # Siblings
    sibling_count = (graph_data.get("siblings") or {}).get("total", 0)
    if sibling_count > 0:
        checks["siblings"] = {"status": "info", "detail": f"{sibling_count} siblings under parent"}
    else:
        checks["siblings"] = {"status": "info", "detail": "No siblings"}

    # "Is documented by" issue links
    issue_links = (graph_data.get("issue_links") or {}).get("links", [])
    doc_links = [lnk for lnk in issue_links if "documented" in lnk.get("direction", "").lower()]
    if doc_links:
        keys = [f"{lnk['key']} ({lnk.get('issuetype', 'Unknown')})" for lnk in doc_links]
        checks["documented_by"] = {
            "status": "pass",
            "detail": ", ".join(keys),
        }
    else:
        checks["documented_by"] = {
            "status": "info",
            "detail": "No 'Is documented by' links found",
        }

    # Compute dimension status (info doesn't count as warn or fail)
    statuses = [c["status"] for c in checks.values() if c["status"] not in ("info",)]
    if "fail" in statuses:
        dim_status = "fail"
    elif "warn" in statuses:
        dim_status = "warn"
    else:
        dim_status = "pass"

    return {"status": dim_status, "checks": checks}


def compute_overall_status(dimensions: dict) -> str:
    """Compute overall readiness verdict from dimension results."""
    statuses = []
    for dim in dimensions.values():
        if dim is None:
            continue
        statuses.append(dim.get("status", "pass"))
    if "fail" in statuses:
        return "not_ready"
    if "warn" in statuses:
        return "ready_with_warnings"
    return "ready"


def build_relationship_map(graph_data: dict) -> dict:
    """Build a simplified relationship map from graph data."""
    rel_map = {}

    parent = graph_data.get("parent")
    if parent:
        rel_map["parent"] = {
            "key": parent["key"],
            "summary": parent.get("summary", ""),
            "type": parent.get("issuetype", "Unknown"),
        }

    children = (graph_data.get("children") or {}).get("issues", [])
    if children:
        rel_map["children"] = []
        for child in children:
            child_entry = {
                "key": child["key"],
                "summary": child.get("summary", ""),
                "type": child.get("issuetype", "Unknown"),
            }
            pr_links = [u for u in child.get("git_links", []) if PR_URL_PATTERN.match(u)]
            if pr_links:
                child_entry["pr"] = pr_links[0]
            # Grandchildren from issue_links
            grandchildren = []
            for link in (child.get("issue_links") or {}).get("links", []):
                gc = {
                    "key": link["key"],
                    "summary": link.get("summary", ""),
                    "type": link.get("issuetype", "Unknown"),
                }
                gc_pr_links = [u for u in link.get("git_links", []) if PR_URL_PATTERN.match(u)]
                if gc_pr_links:
                    gc["pr"] = gc_pr_links[0]
                grandchildren.append(gc)
            if grandchildren:
                child_entry["children"] = grandchildren
            rel_map["children"].append(child_entry)

    siblings = (graph_data.get("siblings") or {}).get("issues", [])
    if siblings:
        rel_map["siblings"] = [
            {
                "key": s["key"],
                "summary": s.get("summary", ""),
                "type": s.get("issuetype", "Unknown"),
            }
            for s in siblings
        ]

    issue_links = (graph_data.get("issue_links") or {}).get("links", [])
    doc_links = [lnk for lnk in issue_links if "documented" in lnk.get("direction", "").lower()]
    if doc_links:
        rel_map["documented_by"] = []
        for lnk in doc_links:
            entry = {
                "key": lnk["key"],
                "summary": lnk.get("summary", ""),
                "type": lnk.get("issuetype", "Unknown"),
            }
            lnk_pr_links = [u for u in lnk.get("git_links", []) if PR_URL_PATTERN.match(u)]
            if lnk_pr_links:
                entry["pr"] = lnk_pr_links[0]
            rel_map["documented_by"].append(entry)

    return rel_map


def assess_ticket(
    issue_data: dict,
    graph_data: dict,
    ready_statuses: list[str] | None = None,
) -> dict:
    """Run all mechanical dimension checks and return structured result."""
    dimensions = {
        "description_quality": None,
        "pr_source_linkage": check_pr_linkage(issue_data, graph_data),
        "metadata_completeness": check_metadata(issue_data, ready_statuses),
        "relationship_context": check_relationships(issue_data, graph_data),
    }

    return {
        "ticket": issue_data.get("issue_key", ""),
        "summary": issue_data.get("summary", ""),
        "url": issue_data.get("url", ""),
        "overall_status": compute_overall_status(dimensions),
        "dimensions": dimensions,
        "relationship_map": build_relationship_map(graph_data),
        "description_text": issue_data.get("description", ""),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Assess JIRA ticket readiness for docs-orchestrator workflow."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--issue", help="Single JIRA ticket key (e.g., PROJ-123)")
    mode.add_argument("--jql", help="JQL query for batch assessment")
    mode.add_argument(
        "--post-comment",
        action="store_true",
        help="Read merged verdict JSON from stdin and post comments to JIRA",
    )

    parser.add_argument("--output-dir", help="Write per-ticket markdown reports to this directory")
    parser.add_argument("--max-results", type=int, default=10, help="Max tickets for JQL mode")
    parser.add_argument(
        "--ready-statuses",
        help="Comma-separated list of JIRA statuses considered docs-ready",
    )
    parser.add_argument(
        "--plugin-root",
        default=os.environ.get("CLAUDE_PLUGIN_ROOT", os.environ.get("CLAUDE_PLUGIN_DIR", "")),
        help="Plugin root for cross-skill script calls",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env()

    ready_statuses = None
    if args.ready_statuses:
        ready_statuses = [s.strip() for s in args.ready_statuses.split(",")]

    if args.post_comment:
        return handle_post_comment()

    jira_reader = resolve_jira_reader(args.plugin_root)

    if args.issue:
        result = handle_single_ticket(jira_reader, args.issue, ready_statuses)
    else:
        result = handle_batch(jira_reader, args.jql, args.max_results, ready_statuses)

    if args.output_dir:
        if isinstance(result, dict) and "error" not in result:
            write_markdown_reports(result, args.output_dir)

    print(json.dumps(result, indent=2))
    return 0


def handle_single_ticket(
    jira_reader: str, issue_key: str, ready_statuses: list[str] | None
) -> dict:
    issue_data = fetch_issue_data(jira_reader, issue_key)
    if "error" in issue_data:
        return issue_data

    graph_data = fetch_graph_data(jira_reader, issue_key)
    if isinstance(graph_data, dict) and "error" in graph_data:
        return {"error": f"Graph fetch failed: {graph_data['error']}", "ticket": issue_key}

    return assess_ticket(issue_data, graph_data, ready_statuses)


def handle_batch(
    jira_reader: str, jql: str, max_results: int, ready_statuses: list[str] | None
) -> dict:
    jql_data = fetch_jql_data(jira_reader, jql, max_results)
    if isinstance(jql_data, dict) and "error" in jql_data:
        return jql_data

    tickets = []
    for item in jql_data:
        key = item.get("issue_key", "")
        result = handle_single_ticket(jira_reader, key, ready_statuses)
        tickets.append(result)

    summary = {"ready": 0, "ready_with_warnings": 0, "not_ready": 0}
    for t in tickets:
        status = t.get("overall_status", "not_ready")
        if status in summary:
            summary[status] += 1

    return {
        "query": jql,
        "total_matched": len(jql_data),
        "summary": summary,
        "tickets": tickets,
    }


def format_comment(result: dict) -> dict:
    """Format a readiness verdict as an ADF document body for JIRA REST API v3."""
    status = result.get("overall_status", "not_ready")
    dims = result.get("dimensions", {})
    content = []

    status_labels = {
        "ready": "READY",
        "ready_with_warnings": "READY (with warnings)",
        "not_ready": "NOT READY",
    }
    heading_text = f"Docs readiness: {status_labels.get(status, status.upper())}"
    content.append(
        {
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": heading_text}],
        }
    )

    if status == "ready":
        content.append(
            _adf_paragraph(
                "This ticket has sufficient information to begin the documentation workflow."
            )
        )
    elif status == "ready_with_warnings":
        content.append(_adf_paragraph("This ticket can proceed but has minor gaps:"))
        gap_items = _format_dimension_gaps(dims, warns_only=True)
        if gap_items:
            content.append({"type": "bulletList", "content": gap_items})
    else:
        content.append(
            _adf_paragraph("This ticket needs the following before documentation work can begin:")
        )
        gap_items = _format_dimension_gaps(dims, warns_only=False)
        if gap_items:
            content.append({"type": "bulletList", "content": gap_items})

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    content.append(
        {
            "type": "paragraph",
            "content": [
                {"type": "emoji", "attrs": {"shortName": ":robot:", "text": "\U0001f916"}},
                {
                    "type": "text",
                    "text": f" Assessed by /docs-ticket-readiness skill on {date_str}",
                    "marks": [{"type": "em"}],
                },
            ],
        }
    )

    return {"version": 1, "type": "doc", "content": content}


def _adf_paragraph(text: str) -> dict:
    """Build a simple ADF paragraph node."""
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


_DIM_LABELS = {
    "description_quality": "Description quality",
    "pr_source_linkage": "PR/source linkage",
    "metadata_completeness": "Metadata",
    "relationship_context": "Relationships",
}

_CHECK_LABELS = {
    "fix_versions": "Fix versions",
    "release_note_type": "Release note type",
    "priority": "Priority",
    "ticket_status": "Status",
    "git_links_present": "Git links",
    "pr_state": "PR state",
    "pr_relevance": "PR relevance",
    "source_repo": "Source repo",
    "parent_epic": "Parent/epic",
    "children": "Children",
    "grandchildren_prs": "Children PRs",
    "siblings": "Siblings",
    "documented_by": "Documented by",
}


def _format_dimension_gaps(dims: dict, warns_only: bool) -> list[dict]:
    """Build ADF listItem nodes for non-passing dimensions."""
    items = []

    for dim_key, label in _DIM_LABELS.items():
        dim = dims.get(dim_key)
        if dim is None:
            continue
        dim_status = dim.get("status", "pass")
        if dim_status == "pass" or dim_status == "info":
            continue
        if warns_only and dim_status == "fail":
            continue

        if dim_key == "description_quality":
            gaps = dim.get("gaps", [])
            score = dim.get("score", "?")
            gap_text = ", ".join(gaps) if gaps else "insufficient detail"
            detail_text = f" {gap_text} (score: {score}/5)"
        else:
            checks = dim.get("checks", {})
            failing_details = []
            for check_name, check in checks.items():
                if check.get("status") in ("fail", "warn"):
                    cl = _CHECK_LABELS.get(check_name, check_name.replace("_", " ").title())
                    detail = check.get("detail", "")
                    failing_details.append(f"{cl}: {detail}")
            detail_text = f" {'; '.join(failing_details)}" if failing_details else ""

        if not detail_text.strip():
            continue

        items.append(
            {
                "type": "listItem",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": f"{label}:", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": detail_text},
                        ],
                    }
                ],
            }
        )

    return items


def post_jira_comment(
    issue_key: str, comment_adf: dict, jira_url: str, email: str, token: str
) -> dict:
    """Post a comment to a JIRA ticket via REST API v3.

    comment_adf is an ADF document body dict (with version, type, content keys).
    """
    import requests

    url = f"{jira_url.rstrip('/')}/rest/api/3/issue/{issue_key}/comment"
    body = {"body": comment_adf}

    try:
        resp = requests.post(
            url,
            json=body,
            auth=(email, token),
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        return {"status": "error", "ticket": issue_key, "detail": str(e)}

    if resp.status_code in (200, 201):
        return {"status": "ok", "ticket": issue_key}
    return {
        "status": "error",
        "ticket": issue_key,
        "http_status": resp.status_code,
        "detail": resp.text[:200],
    }


def handle_post_comment() -> int:
    """Read merged verdict JSON from stdin and post comments to JIRA."""
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON on stdin: {e}"}))
        return 1

    jira_url = os.environ.get("JIRA_URL", "https://redhat.atlassian.net")
    if urlparse(jira_url).hostname not in _ALLOWED_JIRA_HOSTS:
        print(json.dumps({"error": f"Refusing to post to untrusted JIRA_URL host: {jira_url}"}))
        return 1

    email = os.environ.get("JIRA_EMAIL", "")
    token = os.environ.get("JIRA_API_TOKEN", os.environ.get("JIRA_AUTH_TOKEN", ""))

    if not email or not token:
        print(json.dumps({"error": "JIRA_EMAIL and JIRA_API_TOKEN required for comment posting"}))
        return 1

    if "tickets" in data:
        tickets = data["tickets"]
    else:
        tickets = [data]

    results = []
    for ticket in tickets:
        if ticket.get("error"):
            results.append(
                {
                    "status": "skipped",
                    "ticket": ticket.get("ticket", "?"),
                    "reason": "assessment had errors",
                }
            )
            continue
        comment = format_comment(ticket)
        result = post_jira_comment(ticket["ticket"], comment, jira_url, email, token)
        results.append(result)

    print(json.dumps({"comment_results": results}, indent=2))
    return 0


def format_markdown_report(result: dict) -> str:
    """Format a per-ticket readiness report as markdown."""
    ticket = result.get("ticket", "UNKNOWN")
    summary = result.get("summary", "")
    url = result.get("url", "")
    overall = result.get("overall_status", "not_ready")
    dims = result.get("dimensions", {})
    rel_map = result.get("relationship_map", {})

    status_label = {
        "ready": "READY",
        "ready_with_warnings": "READY (with warnings)",
        "not_ready": "NOT READY",
    }.get(overall, overall.upper())

    lines = [
        f"# {ticket} — Readiness Assessment",
        "",
        f"**Summary:** {summary}",
        f"**URL:** {url}",
        f"**Verdict:** {status_label}",
        "",
        "---",
        "",
        "## Dimension Results",
        "",
    ]

    dim_labels = {
        "description_quality": "Description Quality",
        "pr_source_linkage": "PR/Source Linkage",
        "metadata_completeness": "Metadata Completeness",
        "relationship_context": "Relationship Context",
    }

    for dim_key, label in dim_labels.items():
        dim = dims.get(dim_key)
        if dim is None:
            lines.append(f"### {label}: _skipped_")
            lines.append("")
            continue

        dim_status = dim.get("status", "pass").upper()
        lines.append(f"### {label}: {dim_status}")
        lines.append("")

        if dim_key == "description_quality":
            score = dim.get("score", "?")
            lines.append(f"- Score: {score}/5")
            gaps = dim.get("gaps", [])
            if gaps:
                lines.append("- Gaps:")
                for gap in gaps:
                    lines.append(f"  - {gap}")
        else:
            checks = dim.get("checks", {})
            for check_name, check in checks.items():
                check_status = check.get("status", "pass")
                detail = check.get("detail", "")
                icon = {"pass": "pass", "warn": "WARN", "fail": "FAIL", "info": "info"}.get(
                    check_status, check_status
                )
                lines.append(f"- {check_name}: [{icon}] {detail}")

        lines.append("")

    if rel_map:
        lines.append("## Relationship Map")
        lines.append("")
        parent = rel_map.get("parent")
        if parent:
            ptype = parent.get("type", "?")
            psum = parent.get("summary", "")
            lines.append(f"- **Parent:** {parent['key']} ({ptype}: {psum})")

        children = rel_map.get("children", [])
        if children:
            lines.append("- **Children:**")
            for child in children:
                pr_info = f" — PR: {child['pr']}" if child.get("pr") else ""
                ctype = child.get("type", "?")
                csum = child.get("summary", "")
                lines.append(f"  - {child['key']} ({ctype}: {csum}){pr_info}")
                for gc in child.get("children", []):
                    gc_pr = f" — PR: {gc['pr']}" if gc.get("pr") else ""
                    gtype = gc.get("type", "?")
                    gsum = gc.get("summary", "")
                    lines.append(f"    - {gc['key']} ({gtype}: {gsum}){gc_pr}")

        siblings = rel_map.get("siblings", [])
        if siblings:
            lines.append("- **Siblings:**")
            for sib in siblings:
                lines.append(f"  - {sib['key']} ({sib.get('type', '?')}: {sib.get('summary', '')})")

        lines.append("")

    failing_dims = [
        (dim_labels.get(k, k), v)
        for k, v in dims.items()
        if v and v.get("status") in ("fail", "warn")
    ]
    if failing_dims:
        lines.append("## Recommendations")
        lines.append("")
        for label, dim in failing_dims:
            if dim.get("status") == "fail":
                lines.append(f"- **{label}** — must be addressed before starting the docs workflow")
            else:
                lines.append(f"- **{label}** — consider addressing for better workflow results")
        lines.append("")

    return "\n".join(lines)


def write_markdown_reports(result: dict, output_dir: str) -> None:
    """Write per-ticket markdown reports to the output directory."""
    os.makedirs(output_dir, exist_ok=True)

    if "tickets" in result:
        tickets = result["tickets"]
    else:
        tickets = [result]

    for ticket in tickets:
        if ticket.get("error"):
            continue
        key = ticket.get("ticket", "unknown")
        if not _SAFE_JIRA_KEY.match(key):
            continue
        report = format_markdown_report(ticket)
        path = os.path.join(output_dir, f"{key}-readiness.md")
        with open(path, "w") as f:
            f.write(report)


if __name__ == "__main__":
    sys.exit(main())

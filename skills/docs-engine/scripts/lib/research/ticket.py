#!/usr/bin/env python3
"""The boundary between docs-orc and Jira, through the `acli` CLI."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field

# Everything, because a URL can sit in a custom field, a remote-link summary,
# an environment field or a description, and which one differs per project.
# Measured across three tickets: one carried its repositories in `comment` and
# the others carried none. A fixed subset means finding that out per project.
FIELDS = "*all"
# What a requirements pass reads as prose. Everything else in a work item is
# workflow metadata, and sending 150 fields to a model spends a context window
# on nothing.
READABLE = (
    "summary",
    "description",
    "issuetype",
    "status",
    "labels",
    "components",
    "priority",
    "comment",
    "issuelinks",
)

# ADF nodes that end a line when the walk leaves them.
BLOCKS = {
    "paragraph",
    "heading",
    "listItem",
    "codeBlock",
    "blockquote",
    "rule",
    "tableRow",
    "blockCard",
}
# A cell needs a separator or a row reads as one run-on word.
CELLS = {"tableCell", "tableHeader"}


# A ticket names its code in prose, not in a field. A real AIPCC ticket
# carried twenty-one URLs and an empty `issuelinks`, so the repositories are
# found by reading the description and the comments.
URL = re.compile(r"https?://[^\s\"'<>\)\]}]+")
# A forge URL is usually a view of a repository rather than the repository
# itself: a merge request, a file, a release. Everything left of the view is
# the repo. Each rule below keys on the host's structure, because enumerating
# the view names misses the next one anyone invents.

# Everything after GitLab's `/-/` is a view. That is what the marker is for,
# and it is the only thing to key on, because nested groups mean a project
# path can be any depth.
GITLAB_VIEW = re.compile(r"^(?P<repo>https?://[^\s]+?)/-/.+$")

# A github.com repository is always `owner/name`, and anything past it is a
# view. No enumeration to fall behind.
GITHUB_REPO = re.compile(r"^(?P<repo>https?://github\.com/[^/\s]+/[^/\s]+)(?:/.*)?$")

# github.com paths whose first segment is a site page rather than an owner.
GITHUB_RESERVED = frozenset(
    {
        "about",
        "apps",
        "codespaces",
        "collections",
        "enterprise",
        "explore",
        "features",
        "join",
        "login",
        "marketplace",
        "new",
        "notifications",
        "orgs",
        "pricing",
        "search",
        "settings",
        "sponsors",
        "topics",
        "users",
    }
)

# A self-hosted GitLab predating `/-/` has neither marker, so those keep an
# enumerated list. The trailing path is optional: `/releases` is as much a
# view as `/releases/tag/v1`, and requiring the slash is what let the bare
# forms through.
FORGE_VIEW = re.compile(
    r"^(?P<repo>https?://[^\s]+?)/(?:actions|activity|blame|blob|branches|commit|commits"
    r"|compare|discussions|forks|issues|merge_requests|milestones|network|pipelines|pull"
    r"|pulls|raw|releases|stargazers|tags|tree|wiki)(?:/.*)?$"
)
# Hosts worth cloning from. A link to a bug tracker or a docs page is not code.
FORGES = ("gitlab.com", "github.com", "gitlab.cee.redhat.com", "gitlab.consulting.redhat.com")


class TicketError(RuntimeError):
    """`acli` could not run, or ran and could not answer."""


@dataclass(frozen=True)
class Link:
    """A ticket this one points at."""

    key: str
    summary: str
    kind: str = ""
    status: str = ""
    direction: str = "outward"


@dataclass(frozen=True)
class Ticket:
    key: str
    summary: str
    description: str = ""
    kind: str = ""
    status: str = ""
    priority: str = ""
    labels: list = field(default_factory=list)
    urls: list = field(default_factory=list)
    components: list = field(default_factory=list)
    comments: list = field(default_factory=list)
    fix_versions: list = field(default_factory=list)
    links: list = field(default_factory=list)


def flatten(node):
    """Atlassian Document Format as plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(flatten(child) for child in node)
    if not isinstance(node, dict):
        return ""

    kind = node.get("type")
    attrs = node.get("attrs") or {}
    if kind == "text":
        text = node.get("text", "")
        # A link's target lives in a mark, not in the text. Dropping it loses
        # the repositories a ticket points at: a real work item carried
        # twenty-one URLs, every one of them in a mark or a card, and none in
        # `issuelinks`.
        for mark in node.get("marks") or []:
            href = ((mark.get("attrs") or {}).get("href") or "").strip()
            if mark.get("type") == "link" and href and href != text:
                return f"{text} ({href})"
        return text
    if kind == "hardBreak":
        return "\n"
    if kind == "mention":
        return attrs.get("text", "")
    if kind in ("inlineCard", "blockCard", "embedCard"):
        # A card is a URL with no text of its own.
        return (attrs.get("url") or attrs.get("href") or "").strip()
    if kind == "status":
        return attrs.get("text", "")
    if kind == "date":
        return attrs.get("timestamp", "")
    if kind == "emoji":
        return attrs.get("shortName", "")

    inner = flatten(node.get("content"))
    if kind == "listItem":
        inner = f"- {inner.strip()}"
    if kind in CELLS:
        return inner.strip() + " | "
    return inner + "\n" if kind in BLOCKS else inner


def _text(value):
    """A field that may be ADF, a plain string, or absent."""
    if isinstance(value, dict):
        return flatten(value).strip()
    return (value or "").strip() if isinstance(value, str) else ""


def _run(argv, timeout):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise TicketError("the acli binary is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise TicketError(f"acli timed out after {timeout}s") from exc

    joined = f"{done.stdout}\n{done.stderr}"
    if "unauthorized" in joined or "auth login" in joined:
        raise TicketError("acli is not authenticated; run `acli jira auth login --web`")
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise TicketError((detail[0] if detail else f"acli exited {done.returncode}")[:300])
    if not done.stdout.strip():
        raise TicketError("acli returned nothing")
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise TicketError(f"acli produced output that is not JSON: {done.stdout[:200]}") from exc


def parse(payload, key=""):
    """One work item, flattened to the fields a requirements pass reads."""
    fields = payload.get("fields") or {}
    if not fields:
        raise TicketError(f"no fields on work item {key or payload.get('key', '')}")
    comments = (fields.get("comment") or {}).get("comments") or []
    # A documentation ticket is often a thin wrapper: an empty description, one
    # comment, and a `Document` link to the feature that carries the substance.
    # Measured on RHOAIENG-71437, whose own description is empty and whose two
    # links are the feature being documented and the prior work it incorporates.
    links = []
    for entry in fields.get("issuelinks") or []:
        other = entry.get("outwardIssue") or entry.get("inwardIssue") or {}
        if not other.get("key"):
            continue
        other_fields = other.get("fields") or {}
        links.append(
            Link(
                key=other["key"],
                summary=_text(other_fields.get("summary")),
                kind=((entry.get("type") or {}).get("name") or ""),
                status=((other_fields.get("status") or {}).get("name") or ""),
                direction="outward" if entry.get("outwardIssue") else "inward",
            )
        )
    return Ticket(
        key=payload.get("key") or key,
        summary=_text(fields.get("summary")),
        description=_text(fields.get("description")),
        kind=((fields.get("issuetype") or {}).get("name") or ""),
        status=((fields.get("status") or {}).get("name") or ""),
        priority=((fields.get("priority") or {}).get("name") or ""),
        links=links,
        urls=urls_in(payload),
        labels=list(fields.get("labels") or []),
        components=[c.get("name", "") for c in (fields.get("components") or []) if c.get("name")],
        comments=[text for text in (_text(c.get("body")) for c in comments) if text],
        # Workflow metadata rather than prose, so it stays out of READABLE and
        # never reaches a model. It decides which documentation set the chain
        # targets, which is a decision for the run rather than for the writer.
        fix_versions=[
            v.get("name", "") for v in (fields.get("fixVersions") or []) if v.get("name")
        ],
    )


def urls_in(payload):
    """Every URL anywhere in a work item, in the order encountered."""
    found = []
    seen = set()

    def walk(node):
        if isinstance(node, str):
            for match in URL.findall(node):
                cleaned = match.rstrip(".,;)]}\"'")
                if cleaned not in seen:
                    seen.add(cleaned)
                    found.append(cleaned)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def _clean(url):
    """A URL without the trailing slash or the `.git` a clone URL carries."""
    url = url.rstrip("/")
    return url[:-4] if url.endswith(".git") else url


def _is_repository(url):
    """Two path segments, and not one of github.com's own pages."""
    tail = url.split("://", 1)[-1].split("/")[1:]
    if len(tail) < 2:
        return False
    host = url.split("://", 1)[-1].split("/")[0]
    return not (host == "github.com" and tail[0] in GITHUB_RESERVED)


def repo_url(url):
    """The repository a forge URL belongs to, or None if it is not one."""
    url = url.rstrip(".,;)]}\"'")
    if not any(host in url for host in FORGES):
        return None
    match = GITLAB_VIEW.match(url) or GITHUB_REPO.match(url) or FORGE_VIEW.match(url)
    if match:
        candidate = _clean(match.group("repo"))
        # A project genuinely called `releases` would otherwise be cut back to
        # its group, so a strip that leaves no repository behind is discarded
        # and the whole URL is reconsidered below.
        if _is_repository(candidate):
            return candidate
    cleaned = _clean(url)
    return cleaned if _is_repository(cleaned) else None


def repositories(t, *others):
    """Every repository these tickets point at, in the order they mention them."""
    seen = []
    for one in (t, *others):
        # `urls` was harvested from the whole work item; the prose is a fallback
        # for a Ticket built by hand, as the tests do.
        candidates = one.urls or [
            raw
            for blob in (one.summary, one.description, *one.comments)
            for raw in URL.findall(blob or "")
        ]
        for raw in candidates:
            found = repo_url(raw)
            if found and found not in seen:
                seen.append(found)
    return seen


def fetch(key, timeout=120, fields=FIELDS):
    """One Jira work item by key."""
    if not key or not key.strip():
        raise TicketError("an empty key fetches nothing")
    payload = _run(
        ["acli", "jira", "workitem", "view", key.strip(), "--json", "--fields", fields], timeout
    )
    if not isinstance(payload, dict):
        raise TicketError(f"expected one work item, got {type(payload).__name__}")
    return parse(payload, key.strip())

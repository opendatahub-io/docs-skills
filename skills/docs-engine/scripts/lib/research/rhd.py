#!/usr/bin/env python3
"""The boundary between docs-orc and the `rhd` documentation CLI."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field


class RhdError(RuntimeError):
    """`rhd` could not run, or ran and could not answer."""


class RhdUnavailable(RhdError):  # noqa: N818
    """One URL yields nothing, while `rhd` itself is working.

    A subclass, so a caller that treats every failure alike still catches
    `RhdError` and a loop over several URLs can skip this one and carry on.
    The distinction is what keeps an expired token from reading as "every page
    is missing": one dead link in a ranked list of hits is an ordinary fact
    about that link, and stopping the run over it throws away the pages either
    side of it that were fine.
    """


# `rhd` folds every unfetchable URL into one message: a missing guide, a
# missing product, a knowledge base article and a marketing page all exit 1
# with "Not a valid Red Hat Documentation link (error 2001)". Catalogs list
# cross-product links and searches rank withdrawn pages, so both are ordinary.
_UNAVAILABLE = (
    "error 2001",
    "not a valid red hat documentation link",
    "404",
    "not found",
)


@dataclass(frozen=True)
class Result:
    """One search hit."""

    title: str
    url: str
    abstract: str = ""
    modified: str = ""
    kind: str = ""


@dataclass(frozen=True)
class Page:
    """One fetched document."""

    title: str
    url: str
    content: str
    kind: str = ""
    words: int = field(default=0)


@dataclass(frozen=True)
class Guide:
    """One guide in a product's catalog."""

    name: str
    description: str
    url: str
    category: str = ""


def _run(argv, timeout):
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RhdError("the rhd binary is not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RhdError(f"rhd timed out after {timeout}s") from exc

    if done.returncode != 0:
        # rhd exits non-zero when a search matches nothing, which is an answer
        # rather than a failure. Without this the caller reports the error
        # "[]", which says nothing about what went wrong.
        stripped = done.stdout.strip()
        if stripped in ("[]", "{}"):
            return json.loads(stripped)
        detail = (done.stderr or done.stdout).strip().splitlines()
        first = detail[0] if detail else f"rhd exited {done.returncode}"
        # A Python CLI traceback puts its useful exception on the last line.
        # Reporting only the first line reduces every such failure to the
        # content-free "Traceback (most recent call last):".
        if first.startswith("Traceback") and len(detail) > 1:
            first = f"{first} {detail[-1]}"
        # An expired token fails every call the same way, so say what to do
        # about it rather than relaying the grant error. Checked ahead of the
        # per-URL cases, or a whole run answers "nothing found" and never
        # mentions the token.
        joined = " ".join(detail)
        if "invalid_grant" in joined or "not active" in joined:
            raise RhdError("rhd is not authenticated; run `rhd login`")
        lowered = joined.lower()
        if any(marker in lowered for marker in _UNAVAILABLE):
            raise RhdUnavailable(first[:300])
        raise RhdError(first[:300])

    if not done.stdout.strip():
        raise RhdError("rhd returned nothing")
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError as exc:
        raise RhdError(f"rhd produced output that is not JSON: {done.stdout[:200]}") from exc


# One product publishes under more than one name. Red Hat AI Inference keeps
# some tables in the `red_hat_ai` umbrella set and a long tail under its
# former name. Measured on INFERENG-10745: pinning to the product's own name
# discarded all 24 hits, the page the ticket named among them.
FAMILIES = (frozenset({"red_hat_ai", "red_hat_ai_inference", "red_hat_ai_inference_server"}),)


def family(product):
    """Every documentation product name that publishes for `product`."""
    for group in FAMILIES:
        if product in group:
            return group
    return frozenset({product})


def in_product(url, product, version):
    """Whether a documentation URL belongs to the pinned product and version."""
    if not product:
        return True
    path = url or ""
    prefix = f"/documentation/{product}/"
    if prefix in path:
        if not version:
            return True
        return f"{prefix}{version}/" in path
    # A version number means what it says inside one product name and nowhere
    # else: `red_hat_ai` numbers its releases 3 while Red Hat AI Inference is
    # on 3.5, so holding a sibling to the pinned version would drop every page
    # this widening exists to keep. Membership of the family is what still
    # keeps an unrelated product out.
    return any(f"/documentation/{name}/" in path for name in family(product) if name != product)


def catalog(product, version, timeout=300):
    """Every guide a product publishes at one version."""
    url = f"https://docs.redhat.com/en/documentation/{product}/{version}"
    payload = _run(["rhd", "fetch", url, "--json"], timeout)
    if not isinstance(payload, dict):
        raise RhdError(f"expected one catalog object, got {type(payload).__name__}")
    content = payload.get("content") or ""
    start = content.find("{")
    if start < 0:
        raise RhdError(f"rhd returned no catalog for {product} {version}")
    try:
        decoded, _ = json.JSONDecoder().raw_decode(content, start)
    except json.JSONDecodeError as exc:
        raise RhdError(f"the catalog for {product} {version} is not JSON: {exc}") from exc

    guides = []
    for category, block in (decoded.get("categoryTitles") or {}).items():
        for entry in (block or {}).get("titles") or []:
            if not entry.get("url"):
                continue
            guides.append(
                Guide(
                    name=(entry.get("name") or "").strip(),
                    description=(entry.get("description") or "").strip(),
                    url=entry["url"].strip(),
                    category=category.strip(),
                )
            )
    if not guides:
        raise RhdError(f"the catalog for {product} {version} lists no guides")
    return guides


_MINOR_RELEASE = re.compile(r"^(\d+)\.(\d+)$")


def catalog_at_or_before(product, version, timeout=300):
    """The requested catalog, or the nearest earlier published minor release.

    A ticket can legitimately target the next release before its documentation
    site exists.  The published predecessor is then the only reliable map of
    the content that the new material will update.  Only an unavailable
    catalog triggers this fallback: expired credentials, malformed output, and
    other CLI failures must still stop the run.

    The target must be a ``major.minor`` release to be safely decremented.  A
    nonstandard version is queried as-is and its original error is preserved.
    """
    try:
        return version, catalog(product, version, timeout)
    except RhdUnavailable as exc:
        # Exception-target names are cleared after ``except`` in Python; keep
        # this separately because it is useful if every predecessor is absent.
        requested_error = exc
        match = _MINOR_RELEASE.fullmatch(str(version))
        if not match:
            raise requested_error

    major, minor = (int(part) for part in match.groups())
    for candidate_minor in range(minor - 1, -1, -1):
        candidate = f"{major}.{candidate_minor}"
        try:
            return candidate, catalog(product, candidate, timeout)
        except RhdUnavailable:
            continue
    raise RhdUnavailable(
        f"no published catalog for {product} at or before {version}; {requested_error}"
    )


def search(query, limit=5, timeout=120, product=None, version=None):
    """Search results for `query`, newest-first as `rhd` orders them."""
    if not query or not query.strip():
        raise RhdError("an empty query searches for nothing")
    payload = _run(["rhd", "search", query, "--json", "--limit", str(limit)], timeout)
    if not isinstance(payload, list):
        raise RhdError(f"expected a list of results, got {type(payload).__name__}")
    return [
        Result(
            title=row.get("title", "").replace("\n", " ").strip(),
            url=row.get("url", "").strip(),
            abstract=row.get("abstract", "").replace("\n", " ").strip(),
            modified=row.get("lastModifiedDate", ""),
            kind=row.get("documentKind", ""),
        )
        for row in payload
        if row.get("url") and in_product(row["url"], product, version)
    ]


def fetch(url, timeout=300):
    """One page, as Markdown."""
    if not url or not url.strip():
        raise RhdError("an empty url fetches nothing")
    payload = _run(["rhd", "fetch", url, "--json"], timeout)
    if not isinstance(payload, dict):
        raise RhdError(f"expected one page object, got {type(payload).__name__}")
    content = payload.get("content") or ""
    if not content.strip():
        raise RhdError(f"rhd returned an empty page for {url}")
    return Page(
        title=payload.get("title", "").replace("\n", " ").strip(),
        url=payload.get("url", url).strip(),
        content=content,
        kind=payload.get("type", ""),
        words=len(content.split()),
    )

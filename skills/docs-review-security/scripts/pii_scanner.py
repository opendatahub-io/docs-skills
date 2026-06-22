#!/usr/bin/env python3
"""Scan documentation files for sensitive data before publication.

Detects real IP addresses, MAC addresses, URLs/domains, email addresses,
credentials, and internal hostnames. Patterns aligned with
vale-at-red-hat#851 and case_search.py.

Zero external dependencies — Python 3.9+ standard library only.

Usage:
  pii_scanner.py scan <path> [<path>...]
  pii_scanner.py scan --docs-dir <dir> [--scan-dirs modules,topics] [--file-types .adoc,.md]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# ── MAC address detection ─────────────────────────────────────────────────────

_MAC_RE = re.compile(
    r"[a-fA-F\d]{2}:[a-fA-F\d]{2}:[a-fA-F\d]{2}:[a-fA-F\d]{2}:[a-fA-F\d]{2}:[a-fA-F\d]{2}"
    r"|[a-fA-F\d]{2}-[a-fA-F\d]{2}-[a-fA-F\d]{2}-[a-fA-F\d]{2}-[a-fA-F\d]{2}-[a-fA-F\d]{2}"
    r"|[a-fA-F\d]{2}\.[a-fA-F\d]{2}\.[a-fA-F\d]{2}\.[a-fA-F\d]{2}\.[a-fA-F\d]{2}\.[a-fA-F\d]{2}"
)

_ALLOWED_MACS = {
    "00:00:00:00:00:aa",
    "00:00:00:00:00:bb",
    "00-00-00-00-00-aa",
    "00-00-00-00-00-bb",
    "00.00.00.00.00.aa",
    "00.00.00.00.00.bb",
}

# ── IP address detection ─────────────────────────────────────────────────────

_IP_RE = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b")

# RFC 5737 documentation addresses
_RFC5737_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.")

# First octets that are always allowed
_ALLOWED_FIRST_OCTETS = {"127", "0", "224", "255"}

# RFC 1918 172.16-31 range regex
_PRIVATE_172_RE = re.compile(r"^172\.(1[6-9]|2[0-9]|3[01])\.")


def _is_ip_allowed(ip):
    """Check if an IP address is allowed (private, doc, loopback, etc.)."""
    # RFC 5737 documentation addresses
    for prefix in _RFC5737_PREFIXES:
        if ip.startswith(prefix):
            return True
    # First-octet checks (loopback, zero, multicast, broadcast)
    first_octet = ip.split(".")[0]
    if first_octet in _ALLOWED_FIRST_OCTETS:
        return True
    # RFC 1918 private ranges
    if ip.startswith("10."):
        return True
    if ip.startswith("192.168."):
        return True
    if _PRIVATE_172_RE.match(ip):
        return True
    return False


# ── URL/domain detection ──────────────────────────────────────────────────────

_URL_RE = re.compile(r"\b(?:https?://)?(?:www\.)?[^\s]+\.[a-zA-Z]{2,}\b")

_ALLOWED_URLS_EXACT = {
    "redhat.com",
    "hostname",
    "example.com",
    "example.net",
    "example.org",
    "access.redhat.com",
    "server.log",
    "www.redhat.com",
    "bugzilla.redhat.com",
    "config.get",
    "www.example.com",
    "agent.log",
    "rhqctl.log",
    "rhq-storage.log",
    "rhq-client.log",
    "http://access.redhat.com",
    "https://access.redhat.com",
    "https://www.redhat.com",
    "http://www.redhat.com",
    "http://www.example.com",
    "https://www.example.com",
}

_ALLOWED_URL_PREFIXES = (
    "http://access.redhat.com",
    "https://access.redhat.com",
    "https://www.redhat.com",
    "http://www.redhat.com",
    "http://www.example.com",
    "https://www.example.com",
)

_ALLOWED_DOMAIN_SUFFIXES = (".redhat.com", ".redhat.io", ".openshift.com")

_ALLOWED_FILE_EXTENSIONS = {
    ".log",
    ".img",
    ".out",
    ".bin",
    ".cfg",
    ".png",
    ".gif",
    ".jpg",
    ".rhq",
    ".jar",
    ".msc",
    ".txt",
    ".pdf",
    ".tar",
    ".gz",
    ".java",
    ".yml",
    ".xml",
    ".csv",
    ".py",
    ".zip",
    ".jpeg",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pps",
    ".odt",
    ".ods",
    ".odp",
    ".tgz",
    ".bz",
    ".cpp",
    ".bz2",
    ".sh",
    ".stp",
    ".rtf",
    ".sql",
    # Source code extensions commonly referenced in Red Hat docs
    ".go",
    ".rs",
    ".rb",
    ".ts",
    ".js",
    ".tf",
    ".md",
    ".adoc",
    ".json",
    ".toml",
    ".ini",
    ".conf",
    ".yaml",
    ".html",
    ".css",
    ".scss",
    ".jsx",
    ".tsx",
    ".vue",
    ".svelte",
    ".rpm",
    ".deb",
    ".iso",
    ".svg",
    ".wasm",
}


def _is_url_allowed(url):
    """Check if a URL/domain is in the allowlist."""
    if url in _ALLOWED_URLS_EXACT:
        return True
    for prefix in _ALLOWED_URL_PREFIXES:
        if url.startswith(prefix):
            return True
    for suffix in _ALLOWED_DOMAIN_SUFFIXES:
        if url.endswith(suffix):
            return True
    # node*.example.com
    bare = re.sub(r"^https?://", "", url)
    if bare.startswith("node") and bare.endswith(".example.com"):
        return True
    for ext in _ALLOWED_FILE_EXTENSIONS:
        if url.endswith(ext):
            return True
    return False


# ── Email detection ───────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")

_ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.net",
    "example.org",
    "redhat.com",
}


def _is_email_allowed(email):
    """Check if an email domain is in the allowlist."""
    domain = email.split("@", 1)[1].lower()
    return domain in _ALLOWED_EMAIL_DOMAINS


# ── Internal hostname detection ───────────────────────────────────────────────

_INTERNAL_HOSTNAME_RE = re.compile(
    r"\b[a-zA-Z0-9][\w.-]*\."
    r"(?:internal|corp|local)\b"
    r"|"
    r"\blab\.eng\.[a-zA-Z0-9][\w.-]*\.redhat\.com\b"
    r"|"
    r"\b[a-zA-Z0-9][\w.-]*\.eng\.redhat\.com\b"
)

# ── Credential detection ─────────────────────────────────────────────────────

_PASSWORD_RE = re.compile(r"(?:password|passwd)\s*[:=]\s*(\S+)", re.IGNORECASE)
_SECRET_RE = re.compile(r"secret\s*[:=]\s*(\S+)", re.IGNORECASE)
_TOKEN_RE = re.compile(r"token\s*[:=]\s*([A-Za-z0-9_\-]{20,})", re.IGNORECASE)
_BEARER_RE = re.compile(r"Bearer\s+([A-Za-z0-9_\-.]{20,})")
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----")

# Values that are clearly placeholders (case-insensitive check)
_PLACEHOLDER_VALUES_LOWER = {
    "changeme",
    "password",
    "my-password",
    "my_password",
    "your-password",
    "your_password",
    "your-password-here",
    "null",
    "none",
    "replace_me",
    "xxx",
    "example",
    "secret",
    "my-secret",
    "your-secret",
}

# Patterns that indicate a placeholder (checked as prefixes/patterns)
_PLACEHOLDER_PATTERNS = (
    "<",  # <password>, <your-password>, etc.
    "{",  # {my-password} AsciiDoc attribute
    "$",  # $PASSWORD env var
    '"',  # "" empty quoted
    "'",  # '' empty quoted
    "*",  # **** redacted
)


def _is_credential_placeholder(value):
    """Check if a credential value is a known placeholder."""
    if not value:
        return True
    # Check prefix patterns
    for pattern in _PLACEHOLDER_PATTERNS:
        if value.startswith(pattern):
            return True
    # Check known placeholder words (case-insensitive)
    if value.lower().rstrip(".,;:!?") in _PLACEHOLDER_VALUES_LOWER:
        return True
    return False


# ── Comment detection ─────────────────────────────────────────────────────────


def _is_comment_line(line, filename):
    """Check if a line is a single-line comment based on file type."""
    stripped = line.lstrip()
    ext = Path(filename).suffix.lower() if filename else ""
    if ext in (".adoc",):
        return stripped.startswith("//") and not stripped.startswith("////")
    if ext in (".md", ".dita", ".ditamap", ".xml", ".html"):
        return stripped.startswith("<!--") and "-->" in stripped
    return False


def _track_block_comment(line, in_block, block_type, filename):
    """Track multi-line block comment state.

    Returns (skip_line, in_block, block_type).
    """
    stripped = line.lstrip()
    ext = Path(filename).suffix.lower() if filename else ""

    if not in_block:
        if ext == ".adoc" and stripped.startswith("////"):
            return True, True, "adoc"
        if ext in (".md", ".dita", ".ditamap", ".xml", ".html"):
            if "<!--" in stripped and "-->" not in stripped:
                return True, True, "html"
        return False, False, None

    # Inside a block — check for closing delimiter
    if block_type == "adoc" and stripped.startswith("////"):
        return True, False, None
    if block_type == "html" and "-->" in stripped:
        return True, False, None
    return True, True, block_type


# ── Core scanning ─────────────────────────────────────────────────────────────


def scan_line(line, line_num, filename):
    """Scan a single line for sensitive data patterns.

    Returns a list of finding dicts.
    """
    if _is_comment_line(line, filename):
        return []

    findings = []

    # 1. MAC addresses (before IPs — dot-separated MACs overlap with IP regex)
    for match in _MAC_RE.finditer(line):
        mac = match.group(0)
        if mac.lower() not in _ALLOWED_MACS:
            findings.append(
                {
                    "file": filename,
                    "line": line_num,
                    "category": "mac",
                    "matched": mac,
                    "context": line.rstrip(),
                    "severity": "warning",
                    "suggestion": "Use placeholder MAC (00:00:00:00:00:aa or 00:00:00:00:00:bb)",
                }
            )

    # 2. IP addresses
    for match in _IP_RE.finditer(line):
        ip = match.group(1)
        if not _is_ip_allowed(ip):
            findings.append(
                {
                    "file": filename,
                    "line": line_num,
                    "category": "ip",
                    "matched": ip,
                    "context": line.rstrip(),
                    "severity": "warning",
                    "suggestion": (
                        "Use RFC 5737 documentation address "
                        "(192.0.2.x, 198.51.100.x, or 203.0.113.x)"
                    ),
                }
            )

    # 3. Internal hostnames (before general URL check)
    for match in _INTERNAL_HOSTNAME_RE.finditer(line):
        hostname = match.group(0)
        findings.append(
            {
                "file": filename,
                "line": line_num,
                "category": "internal_hostname",
                "matched": hostname,
                "context": line.rstrip(),
                "severity": "warning",
                "suggestion": "Use example.com hostname (e.g., node1.example.com)",
            }
        )

    # 4. URLs/domains
    for match in _URL_RE.finditer(line):
        url = match.group(0)
        if not _is_url_allowed(url):
            # Skip if already caught as internal hostname
            if any(f["matched"] in url for f in findings if f["category"] == "internal_hostname"):
                continue
            findings.append(
                {
                    "file": filename,
                    "line": line_num,
                    "category": "url",
                    "matched": url,
                    "context": line.rstrip(),
                    "severity": "warning",
                    "suggestion": "Use example.com or a *.redhat.com domain",
                }
            )

    # 5. Email addresses
    for match in _EMAIL_RE.finditer(line):
        email = match.group(0)
        if not _is_email_allowed(email):
            findings.append(
                {
                    "file": filename,
                    "line": line_num,
                    "category": "email",
                    "matched": email,
                    "context": line.rstrip(),
                    "severity": "warning",
                    "suggestion": "Use user@example.com (RFC 2606 reserved domain)",
                }
            )

    # 6. Credentials
    for pattern, label in [(_PASSWORD_RE, "password"), (_SECRET_RE, "secret")]:
        m = pattern.search(line)
        if m and not _is_credential_placeholder(m.group(1)):
            findings.append(
                {
                    "file": filename,
                    "line": line_num,
                    "category": "credential",
                    "matched": f"{label}: {m.group(1)}",
                    "context": line.rstrip(),
                    "severity": "critical",
                    "suggestion": f"Use a placeholder value (e.g., <{label}>)",
                }
            )

    m = _TOKEN_RE.search(line)
    if m and not _is_credential_placeholder(m.group(1)):
        findings.append(
            {
                "file": filename,
                "line": line_num,
                "category": "credential",
                "matched": f"token: {m.group(1)[:20]}...",
                "context": line.rstrip(),
                "severity": "critical",
                "suggestion": "Use a placeholder token value",
            }
        )

    m = _BEARER_RE.search(line)
    if m and not _is_credential_placeholder(m.group(1)):
        findings.append(
            {
                "file": filename,
                "line": line_num,
                "category": "credential",
                "matched": f"Bearer {m.group(1)[:20]}...",
                "context": line.rstrip(),
                "severity": "critical",
                "suggestion": "Use a placeholder Bearer token",
            }
        )

    if _PRIVATE_KEY_RE.search(line):
        findings.append(
            {
                "file": filename,
                "line": line_num,
                "category": "credential",
                "matched": "PRIVATE KEY header",
                "context": line.rstrip(),
                "severity": "critical",
                "suggestion": "Remove private key material from documentation",
            }
        )

    return findings


def scan_file(filepath):
    """Scan a file for sensitive data. Returns list of findings."""
    try:
        text = Path(filepath).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [
            {
                "file": filepath,
                "line": 0,
                "category": "scan_error",
                "matched": "file unreadable",
                "context": "",
                "severity": "warning",
                "suggestion": "File could not be read — verify path and permissions",
            }
        ]

    all_findings = []
    if "�" in text:
        all_findings.append(
            {
                "file": filepath,
                "line": 0,
                "category": "scan_warning",
                "matched": "encoding issues",
                "context": "",
                "severity": "warning",
                "suggestion": "File contains non-UTF-8 bytes — scan may miss content",
            }
        )
    in_block = False
    block_type = None
    for i, line in enumerate(text.splitlines(), start=1):
        skip, in_block, block_type = _track_block_comment(
            line, in_block, block_type, filepath
        )
        if skip:
            continue
        all_findings.extend(scan_line(line, i, filepath))
    return all_findings


# ── File collection ───────────────────────────────────────────────────────────


def collect_files(docs_dir, scan_dirs, file_types):
    """Collect files matching extensions under scan directories."""
    root = Path(docs_dir)
    files = []
    for scan_dir in scan_dirs:
        d = root / scan_dir
        if not d.is_dir():
            continue
        for ext in file_types:
            files.extend(d.rglob(f"*{ext}"))
    return sorted(files)


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_scan(files):
    """Scan files and return structured results."""
    all_findings = []
    files_with_findings = set()

    for f in files:
        findings = scan_file(str(f))
        if findings:
            files_with_findings.add(str(f))
            all_findings.extend(findings)

    category_counts = Counter(f["category"] for f in all_findings)
    severity_counts = Counter(f["severity"] for f in all_findings)

    return {
        "command": "scan",
        "summary": {
            "files_scanned": len(files),
            "files_with_findings": len(files_with_findings),
            "total_findings": len(all_findings),
            "by_category": dict(category_counts),
            "by_severity": dict(severity_counts),
        },
        "findings": all_findings,
    }


def run(args):
    """Execute the scan command and return exit code."""
    # Collect files from paths or docs-dir
    if args.paths:
        files = [Path(p) for p in args.paths if Path(p).is_file()]
    elif args.docs_dir:
        docs_dir = args.docs_dir
        if not Path(docs_dir).is_dir():
            print(json.dumps({"error": f"Not a directory: {docs_dir}"}), file=sys.stderr)
            sys.exit(1)
        raw_dirs = args.scan_dirs
        scan_dirs = raw_dirs if isinstance(raw_dirs, list) else raw_dirs.split(",")
        raw_types = args.file_types
        file_types = raw_types if isinstance(raw_types, list) else raw_types.split(",")
        files = collect_files(docs_dir, scan_dirs, file_types)
    else:
        files = []

    result = cmd_scan(files)
    print(json.dumps(result, indent=2))

    # Exit codes: 0 = clean, 1 = warnings, 2 = critical
    if result["summary"]["by_severity"].get("critical", 0) > 0:
        return 2
    if result["summary"]["total_findings"] > 0:
        return 1
    return 0


def main():
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Scan documentation files for sensitive data "
        "(PII, credentials, internal hostnames)."
    )
    sub = parser.add_subparsers(dest="command")

    scan_parser = sub.add_parser("scan", help="Scan files for sensitive data")
    scan_parser.add_argument("paths", nargs="*", help="File paths to scan")
    scan_parser.add_argument("--docs-dir", help="Documentation root directory")
    scan_parser.add_argument(
        "--scan-dirs",
        default="modules,topics",
        help="Comma-separated subdirectories to scan (default: modules,topics)",
    )
    scan_parser.add_argument(
        "--file-types",
        default=".adoc,.md,.dita,.ditamap",
        help="Comma-separated file extensions (default: .adoc,.md,.dita,.ditamap)",
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    sys.exit(run(args))


if __name__ == "__main__":
    main()

---
context: fork
name: docs-review-security
description: >-
  Scan documentation for sensitive data before publication — real IP addresses,
  credentials, internal hostnames, email addresses, and MAC addresses. Use this
  skill when asked to check for PII, security issues, customer-sensitive data,
  or before publishing documentation. Runs a deterministic regex scanner first,
  then applies agent judgment for patterns regex cannot catch.
---

# Security and PII review skill

Scan documentation for sensitive data that must not appear in published content:
real IP addresses, credentials, internal hostnames, customer-identifying
information, and other PII.

This skill has two layers:

1. **Deterministic scan** — run `pii_scanner.py` for regex-based detection
2. **Agent analysis** — review for patterns regex cannot catch

## Layer 1: Run the scanner

Run the PII scanner against the target files:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/pii_scanner.py scan <file1> <file2> ...
```

Or for a docs directory:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/pii_scanner.py scan --docs-dir <path> [--scan-dirs modules,topics] [--file-types .adoc,.md,.dita]
```

Parse the JSON output. If findings exist, include them in the report grouped
by severity (critical first, then warning).

## Layer 2: Agent analysis checklist

After the scanner runs, review the content for patterns that regex cannot
reliably detect:

### Customer-sensitive data in YAML/JSON examples

- [ ] CR `metadata.name` fields use generic names (`example-<kind>`) not customer-specific names
- [ ] CR `metadata.namespace` fields use generic namespaces, not customer project names
- [ ] `resourceName`, `hostname`, and similar fields do not contain real customer identifiers
- [ ] No customer application names appear — use "the custom application" or a generic name

### Internal references

- [ ] No internal Jira project keys or ticket numbers that expose internal tooling
- [ ] No internal wiki, Confluence, or Google Doc URLs
- [ ] No internal Slack channel names or references
- [ ] No references to internal build systems, CI/CD pipelines, or staging environments

### Sensitive patterns in prose

- [ ] No real person names associated with accounts, cases, or examples
- [ ] No real organization or company names in examples (use "Example Corp" or similar)
- [ ] No internal Red Hat team names or org chart references in customer-facing content
- [ ] No case numbers, account numbers, or subscription IDs from real customers

### LUN WWIDs (if applicable)

- [ ] World Wide IDs use the generic pattern: `3600000000000000000aaaaaaaaaaaaaa`
- [ ] If differentiation is needed, vary the end characters: `...bbbbbbbbbbbbbb`

## How to report

For each finding, report:
- **File** and **line number**
- **Category** (ip, email, credential, url, mac, internal_hostname, or agent-detected)
- **Severity**: `critical` (credentials, private keys) or `warning` (IPs, emails, URLs)
- **Suggestion**: the safe replacement (RFC 5737 IP, `@example.com` email, etc.)

## Example invocations

- "Scan this file for PII and sensitive data"
- "Run a security review on the installation guide"
- "Check these docs for credentials and internal hostnames before we publish"

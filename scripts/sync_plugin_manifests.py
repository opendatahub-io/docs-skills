#!/usr/bin/env python3
"""Generate the Claude Code and Codex plugin manifests from shared metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PLUGIN_NAME = "docs-skills"
PLUGIN_VERSION = "0.4.0"
MARKETPLACE_NAME = "opendatahub-docs"
DESCRIPTION = (
    "Documentation review, writing, and workflow tools for AsciiDoc and Markdown documentation"
)
REPOSITORY_URL = "https://github.com/opendatahub-io/docs-skills"


def manifests() -> dict[Path, dict[str, Any]]:
    """Return every generated manifest, keyed by repository-relative path."""
    return {
        Path(".claude-plugin/plugin.json"): {
            "name": PLUGIN_NAME,
            "version": PLUGIN_VERSION,
            "description": DESCRIPTION,
            "author": {"name": "opendatahub-io"},
            "license": "Apache-2.0",
            "homepage": REPOSITORY_URL,
        },
        Path(".claude-plugin/marketplace.json"): {
            "name": MARKETPLACE_NAME,
            "owner": {"name": "opendatahub-io"},
            "description": DESCRIPTION,
            "plugins": [
                {
                    "name": PLUGIN_NAME,
                    "source": ".",
                    "description": DESCRIPTION,
                }
            ],
        },
        Path(".codex-plugin/plugin.json"): {
            "name": PLUGIN_NAME,
            "version": PLUGIN_VERSION,
            "description": DESCRIPTION,
            "author": {"name": "opendatahub-io"},
            "homepage": REPOSITORY_URL,
            "repository": REPOSITORY_URL,
            "license": "Apache-2.0",
            "keywords": [
                "documentation",
                "writing",
                "review",
                "asciidoc",
                "markdown",
            ],
            "skills": "./skills/",
            "interface": {
                "displayName": "Documentation Skills",
                "shortDescription": "Plan, write, and review technical documentation",
                "longDescription": (
                    "Reusable documentation workflows for requirements analysis, planning, "
                    "writing, code-grounded review, and style-guide compliance."
                ),
                "developerName": "opendatahub-io",
                "category": "Productivity",
                "capabilities": ["Interactive", "Read", "Write"],
                "websiteURL": REPOSITORY_URL,
                "defaultPrompt": [
                    "Plan documentation for this change.",
                    "Review these docs for technical accuracy.",
                    "Run the documentation workflow for this ticket.",
                ],
            },
        },
        Path(".agents/plugins/marketplace.json"): {
            "name": MARKETPLACE_NAME,
            "interface": {"displayName": "OpenDataHub Documentation"},
            "plugins": [
                {
                    "name": PLUGIN_NAME,
                    "source": {"source": "local", "path": "."},
                    "policy": {
                        "installation": "AVAILABLE",
                        "authentication": "ON_INSTALL",
                    },
                    "category": "Productivity",
                }
            ],
        },
    }


def render(payload: dict[str, Any]) -> str:
    return f"{json.dumps(payload, indent=2)}\n"


def sync(repo_root: Path, *, check: bool) -> list[Path]:
    """Write manifests, or return paths that differ when check mode is enabled."""
    changed: list[Path] = []
    for relative_path, payload in manifests().items():
        path = repo_root / relative_path
        expected = render(payload)
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == expected:
            continue
        changed.append(relative_path)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when generated manifests are stale.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    changed = sync(repo_root, check=args.check)
    if args.check and changed:
        paths = ", ".join(str(path) for path in changed)
        raise SystemExit(f"Plugin manifests are stale: {paths}")
    if changed:
        print("Updated plugin manifests: " + ", ".join(str(path) for path in changed))
    else:
        print("Plugin manifests are current.")


if __name__ == "__main__":
    main()

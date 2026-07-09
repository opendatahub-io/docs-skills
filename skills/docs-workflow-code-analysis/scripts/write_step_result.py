#!/usr/bin/env python3
"""Write the code-analysis step-result.json sidecar.

Reads the learn-code analysis directory to derive module/relationship/language
metrics deterministically, so the orchestrator does not need to parse them and
the sidecar cannot drift from its schema.

Usage:
  write_step_result.py --ticket <id> --repo <path> \
      --analysis-path <learn-code base> --sidecar <path>
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _module_count(analysis_path: Path) -> int:
    """registry.json is a JSON array; the count is its length."""
    registry = analysis_path / "module-registry" / "registry.json"
    try:
        data = json.loads(registry.read_text())
    except (json.JSONDecodeError, OSError):
        return 0
    return len(data) if isinstance(data, list) else 0


def _relationship_count(analysis_path: Path) -> int:
    """Count the .json files in relationships/."""
    rel_dir = analysis_path / "relationships"
    if not rel_dir.is_dir():
        return 0
    return sum(1 for _ in rel_dir.glob("*.json"))


def _languages_detected(analysis_path: Path) -> list[str]:
    """Use language_counts keys from detection.json, else primary_language."""
    detection = analysis_path / "detection" / "detection.json"
    try:
        data = json.loads(detection.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict):
        return []
    counts = data.get("language_counts")
    if isinstance(counts, dict) and counts:
        return list(counts.keys())
    primary = data.get("primary_language")
    return [primary] if primary else []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", required=True)
    parser.add_argument("--repo", required=True, help="Path to the analyzed source repo")
    parser.add_argument("--analysis-path", required=True, help="learn-code analysis base directory")
    parser.add_argument("--sidecar", required=True, help="Path to write step-result.json")
    args = parser.parse_args()

    analysis_path = Path(args.analysis_path)
    if not analysis_path.is_dir():
        print(f"ERROR: analysis path not found: {analysis_path}", file=sys.stderr)
        return 1

    module_count = _module_count(analysis_path)
    relationship_count = _relationship_count(analysis_path)
    languages_detected = _languages_detected(analysis_path)

    sidecar = {
        "schema_version": 1,
        "step": "code-analysis",
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "module_count": module_count,
        "relationship_count": relationship_count,
        "languages_detected": languages_detected,
        "repo_path": str(Path(args.repo).resolve()),
        "repo_analysis_path": str(analysis_path.resolve()),
    }

    sidecar_path = Path(args.sidecar)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    print(f"Written {sidecar_path}")
    print(
        f"module_count={module_count} relationship_count={relationship_count} "
        f"languages_detected={','.join(languages_detected) or '(none)'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

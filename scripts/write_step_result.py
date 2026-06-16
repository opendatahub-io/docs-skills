#!/usr/bin/env python3
"""Generic step-result.json sidecar writer.

Guarantees common fields (schema_version, step, ticket, completed_at).
Merges step-specific data from --data JSON.

Usage:
    python3 write_step_result.py --step planning --ticket PROJ-123 \
        --output-dir <dir> [--data '{"module_count": 5}']
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

SCHEMA_VERSION = 1


def atomic_write_json(path, data):
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description="Write step-result.json sidecar")
    parser.add_argument("--step", required=True, help="Step name")
    parser.add_argument("--ticket", required=True, help="JIRA ticket ID")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--data", default="{}", help="Step-specific JSON data to merge")

    args = parser.parse_args()

    try:
        extra = json.loads(args.data)
    except json.JSONDecodeError as e:
        print(f"Invalid --data JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(extra, dict):
        print("--data must be a JSON object", file=sys.stderr)
        sys.exit(1)

    result = {
        "schema_version": SCHEMA_VERSION,
        "step": args.step,
        "ticket": args.ticket,
        "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    result.update(extra)

    output_path = os.path.join(args.output_dir, "step-result.json")
    atomic_write_json(output_path, result)
    print(output_path)


if __name__ == "__main__":
    main()

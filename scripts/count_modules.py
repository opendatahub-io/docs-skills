#!/usr/bin/env python3
"""Count module specs in a documentation plan file.

Scans for "### Module" headings (with optional numbering) outside code blocks.

Usage:
    python3 count_modules.py <plan.md>

Outputs JSON: {"module_count": N}
"""

import json
import re
import sys


def count_modules(path):
    count = 0
    in_code_block = False
    with open(path) as f:
        for line in f:
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if not in_code_block and re.match(r"^###\s+Module\b", line):
                count += 1
    return count


def main():
    if len(sys.argv) < 2:
        print("Usage: count_modules.py <plan.md>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    try:
        n = count_modules(path)
    except FileNotFoundError:
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    json.dump({"module_count": n}, sys.stdout)
    print()


if __name__ == "__main__":
    main()

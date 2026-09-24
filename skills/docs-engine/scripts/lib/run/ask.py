#!/usr/bin/env python3
"""Answer a step's model call from the pi session that started the run."""

from __future__ import annotations

import os
import socket
import sys

CHUNK = 65536

# Long enough for a real step. A research call over six fetched pages is the
# slowest thing this carries, and the session's model may also be queued behind
# whatever else the user asked pi to do.
TIMEOUT = 900


def ask(path, prompt, timeout=TIMEOUT):
    """Send `prompt` to the listener at `path` and return its reply."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(path))
        client.sendall(prompt.encode("utf-8"))
        client.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            block = client.recv(CHUNK)
            if not block:
                break
            chunks.append(block)
    finally:
        client.close()
    return b"".join(chunks).decode("utf-8")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else os.environ.get("DOCS_ASK_SOCKET", "")
    if not path:
        print(
            "docs-ask: no socket to ask. Pass one as an argument or set "
            "DOCS_ASK_SOCKET. This command only works inside a pi session "
            "running the docs-skills extension.",
            file=sys.stderr,
        )
        return 1

    prompt = sys.stdin.read()
    try:
        reply = ask(path, prompt)
    except (OSError, socket.timeout) as exc:
        print(f"docs-ask: could not reach the pi session at {path}: {exc}", file=sys.stderr)
        return 1

    if not reply.strip():
        # `invoke` would hand an empty stdout to `extract_json`, which reports
        # unparseable JSON. Naming the real problem saves that hunt.
        print(f"docs-ask: the pi session at {path} answered nothing", file=sys.stderr)
        return 1

    sys.stdout.write(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())

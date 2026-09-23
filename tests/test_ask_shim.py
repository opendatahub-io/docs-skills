"""The command line the pi extension depends on.

`lib/run/step.py:invoke` spawns a command, pipes the prompt to its stdin, and
requires exit 0 with the reply on stdout. `ask.py` satisfies that contract
without starting a model: it hands the prompt to a socket the pi extension is
listening on and prints back what the session's model said.

The extension is glue. What has to hold is this contract, so this is where it
is tested, the same way `test_vale_gate.py` tests `check.main` rather than the
TypeScript above it.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import threading
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ASK = _REPO_ROOT / "skills" / "docs-engine" / "scripts" / "lib" / "run" / "ask.py"


def serve(path, reply, capture):
    """A one-shot stand-in for the extension's listener."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)

    def handle():
        conn, _ = server.accept()
        with conn:
            chunks = []
            while True:
                block = conn.recv(65536)
                if not block:
                    break
                chunks.append(block)
            capture.append(b"".join(chunks).decode("utf-8"))
            conn.sendall(reply.encode("utf-8"))
        server.close()

    thread = threading.Thread(target=handle, daemon=True)
    thread.start()
    return thread


def ask(path, prompt, env=None):
    return subprocess.run(
        [sys.executable, str(_ASK), str(path)],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


def test_a_prompt_reaches_the_socket_and_the_reply_reaches_stdout(tmp_path):
    sock = tmp_path / "ask.sock"
    seen = []
    thread = serve(sock, '{"findings": []}', seen)
    done = ask(sock, "what does this feature do?")
    thread.join(timeout=10)
    assert done.returncode == 0
    assert done.stdout == '{"findings": []}'
    assert seen == ["what does this feature do?"]


def test_a_large_prompt_round_trips(tmp_path):
    """Research payloads run to tens of thousands of characters, so a shim that
    only works on short prompts works on none of the real ones."""
    sock = tmp_path / "ask.sock"
    seen = []
    prompt = "x" * 200_000
    thread = serve(sock, "ok", seen)
    done = ask(sock, prompt)
    thread.join(timeout=20)
    assert done.returncode == 0
    assert seen[0] == prompt


def test_no_listener_fails_loudly_with_nothing_on_stdout(tmp_path):
    """`invoke` treats a non-zero exit as a step failure and reports stderr.
    Printing a half-answer on stdout would be parsed as a model reply."""
    done = ask(tmp_path / "absent.sock", "anything")
    assert done.returncode != 0
    assert done.stdout == ""
    assert "docs-ask" in done.stderr


def test_an_empty_reply_is_a_failure_rather_than_an_empty_answer(tmp_path):
    """An empty stdout reaches `extract_json` as unparseable and surfaces as a
    confusing schema error. Saying the listener answered nothing is clearer."""
    sock = tmp_path / "ask.sock"
    thread = serve(sock, "", [])
    done = ask(sock, "anything")
    thread.join(timeout=10)
    assert done.returncode != 0
    assert done.stdout == ""
    assert "nothing" in done.stderr.lower()


def test_the_socket_path_can_come_from_the_environment(tmp_path):
    """The extension sets DOCS_LLM_CMD once; carrying the path in the
    environment keeps that command a fixed string."""
    import os

    sock = tmp_path / "ask.sock"
    seen = []
    thread = serve(sock, "ok", seen)
    env = {**os.environ, "DOCS_ASK_SOCKET": str(sock)}
    done = subprocess.run(
        [sys.executable, str(_ASK)],
        input="hello",
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    thread.join(timeout=10)
    assert done.returncode == 0
    assert done.stdout == "ok"
    assert seen == ["hello"]


def test_no_socket_anywhere_says_what_is_missing(tmp_path):
    import os

    env = {k: v for k, v in os.environ.items() if k != "DOCS_ASK_SOCKET"}
    done = subprocess.run(
        [sys.executable, str(_ASK)],
        input="hello",
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert done.returncode != 0
    assert "DOCS_ASK_SOCKET" in done.stderr

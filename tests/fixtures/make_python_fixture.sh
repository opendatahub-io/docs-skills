#!/usr/bin/env bash
# Builds the synthetic Python repository the pipeline tests run against.
#
# One tagged baseline, then one breaking commit touching three modules in three
# different ways: a real API change, a whitespace-only reformat, and a
# prose-only edit. The relevance engine must reach a different verdict for each.
#
# Usage: make_python_fixture.sh <target-dir>
set -euo pipefail
dir="${1:?target dir}"
rm -rf "$dir" && mkdir -p "$dir" && cd "$dir"
git init -q
git config user.email fixture@example.com
git config user.name Fixture
# A global commit-msg hook that appends its own footer would otherwise bury the
# trailers these fixtures depend on.
git config core.hooksPath /dev/null
mkdir -p core util docs

cat > core/api.py <<'PY'
def connect(host, port=80):
    """Open a connection."""
    return (host, port)

def _private(x):
    return x

class Client:
    def __init__(self, host):
        self.host = host

    def send(self, payload):
        return payload
PY

cat > core/test_api.py <<'PY'
from core.api import Client, connect


def test_connect_uses_the_default_port():
    assert connect("example.com") == ("example.com", 80)


def test_client_echoes_the_payload():
    assert Client("example.com").send({"id": 1}) == {"id": 1}
PY

echo 'def helper(a): return a' > util/tools.py
echo '# docs' > docs/guide.md

cat > registry.json <<'JSON'
{"core": ["core"], "util": ["util"], "docs": ["docs"]}
JSON

git add -A
git commit -qm "feat: initial"
git tag v0.1.0

# core: signature change plus a new public symbol. Verdict: rebuild.
cat > core/api.py <<'PY'
def connect(host, port=443, timeout=30):
    """Open a connection."""
    return (host, port, timeout)

def _private(x):
    return x

def disconnect(handle):
    return None

class Client:
    def __init__(self, host):
        self.host = host

    def send(self, payload):
        return payload
PY

# util: reformat only, identical fingerprint. Verdict: skip.
printf 'def helper(a):\n\n    return a\n' > util/tools.py

# docs: prose only. Verdict: skip.
echo 'more docs' >> docs/guide.md

git commit -qam "feat!: retime connect and add disconnect

BREAKING CHANGE: connect default port is now 443
Fixes: ABC-1"

echo "fixture ready at $dir"

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

# Enough for each foundation gate to reach a verdict. `cli` is an entry
# point, the Makefile declares runnable targets, `legacy` carries a
# deprecation, and the policy file suppresses SECURITY.md the way a real
# repository's hand-written one does.
mkdir -p cli
cat > cli/__init__.py <<'CLIPY'
"""Command line entry point."""


def main():
    """Run the tool."""
    return 0


def legacy():
    """Deprecated: use main instead."""
    return main()
CLIPY

cat > Makefile <<'MAKEEOF'
build: ## Build the package
	python3 -m build

test: ## Run the suite
	python3 -m pytest
MAKEEOF

cat > SECURITY.md <<'SECEOF'
# Security policy

Report a vulnerability to security@example.com.
SECEOF

mkdir -p .docs-gen
cat > .docs-gen/registry.json <<'REGEOF'
{"modules": {"cli": {"kind": "cli"}, "core": {"kind": "library"}, "util": {"kind": "library"}}}
REGEOF
cat > .docs-gen/dep-pairs.json <<'DEPEOF'
{"pairs": [{"from": "cli", "to": "core"}, {"from": "core", "to": "util"}]}
DEPEOF
cat > .docs-gen/api-surface.json <<'APIEOF'
{"modules": {"cli": {"symbols": {"main": {"doc": "Run the tool."},
  "legacy": {"doc": "Deprecated: use main instead."}}}}}
APIEOF

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

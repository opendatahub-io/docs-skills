"""The commands a repository declares, and the allowlist a tutorial may use.

A getting-started page whose commands do not run is worse than no page, so the
commands come from what a manifest declares rather than from a model. The same
list grounds the writer and gates the reviewer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None

# A target name, a colon, then either end of line, a dependency list, or the
# `## ` help text convention. Rejects `CC := gcc` through the `=` lookahead,
# `%.o:` through the character class, and `.PHONY:` through the leading dot.
_TARGET = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_.-]*)\s*:(?!=)(?P<rest>[^=].*)?$")
_HELP = re.compile(r"##\s*(?P<help>.+?)\s*$")

# Universally available, and a tutorial needs them to set a scene. A command
# head outside this set and outside the manifests is one nothing declared.
# The toolchain a reader already has. No manifest declares these, so a
# tutorial that runs an interpreter, installs a dependency or pipes output
# must not be flagged for it. A runner that takes a declared target stays
# out: the whole point of the check is that `make deploy` names a target the
# Makefile has, and `docker` is handled by the allowlist so that a repository
# with no Dockerfile is still flagged for printing one.
BUILTINS = frozenset(
    {
        "cd",
        "git",
        "export",
        "echo",
        "mkdir",
        "curl",
        "cat",
        "ls",
        "cp",
        "mv",
        "chmod",
        # Interpreters and their installers.
        "python",
        "python3",
        "pip",
        "pip3",
        "pipx",
        "node",
        "npx",
        "go",
        "cargo",
        # Pipe and file utilities a worked example runs output through.
        "grep",
        "sed",
        "awk",
        "tee",
        "head",
        "tail",
        "sort",
        "uniq",
        "wc",
        "less",
        "diff",
        "find",
        "tar",
        "unzip",
        "rm",
        "touch",
        "printf",
        "env",
        "which",
        "source",
        "open",
    }
)


def _make_targets(path):
    """Target names and their `## ` help text, in file order."""
    found = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("\t") or line.lstrip().startswith("#"):
            continue
        match = _TARGET.match(line)
        if not match:
            continue
        rest = match["rest"] or ""
        help_match = _HELP.search(rest)
        found.append({"target": match["name"], "help": help_match["help"] if help_match else ""})
    return found


def _nested_keys(data, *keys):
    """A nested object's keys, or an empty list where any step is missing or
    is not itself a mapping. Shared by every manifest reader below, so a
    `project = 5` or a `"scripts": ["a", "b"]` degrades instead of raising."""
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
        if data is None:
            return []
    return sorted(data) if isinstance(data, dict) else []


def _json_keys(path, *keys):
    """A nested object's keys, or an empty list where anything is missing."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    return _nested_keys(data, *keys)


def _docker_entrypoints(path):
    """ENTRYPOINT and CMD lines, as written."""
    found = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        head = line.strip().split(None, 1)
        if len(head) == 2 and head[0].upper() in ("ENTRYPOINT", "CMD"):
            found.append(head[1].strip())
    return found


def _pyproject_scripts(path):
    if tomllib is None:
        # 3.10 has no tomllib, and a TOML dependency for one gate is a poor
        # trade. The bracket-section scan covers the shape the spec names.
        # It works line by line on strings rather than a parsed structure, so
        # there is no `.get` to raise on a non-table `project` — a malformed
        # or unexpected section shape just fails to match and is skipped.
        names, inside = [], False
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                inside = stripped == "[project.scripts]"
                continue
            if inside and "=" in stripped and not stripped.startswith("#"):
                names.append(stripped.split("=", 1)[0].strip().strip('"'))
        return sorted(names)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return []
    # Guarded the same way as `_json_keys`: a non-table `project` (or a
    # non-table `scripts` beneath it) degrades to empty rather than raising,
    # because this runs against pyproject.toml files this tool did not write.
    return _nested_keys(data, "project", "scripts")


def declared_commands(repo):
    """Every command the repository's manifests declare, grouped by runner."""
    root = Path(repo)
    found = {"make": [], "npm": [], "docker": [], "python": []}
    makefile = root / "Makefile"
    if makefile.is_file():
        found["make"] = _make_targets(makefile)
    package = root / "package.json"
    if package.is_file():
        found["npm"] = _json_keys(package, "scripts")
    dockerfile = root / "Dockerfile"
    if dockerfile.is_file():
        found["docker"] = _docker_entrypoints(dockerfile)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        found["python"] = _pyproject_scripts(pyproject)
    return found


def allowlist(declared):
    """The full command strings a document may print.

    Every runner `has_manifest` counts contributes here. A Docker-only
    repository used to pass the getting-started gate on its Dockerfile and
    then hand the writer an empty allowlist, so review flagged whatever the
    page printed and nothing could clear it.
    """
    allowed = set()
    if declared.get("make"):
        # A bare `make` runs the Makefile's first target.
        allowed.add("make")
    for entry in declared.get("make") or []:
        allowed.add(f"make {entry['target']}")
    if declared.get("npm"):
        # package.json declares the scripts, so installing them is declared.
        allowed.update({"npm install", "npm ci"})
    for name in declared.get("npm") or []:
        allowed.add(f"npm run {name}")
    for name in declared.get("python") or []:
        allowed.add(name)
    if declared.get("docker"):
        # ENTRYPOINT and CMD are what the image runs, not what a reader types.
        # These two are what a reader types to reach them.
        allowed.update({"docker build", "docker run"})
    return allowed


def has_manifest(repo):
    """Whether anything declares a runnable target. The GET-STARTED gate."""
    declared = declared_commands(repo)
    return any(declared[key] for key in declared)

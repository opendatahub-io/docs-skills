"""The pi tool schemas `extensions/vale-gate.ts` is pinned to.

The gate fires on `tool_result` and reads `input.path`. Rename that key in pi,
or grow a file-mutating tool the gate does not know about, and nothing breaks
loudly: the gate stops firing, and a run that linted nothing reads exactly like
a run whose prose was clean. The extension narrows through pi's own types, so
`tsc` catches a rename, which is not something this repository's CI runs. This
catches it on any machine that has pi installed.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest


def pi_tools_dir():
    """Where the installed pi keeps its tool declarations, or None.

    Found by walking up from the binary to the package root, because the entry
    point sits at a different depth in a bundled install than in a plain one.
    """
    binary = shutil.which("pi")
    if not binary:
        return None
    for parent in Path(binary).resolve().parents:
        if parent.name == "pi-coding-agent":
            tools = parent / "dist" / "core" / "tools"
            return tools if (tools / "index.d.ts").exists() else None
    return None


_TOOLS = pi_tools_dir()
needs_pi = pytest.mark.skipif(_TOOLS is None, reason="pi is not installed")

# What the extension believes, in one place, so a failure here names the belief.
LINT_TRIGGERING_TOOLS = {"edit", "write"}
PATH_KEY = "path"
KNOWN_TOOLS = {"read", "bash", "powershell", "edit", "write", "grep", "find", "ls"}


@needs_pi
@pytest.mark.parametrize("tool", sorted(LINT_TRIGGERING_TOOLS))
def test_the_tool_input_still_names_the_path_key(tool):
    """`lintTarget` destructures `path` off the narrowed input."""
    declaration = (_TOOLS / f"{tool}.d.ts").read_text()
    schema = re.search(rf"declare const {tool}Schema:.*?^}}>;", declaration, re.S | re.M)
    assert schema, f"no {tool}Schema in {tool}.d.ts"
    keys = set(re.findall(r"^\s{4}(\w+):", schema.group(0), re.M))
    assert PATH_KEY in keys, f"pi's {tool} tool no longer takes `{PATH_KEY}`: {sorted(keys)}"


@needs_pi
def test_the_edit_tool_still_reports_a_patch():
    """The scope the gate passes to `check.py --range` comes off `details.patch`."""
    declaration = (_TOOLS / "edit.d.ts").read_text()
    assert "patch: string" in declaration


@needs_pi
def test_no_tool_has_appeared_that_could_write_prose_unwatched():
    """A new tool is not a failure. Going unread is.

    `bash` already mutates files outside the gate, which is a known hole rather
    than a surprise. This fails on the ninth name, so someone decides whether it
    is a tenth way to write Markdown.
    """
    union = re.search(r"export type ToolName = ([^;]+);", (_TOOLS / "index.d.ts").read_text())
    assert union, "no ToolName union in index.d.ts"
    found = set(re.findall(r'"(\w+)"', union.group(1)))
    assert found == KNOWN_TOOLS, f"pi's tool set moved: {sorted(found ^ KNOWN_TOOLS)}"

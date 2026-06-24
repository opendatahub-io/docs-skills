"""Tests for the Python tree-sitter public API extractor.

Verifies that extract_public_api_treesitter.py produces correct output
for Go, JavaScript, and TypeScript fixtures.
"""

# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "tree-sitter",
#     "tree-sitter-go",
#     "tree-sitter-javascript",
#     "tree-sitter-typescript",
# ]
# ///

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "skills/learn-code/scripts/extract_public_api_treesitter.py"
FIXTURES = Path(__file__).parent / "fixtures/treesitter"

PASS = 0
FAIL = 0


def run_extractor(files: list[str], lang: str, module: str = "test") -> dict:
    """Run the extractor script and return parsed JSON output."""
    cmd = [
        sys.executable, str(SCRIPT),
        "--files", *files,
        "--lang", lang,
        "--module", module,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(
            f"Extractor failed (exit {result.returncode}):\n{result.stderr}"
        )
    return json.loads(result.stdout)


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL  # noqa: PLW0603
    if condition:
        PASS += 1
        print(f"  PASS: {label}")
    else:
        FAIL += 1
        msg = f"  FAIL: {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)


def test_go():
    print("\n=== Go extraction ===")
    result = run_extractor(
        [str(FIXTURES / "sample.go")], "go", "sample"
    )

    check("module name", result["module"] == "sample")
    check("language", result["language"] == "go")

    exports = result["exports"]
    names = [e["name"] for e in exports]

    check("exported func NewConfig", "NewConfig" in names)
    check("exported method Start", "Start" in names)
    check("exported struct Config", "Config" in names)
    check("exported interface Handler", "Handler" in names)
    check("exported type StringAlias", "StringAlias" in names)
    check("exported const DefaultTimeout", "DefaultTimeout" in names)
    check("exported var MaxRetries", "MaxRetries" in names)

    check(
        "unexported func excluded",
        "helperFunc" not in names,
        f"found: {names}",
    )
    check(
        "unexported const excluded",
        "internalLimit" not in names,
        f"found: {names}",
    )
    check(
        "unexported method excluded",
        "validate" not in names,
        f"found: {names}",
    )

    config_export = next(e for e in exports if e["name"] == "Config")
    check("Config kind is struct", config_export["kind"] == "struct")

    handler_export = next(e for e in exports if e["name"] == "Handler")
    check("Handler kind is interface", handler_export["kind"] == "interface")

    start_export = next(e for e in exports if e["name"] == "Start")
    check("Start kind is method", start_export["kind"] == "method")
    check("Start has receiver", "receiver" in start_export)

    new_config = next(e for e in exports if e["name"] == "NewConfig")
    check(
        "NewConfig has docstring",
        new_config["docstring"] is not None,
    )

    imports = result["imports"]
    modules = [i["module"] for i in imports]
    check("imports fmt", "fmt" in modules)
    check("imports net/http", "net/http" in modules)

    check("export_count matches", result["export_count"] == len(exports))


def test_javascript():
    print("\n=== JavaScript extraction ===")
    result = run_extractor(
        [str(FIXTURES / "sample.js")], "javascript", "sample"
    )

    exports = result["exports"]
    names = [e["name"] for e in exports]

    check("exported function greet", "greet" in names)
    check("exported class Logger", "Logger" in names)
    check("exported constant MAX_SIZE", "MAX_SIZE" in names)
    check("exported arrow fn transform", "transform" in names)
    check("default export main", "main" in names)

    transform_export = next(e for e in exports if e["name"] == "transform")
    check(
        "transform kind is function (arrow)",
        transform_export["kind"] == "function",
    )

    max_export = next(e for e in exports if e["name"] == "MAX_SIZE")
    check("MAX_SIZE kind is constant", max_export["kind"] == "constant")

    re_exports = [e for e in exports if e["kind"] == "re-export"]
    check("has re-exports", len(re_exports) >= 1)

    imports = result["imports"]
    modules = [i["module"] for i in imports]
    check("imports fs", "fs" in modules)
    check("imports path", "path" in modules)
    check("imports lodash via require", "lodash" in modules)


def test_typescript():
    print("\n=== TypeScript extraction ===")
    result = run_extractor(
        [str(FIXTURES / "sample.ts")], "typescript", "sample"
    )

    exports = result["exports"]
    names = [e["name"] for e in exports]

    check("exported interface ServerConfig", "ServerConfig" in names)
    check("exported type RequestHandler", "RequestHandler" in names)
    check("exported enum LogLevel", "LogLevel" in names)
    check("exported class Server", "Server" in names)
    check("exported abstract class BasePlugin", "BasePlugin" in names)
    check("exported function createServer", "createServer" in names)
    check("exported constant DEFAULT_PORT", "DEFAULT_PORT" in names)
    check("exported arrow fn handleRequest", "handleRequest" in names)
    check("default export App", "App" in names)

    iface = next(e for e in exports if e["name"] == "ServerConfig")
    check("ServerConfig kind is interface", iface["kind"] == "interface")

    type_alias = next(e for e in exports if e["name"] == "RequestHandler")
    check("RequestHandler kind is type", type_alias["kind"] == "type")

    enum_export = next(e for e in exports if e["name"] == "LogLevel")
    check("LogLevel kind is enum", enum_export["kind"] == "enum")

    abstract = next(e for e in exports if e["name"] == "BasePlugin")
    check(
        "BasePlugin kind is abstract-class",
        abstract["kind"] == "abstract-class",
    )

    imports = result["imports"]
    modules = [i["module"] for i in imports]
    check("imports events", "events" in modules)


def test_no_files():
    print("\n=== Error: no files ===")
    result = run_extractor([], "go", "empty")
    # argparse with nargs='+' and default=[] means no files → error JSON
    # but we need to handle argparse behavior
    check("has error field", "error" in result)
    check("exports empty", result["exports"] == [])
    check("export_count zero", result["export_count"] == 0)


def test_missing_file():
    print("\n=== Missing file (should skip) ===")
    result = run_extractor(
        ["/nonexistent/file.go"], "go", "missing"
    )
    check("no error field", "error" not in result)
    check("exports empty", result["exports"] == [])


if __name__ == "__main__":
    test_go()
    test_javascript()
    test_typescript()
    test_no_files()
    test_missing_file()

    print(f"\n{'=' * 40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        sys.exit(1)
    print("All tests passed!")

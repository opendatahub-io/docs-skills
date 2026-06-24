"""Tests for the Python tree-sitter public API extractor.

Verifies that extract_public_api_treesitter.py produces correct output
for Go, JavaScript, TypeScript, and Python fixtures.
"""

# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "tree-sitter>=0.25.2",
#     "tree-sitter-go>=0.25.0",
#     "tree-sitter-javascript>=0.25.0",
#     "tree-sitter-python>=0.25.0",
#     "tree-sitter-typescript>=0.23.2",
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
        sys.executable,
        str(SCRIPT),
        "--files",
        *files,
        "--lang",
        lang,
        "--module",
        module,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"Extractor failed (exit {result.returncode}):\n{result.stderr}")
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
    result = run_extractor([str(FIXTURES / "sample.go")], "go", "sample")

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
    result = run_extractor([str(FIXTURES / "sample.js")], "javascript", "sample")

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
    result = run_extractor([str(FIXTURES / "sample.ts")], "typescript", "sample")

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


def test_python():
    print("\n=== Python extraction ===")
    result = run_extractor([str(FIXTURES / "sample.py")], "python", "sample")

    check("module name", result["module"] == "sample")
    check("language", result["language"] == "python")

    exports = result["exports"]
    names = [e["name"] for e in exports]

    check("exported function create_config", "create_config" in names)
    check("exported async function async_fetch", "async_fetch" in names)
    check("exported class Config", "Config" in names)
    check("exported class Handler", "Handler" in names)
    check("exported decorated class Settings", "Settings" in names)
    check("exported constant MAX_RETRIES", "MAX_RETRIES" in names)
    check("exported constant DEFAULT_TIMEOUT", "DEFAULT_TIMEOUT" in names)
    check("exported constant CONSTANT_TUPLE", "CONSTANT_TUPLE" in names)

    check(
        "private function excluded",
        "_helper" not in names,
        f"found: {names}",
    )
    check(
        "private class excluded",
        "_InternalHelper" not in names,
        f"found: {names}",
    )
    check(
        "private var excluded",
        "_private_var" not in names,
        f"found: {names}",
    )

    config_export = next(e for e in exports if e["name"] == "Config")
    check("Config kind is class", config_export["kind"] == "class")
    check(
        "Config has docstring",
        config_export["docstring"] == "Holds application configuration.",
    )

    handler_export = next(e for e in exports if e["name"] == "Handler")
    check("Handler kind is class", handler_export["kind"] == "class")
    check(
        "Handler signature includes base class",
        "Config" in handler_export["signature"],
    )

    create_export = next(e for e in exports if e["name"] == "create_config")
    check("create_config kind is function", create_export["kind"] == "function")
    check(
        "create_config has docstring",
        create_export["docstring"] == "Create a new Config with defaults.",
    )
    check(
        "create_config signature has type hints",
        "host: str" in create_export["signature"],
    )

    settings_export = next(e for e in exports if e["name"] == "Settings")
    check(
        "Settings signature includes decorator",
        "@dataclass" in settings_export["signature"],
    )

    max_export = next(e for e in exports if e["name"] == "MAX_RETRIES")
    check("MAX_RETRIES kind is constant", max_export["kind"] == "constant")

    imports = result["imports"]
    modules = [i["module"] for i in imports]
    check("imports os", "os" in modules)
    check("imports sys", "sys" in modules)
    check("imports pathlib", "pathlib" in modules)
    check("imports typing", "typing" in modules)
    check("imports collections.abc", "collections.abc" in modules)
    check("imports dataclasses", "dataclasses" in modules)

    check("export_count matches", result["export_count"] == len(exports))


def test_python_multi_file():
    print("\n=== Python multi-file extraction ===")
    result = run_extractor(
        [str(FIXTURES / "sample.py"), str(FIXTURES / "sample_multi.py")],
        "python",
        "combined",
    )

    exports = result["exports"]
    names = [e["name"] for e in exports]

    check("has exports from sample.py", "Config" in names)
    check("has exports from sample_multi.py", "Processor" in names)
    check("has exports from sample_multi.py", "run_pipeline" in names)
    check("has exports from sample_multi.py", "BATCH_SIZE" in names)

    sample_files = {e["file"] for e in exports}
    check("exports span two files", len(sample_files) == 2)

    imports = result["imports"]
    import_files = {i["file"] for i in imports}
    check("imports span two files", len(import_files) == 2)

    check(
        "total export count",
        result["export_count"] == len(exports),
    )


def test_go_edge_cases():
    print("\n=== Go edge cases ===")
    result = run_extractor([str(FIXTURES / "sample_edge.go")], "go", "sample_edge")

    exports = result["exports"]
    names = [e["name"] for e in exports]

    check("generic struct List", "List" in names)
    check("generic struct Pair", "Pair" in names)
    check("interface Stringer", "Stringer" in names)
    check("grouped type UserID", "UserID" in names)
    check("grouped type GroupID", "GroupID" in names)
    check("struct with embedded Node", "Node" in names)
    check("generic function Map", "Map" in names)
    check("generic function Filter", "Filter" in names)
    check("multi-return generic Swap", "Swap" in names)
    check("grouped var GlobalRegistry", "GlobalRegistry" in names)
    check("grouped var DefaultCtx", "DefaultCtx" in names)

    check(
        "unexported generic merge excluded",
        "merge" not in names,
        f"found: {names}",
    )

    list_export = next(e for e in exports if e["name"] == "List")
    check("List kind is struct", list_export["kind"] == "struct")
    check(
        "List signature has type param",
        "comparable" in list_export["signature"],
    )

    map_export = next(e for e in exports if e["name"] == "Map")
    check("Map kind is function", map_export["kind"] == "function")
    check(
        "Map signature has type params",
        "[T, U any]" in map_export["signature"],
    )

    uid_export = next(e for e in exports if e["name"] == "UserID")
    check("UserID kind is type", uid_export["kind"] == "type")

    reg_export = next(e for e in exports if e["name"] == "GlobalRegistry")
    check("GlobalRegistry kind is variable", reg_export["kind"] == "variable")

    imports = result["imports"]
    modules = [i["module"] for i in imports]
    check("imports context", "context" in modules)
    check("imports sync", "sync" in modules)

    check("export_count matches", result["export_count"] == len(exports))


def test_javascript_edge_cases():
    print("\n=== JavaScript edge cases ===")
    result = run_extractor([str(FIXTURES / "sample_edge.js")], "javascript", "sample_edge")

    exports = result["exports"]
    names = [e["name"] for e in exports]

    check("renamed re-export Emitter", "Emitter" in names)
    check("async function fetchData", "fetchData" in names)

    fetch_export = next(e for e in exports if e["name"] == "fetchData")
    check("fetchData kind is function", fetch_export["kind"] == "function")
    check(
        "fetchData signature includes async",
        "async" in fetch_export["signature"],
    )

    check("has default export", any(e["kind"] == "default" for e in exports))

    imports = result["imports"]
    modules = [i["module"] for i in imports]
    check("imports events", "events" in modules)

    check("export_count matches", result["export_count"] == len(exports))


def test_typescript_edge_cases():
    print("\n=== TypeScript edge cases ===")
    result = run_extractor([str(FIXTURES / "sample_edge.ts")], "typescript", "sample_edge")

    exports = result["exports"]
    names = [e["name"] for e in exports]

    check("generic interface Container", "Container" in names)
    check("generic class Box", "Box" in names)
    check("conditional type IsString", "IsString" in names)
    check("mapped type Readonly", "Readonly" in names)
    check("union type StringOrNumber", "StringOrNumber" in names)
    check("intersection type UserRecord", "UserRecord" in names)
    check("const assertion COLORS", "COLORS" in names)
    check("generic async function loadConfig", "loadConfig" in names)

    container = next(e for e in exports if e["name"] == "Container")
    check("Container kind is interface", container["kind"] == "interface")
    check(
        "Container signature has generic param",
        "<T>" in container["signature"],
    )

    box = next(e for e in exports if e["name"] == "Box")
    check("Box kind is class", box["kind"] == "class")
    check(
        "Box signature has implements",
        "implements" in box["signature"],
    )

    is_string = next(e for e in exports if e["name"] == "IsString")
    check("IsString kind is type", is_string["kind"] == "type")
    check(
        "IsString signature has conditional",
        "extends" in is_string["signature"],
    )

    readonly = next(e for e in exports if e["name"] == "Readonly")
    check("Readonly kind is type", readonly["kind"] == "type")

    load_config = next(e for e in exports if e["name"] == "loadConfig")
    check("loadConfig kind is function", load_config["kind"] == "function")
    check(
        "loadConfig signature has generic",
        "<T>" in load_config["signature"],
    )

    imports = result["imports"]
    modules = [i["module"] for i in imports]
    check("imports events", "events" in modules)

    check("export_count matches", result["export_count"] == len(exports))


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
    result = run_extractor(["/nonexistent/file.go"], "go", "missing")
    check("no error field", "error" not in result)
    check("exports empty", result["exports"] == [])


if __name__ == "__main__":
    test_go()
    test_javascript()
    test_typescript()
    test_python()
    test_python_multi_file()
    test_go_edge_cases()
    test_javascript_edge_cases()
    test_typescript_edge_cases()
    test_no_files()
    test_missing_file()

    print(f"\n{'=' * 40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        sys.exit(1)
    print("All tests passed!")

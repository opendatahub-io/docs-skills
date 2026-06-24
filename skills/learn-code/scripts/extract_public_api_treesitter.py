"""Extract public API surface from Go, JavaScript, and TypeScript files
using tree-sitter AST parsing.

Uses py-tree-sitter (compiled bindings, no Node.js required).

Usage:
    uv run --script extract_public_api_treesitter.py -- \
        --files f1.go f2.go --lang go --module mymod
    uv run --script extract_public_api_treesitter.py -- \
        --files f1.ts --lang typescript --module auth
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

import argparse
import json
import re
import sys
from os.path import basename
from pathlib import Path

import tree_sitter_go
import tree_sitter_javascript
import tree_sitter_typescript
from tree_sitter import Language, Parser

LANGUAGES = {
    "go": Language(tree_sitter_go.language()),
    "javascript": Language(tree_sitter_javascript.language()),
    "typescript": Language(tree_sitter_typescript.language_typescript()),
    "tsx": Language(tree_sitter_typescript.language_tsx()),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(node) -> str:
    """Decode node text from bytes to str."""
    return node.text.decode("utf-8", errors="replace")


def _descendants_of_type(node, type_name: str) -> list:
    """Return all descendants matching *type_name* (recursive)."""
    results = []

    def _walk(n):
        if n.type == type_name:
            results.append(n)
        for child in n.children:
            _walk(child)

    _walk(node)
    return results


def _get_preceding_comment(node) -> str | None:
    """Extract a one-line comment immediately preceding *node*."""
    prev = node.prev_named_sibling
    if not prev:
        prev = node.prev_sibling
    if not prev:
        return None

    if prev.type in ("comment", "line_comment", "block_comment"):
        text = re.sub(r"^//\s?|^/\*|\*/$", "", _text(prev)).strip()
        first_line = text.split("\n")[0][:200]
        return first_line or None
    return None


def _find_declaration_child(export_node):
    """Find the declaration child of an export statement."""
    for child in export_node.named_children:
        if child.type.endswith("_declaration") or child.type.endswith(
            "_signature"
        ):
            return child
    if export_node.named_child_count > 0:
        last = export_node.named_children[-1]
        if last.type not in ("export_clause", "string"):
            return last
    return None


def _find_child_of_type(node, type_name: str):
    """Find first named child matching *type_name*."""
    for child in node.named_children:
        if child.type == type_name:
            return child
    return None


# ---------------------------------------------------------------------------
# Go extraction
# ---------------------------------------------------------------------------


def extract_go_exports(root, file_name: str) -> list[dict]:
    exports = []

    for child in root.named_children:
        if child.type == "function_declaration":
            name_node = child.child_by_field_name("name")
            if not name_node or not _text(name_node)[0].isupper():
                continue
            exports.append(
                {
                    "name": _text(name_node),
                    "kind": "function",
                    "file": file_name,
                    "line": child.start_point[0] + 1,
                    "signature": _text(child).split("{")[0].strip()[:400],
                    "docstring": _get_preceding_comment(child),
                }
            )

        elif child.type == "method_declaration":
            name_node = child.child_by_field_name("name")
            if not name_node or not _text(name_node)[0].isupper():
                continue
            receiver_node = child.child_by_field_name("receiver")
            exports.append(
                {
                    "name": _text(name_node),
                    "kind": "method",
                    "file": file_name,
                    "line": child.start_point[0] + 1,
                    "signature": _text(child).split("{")[0].strip()[:400],
                    "docstring": _get_preceding_comment(child),
                    "receiver": _text(receiver_node) if receiver_node else "",
                }
            )

        elif child.type == "type_declaration":
            for spec in child.named_children:
                if spec.type != "type_spec":
                    continue
                name_node = spec.child_by_field_name("name")
                if not name_node or not _text(name_node)[0].isupper():
                    continue

                type_node = spec.child_by_field_name("type")
                kind = "type"
                if type_node:
                    if type_node.type == "struct_type":
                        kind = "struct"
                    elif type_node.type == "interface_type":
                        kind = "interface"

                sig_lines = _text(spec).split("\n")[:3]
                exports.append(
                    {
                        "name": _text(name_node),
                        "kind": kind,
                        "file": file_name,
                        "line": spec.start_point[0] + 1,
                        "signature": "\n".join(sig_lines)[:400],
                        "docstring": _get_preceding_comment(child),
                    }
                )

        elif child.type == "var_declaration":
            for spec in child.named_children:
                if spec.type != "var_spec":
                    continue
                name_node = spec.child_by_field_name("name")
                if not name_node or not _text(name_node)[0].isupper():
                    continue
                exports.append(
                    {
                        "name": _text(name_node),
                        "kind": "variable",
                        "file": file_name,
                        "line": spec.start_point[0] + 1,
                        "signature": _text(spec)[:200],
                        "docstring": _get_preceding_comment(child),
                    }
                )

        elif child.type == "const_declaration":
            for spec in child.named_children:
                if spec.type != "const_spec":
                    continue
                name_node = spec.child_by_field_name("name")
                if not name_node or not _text(name_node)[0].isupper():
                    continue
                exports.append(
                    {
                        "name": _text(name_node),
                        "kind": "constant",
                        "file": file_name,
                        "line": spec.start_point[0] + 1,
                        "signature": _text(spec)[:200],
                        "docstring": _get_preceding_comment(child),
                    }
                )

    return exports


def extract_go_imports(root, file_name: str) -> list[dict]:
    imports = []

    for child in root.named_children:
        if child.type == "import_declaration":
            specs = _descendants_of_type(child, "import_spec")
            for spec in specs:
                path_node = spec.child_by_field_name("path")
                if path_node:
                    mod_path = _text(path_node).strip('"')
                    imports.append({"module": mod_path, "file": file_name})

    return imports


# ---------------------------------------------------------------------------
# JavaScript / TypeScript extraction
# ---------------------------------------------------------------------------


def extract_js_exports(
    root, file_name: str, is_typescript: bool
) -> list[dict]:
    exports = []

    for child in root.named_children:
        if child.type != "export_statement":
            continue

        decl = child.child_by_field_name(
            "declaration"
        ) or _find_declaration_child(child)
        if not decl:
            clause = _find_child_of_type(child, "export_clause")
            if clause:
                specifiers = _descendants_of_type(clause, "export_specifier")
                for spec in specifiers:
                    name_node = spec.child_by_field_name("name")
                    if not name_node and spec.named_child_count > 0:
                        name_node = spec.named_children[0]
                    if name_node:
                        exports.append(
                            {
                                "name": _text(name_node),
                                "kind": "re-export",
                                "file": file_name,
                                "line": child.start_point[0] + 1,
                                "signature": _text(child)[:200],
                                "docstring": None,
                            }
                        )
            continue

        is_default = "export default" in _text(child)

        if decl.type in ("function_declaration", "function_signature"):
            name_node = decl.child_by_field_name("name")
            exports.append(
                {
                    "name": _text(name_node) if name_node else "(default)",
                    "kind": "function",
                    "file": file_name,
                    "line": decl.start_point[0] + 1,
                    "signature": _text(decl).split("{")[0].strip()[:400],
                    "docstring": _get_preceding_comment(child),
                }
            )

        elif decl.type in ("class_declaration", "abstract_class_declaration"):
            name_node = decl.child_by_field_name("name")
            kind = (
                "abstract-class"
                if decl.type == "abstract_class_declaration"
                else "class"
            )
            exports.append(
                {
                    "name": _text(name_node) if name_node else "(default)",
                    "kind": kind,
                    "file": file_name,
                    "line": decl.start_point[0] + 1,
                    "signature": _text(decl).split("{")[0].strip()[:400],
                    "docstring": _get_preceding_comment(child),
                }
            )

        elif decl.type in ("lexical_declaration", "variable_declaration"):
            declarators = _descendants_of_type(decl, "variable_declarator")
            for d in declarators:
                name_node = d.child_by_field_name("name")
                if not name_node:
                    continue
                value_node = d.child_by_field_name("value")
                kind = "constant"
                if value_node and value_node.type in (
                    "arrow_function",
                    "function_expression",
                ):
                    kind = "function"
                exports.append(
                    {
                        "name": _text(name_node),
                        "kind": kind,
                        "file": file_name,
                        "line": d.start_point[0] + 1,
                        "signature": _text(d)[:400],
                        "docstring": _get_preceding_comment(child),
                    }
                )

        elif decl.type == "interface_declaration":
            if not is_typescript:
                continue
            name_node = decl.child_by_field_name("name")
            exports.append(
                {
                    "name": (
                        _text(name_node) if name_node else "(anonymous)"
                    ),
                    "kind": "interface",
                    "file": file_name,
                    "line": decl.start_point[0] + 1,
                    "signature": _text(decl).split("{")[0].strip()[:400],
                    "docstring": _get_preceding_comment(child),
                }
            )

        elif decl.type == "type_alias_declaration":
            if not is_typescript:
                continue
            name_node = decl.child_by_field_name("name")
            exports.append(
                {
                    "name": (
                        _text(name_node) if name_node else "(anonymous)"
                    ),
                    "kind": "type",
                    "file": file_name,
                    "line": decl.start_point[0] + 1,
                    "signature": _text(decl)[:400],
                    "docstring": _get_preceding_comment(child),
                }
            )

        elif decl.type == "enum_declaration":
            if not is_typescript:
                continue
            name_node = decl.child_by_field_name("name")
            exports.append(
                {
                    "name": (
                        _text(name_node) if name_node else "(anonymous)"
                    ),
                    "kind": "enum",
                    "file": file_name,
                    "line": decl.start_point[0] + 1,
                    "signature": _text(decl).split("{")[0].strip()[:400],
                    "docstring": _get_preceding_comment(child),
                }
            )

        elif is_default:
            exports.append(
                {
                    "name": "(default)",
                    "kind": "default",
                    "file": file_name,
                    "line": decl.start_point[0] + 1,
                    "signature": _text(decl)[:400],
                    "docstring": _get_preceding_comment(child),
                }
            )

    return exports


def extract_js_imports(root, file_name: str) -> list[dict]:
    imports = []

    for child in root.named_children:
        if child.type == "import_statement":
            source_node = child.child_by_field_name("source")
            if source_node:
                mod_path = re.sub(r"^['\"]|['\"]$", "", _text(source_node))
                imports.append({"module": mod_path, "file": file_name})

    require_calls = _descendants_of_type(root, "call_expression")
    for call in require_calls:
        fn_node = call.child_by_field_name("function")
        if fn_node and _text(fn_node) == "require":
            args_node = call.child_by_field_name("arguments")
            if args_node and args_node.named_child_count > 0:
                first_arg = args_node.named_child(0)
                if first_arg and first_arg.type in (
                    "string",
                    "template_string",
                ):
                    mod_path = re.sub(
                        r"^['\"]|['\"]$", "", _text(first_arg)
                    )
                    imports.append({"module": mod_path, "file": file_name})

    return imports


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _error_result(msg: str, module_name: str, lang: str) -> dict:
    return {
        "error": msg,
        "module": module_name,
        "language": lang,
        "exports": [],
        "imports": [],
        "export_count": 0,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Extract public API from Go/JS/TS files via tree-sitter",
    )
    ap.add_argument(
        "--files", nargs="*", default=[], help="Source files to analyze"
    )
    ap.add_argument("--lang", default="javascript", help="Language")
    ap.add_argument("--module", default="unknown", help="Module name")
    args = ap.parse_args()

    if not args.files:
        json.dump(
            _error_result("No files provided", args.module, args.lang),
            sys.stdout,
            indent=2,
        )
        print()
        return

    is_typescript = args.lang == "typescript"
    is_go = args.lang == "go"

    all_exports = []
    all_imports = []

    for filepath in args.files:
        try:
            source = Path(filepath).read_bytes()
        except OSError:
            continue

        file_name = basename(filepath)
        ext = "." + file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

        lang_key = args.lang
        if is_typescript and ext in (".tsx", ".jsx"):
            lang_key = "tsx"

        language = LANGUAGES.get(lang_key)
        if not language:
            print(
                f"Warning: No tree-sitter grammar for {lang_key}",
                file=sys.stderr,
            )
            continue

        parser = Parser(language)
        tree = parser.parse(source)

        if is_go:
            all_exports.extend(extract_go_exports(tree.root_node, file_name))
            all_imports.extend(extract_go_imports(tree.root_node, file_name))
        else:
            all_exports.extend(
                extract_js_exports(tree.root_node, file_name, is_typescript)
            )
            all_imports.extend(extract_js_imports(tree.root_node, file_name))

    result = {
        "module": args.module,
        "language": args.lang,
        "exports": all_exports,
        "imports": all_imports,
        "export_count": len(all_exports),
    }

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        json.dump(
            _error_result(
                f"Unexpected error: {e}",
                "unknown",
                "unknown",
            ),
            sys.stdout,
            indent=2,
        )
        print()
        sys.exit(1)

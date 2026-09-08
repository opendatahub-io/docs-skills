#!/usr/bin/env python3
"""Run one model step: render a prompt, pipe it to a command, validate the reply.

Every model call in this plugin goes through here. The harness is a string on
the command line, so swapping `claude -p` for `codex exec`, `ollama run`, or a
shell wrapper around a raw HTTP call changes nothing else.

    python3 lib/run/step.py \
      --prompt prompts/write-module.md \
      --input .docs-gen/write-input/scheduler.json \
      --schema schemas/write-out.json \
      --llm-cmd "claude -p" \
      --out .docs-gen/write-output/scheduler.json

Exit codes:
    0  wrote a validated result
    2  bad invocation (missing file, unreadable schema)
    3  the model failed validation twice
    4  the command itself failed or timed out
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

SCHEMA = "docs-skills/step/1"

# ``{{input}}`` and friends. Anything not supplied is left in place, so a
# prompt carrying literal braces for the model to read survives rendering.
PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

FENCE = re.compile(r"^\s*```(?:json|jsonc)?\s*\n(?P<body>.*?)\n\s*```\s*$", re.DOTALL)


# ------------------------------------------------------------------- rendering


def render(template, values):
    """Substitute ``{{name}}`` placeholders, leaving unknown names untouched."""

    def replace(match):
        key = match.group(1)
        if key not in values:
            return match.group(0)
        value = values[key]
        if isinstance(value, str):
            return value
        return json.dumps(value, indent=2, sort_keys=True)

    return PLACEHOLDER.sub(replace, template)


def build_values(payload, extra):
    """Prompt variables: the whole input as ``{{input}}``, plus its top level.

    A prompt written against a known input schema reaches fields directly with
    ``{{module}}``. One written against an evolving schema takes ``{{input}}``
    and lets the model read the JSON.
    """
    values = {"input": payload}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if PLACEHOLDER.fullmatch("{{%s}}" % key):
                values.setdefault(key, value)
    values.update(extra)
    return values


# ------------------------------------------------------------------ extraction


def extract_json(text):
    """Recover a JSON document from whatever the CLI printed around it.

    CLIs wrap replies in prose, in a fenced block, or in both. Try the cheap
    readings first and fall back to brace matching, which handles a preamble
    and a trailing sign-off in one pass.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("command produced no output")

    for candidate in (stripped, _unfence(stripped)):
        if candidate is None:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    span = _outermost_json(stripped)
    if span is None:
        raise ValueError("no JSON object or array found in output")
    return json.loads(span)


def _unfence(text):
    match = FENCE.match(text)
    return match.group("body") if match else None


def _outermost_json(text):
    """Longest brace- or bracket-balanced span that parses, scanning from each
    opening delimiter. String literals are skipped so a brace inside prose the
    model quoted does not throw off the count."""
    for start, closer in _candidates(text):
        depth = 0
        in_string = False
        escaped = False
        opener = text[start]
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    span = text[start : index + 1]
                    try:
                        json.loads(span)
                    except json.JSONDecodeError:
                        break
                    return span
    return None


def _candidates(text):
    for index, char in enumerate(text):
        if char == "{":
            yield index, "}"
        elif char == "[":
            yield index, "]"


# ------------------------------------------------------------------ validation


def resolve_ref(ref, root):
    """Resolve a local ``#/a/b`` pointer. Remote refs are not supported."""
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref is supported, got {ref!r}")
    node = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise ValueError(f"unresolvable $ref {ref!r}")
        node = node[part]
    return node


def validate(instance, schema, path="$", root=None):
    """Validate against the JSON Schema subset the step contracts use.

    Deliberately small: type, required, properties, items, enum, additional
    properties, local ``$ref``, and the numeric and string bounds. Everything
    in `schemas/` is written to stay inside it, so the plugin adds no
    dependency for a check that runs on every model reply. Returns a list of
    human-readable errors.
    """
    errors = []
    if not isinstance(schema, dict):
        return errors
    if root is None:
        root = schema

    if "$ref" in schema:
        try:
            schema = resolve_ref(schema["$ref"], root)
        except ValueError as exc:
            return [f"{path}: {exc}"]

    expected = schema.get("type")
    if expected and not _type_ok(instance, expected):
        actual = _type_name(instance)
        want = expected if isinstance(expected, str) else "/".join(expected)
        errors.append(f"{path}: expected {want}, got {actual}")
        return errors

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} is not one of {schema['enum']}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required key {key!r}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate(value, properties[key], f"{path}.{key}", root))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected key {key!r}")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(
                    validate(value, schema["additionalProperties"], f"{path}.{key}", root)
                )

    if isinstance(instance, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                errors.extend(validate(item, item_schema, f"{path}[{index}]", root))
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} items")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']} characters")
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, instance):
            errors.append(f"{path}: does not match /{pattern}/")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")

    return errors


TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(instance, expected):
    names = [expected] if isinstance(expected, str) else list(expected)
    for name in names:
        python_type = TYPES.get(name)
        if python_type is None:
            return True
        if name in ("number", "integer") and isinstance(instance, bool):
            continue
        if isinstance(instance, python_type):
            return True
    return False


def _type_name(instance):
    if isinstance(instance, bool):
        return "boolean"
    for name, python_type in TYPES.items():
        if name in ("number", "boolean"):
            continue
        if isinstance(instance, python_type):
            return name
    return type(instance).__name__


# ---------------------------------------------------------------------- runner


def invoke(command, prompt, timeout, env=None):
    """Pipe the prompt to the command on stdin and return stdout."""
    argv = shlex.split(command)
    if not argv:
        raise ValueError("--llm-cmd is empty")
    try:
        completed = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env or os.environ.copy(),
        )
    except FileNotFoundError:
        raise RuntimeError(f"command not found: {argv[0]}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"command timed out after {timeout}s")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"command exited {completed.returncode}: {detail[:800] or '(no output)'}"
        )
    return completed.stdout


RETRY_PREAMBLE = """
Your previous reply did not satisfy the output contract. Return corrected JSON
and nothing else. No prose before it, no prose after it, no code fence.

Validation errors:
{errors}

Your previous reply:
{previous}
""".strip()


def run_step(prompt_text, payload, schema, command, timeout, retries=1, values=None):
    """Render, invoke, extract, validate, retry once with the errors appended.

    Returns ``(result, attempts)``. Raises ``StepError`` when the last attempt
    still fails, carrying the errors and the final raw reply so the caller can
    write them into review.json rather than losing them to a traceback.
    """
    rendered = render(prompt_text, build_values(payload, values or {}))
    attempt_prompt = rendered
    last_errors = []
    last_raw = ""

    for attempt in range(1, retries + 2):
        last_raw = invoke(command, attempt_prompt, timeout)
        try:
            result = extract_json(last_raw)
        except (ValueError, json.JSONDecodeError) as exc:
            last_errors = [f"$: {exc}"]
        else:
            last_errors = validate(result, schema) if schema else []
            if not last_errors:
                return result, attempt

        if attempt > retries:
            break
        attempt_prompt = (
            rendered
            + "\n\n"
            + RETRY_PREAMBLE.format(
                errors="\n".join(f"- {error}" for error in last_errors),
                previous=last_raw.strip()[:4000],
            )
        )

    raise StepError(last_errors, last_raw)


class StepError(Exception):
    def __init__(self, errors, raw):
        super().__init__("; ".join(errors) or "step failed")
        self.errors = errors
        self.raw = raw


# ------------------------------------------------------------------------- cli


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one model step")
    parser.add_argument("--prompt", required=True, help="Prompt template file")
    parser.add_argument("--input", help="JSON input file. Reads stdin when absent")
    parser.add_argument("--schema", help="JSON Schema the reply must satisfy")
    parser.add_argument("--in-schema", help="Schema the input must satisfy first")
    parser.add_argument(
        "--llm-cmd",
        default=os.environ.get("DOCS_LLM_CMD", "claude -p"),
        help="Command reading the prompt on stdin, writing JSON to stdout",
    )
    parser.add_argument("--out", help="Where to write the result. Default stdout")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra prompt variable. Repeatable",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the rendered prompt and exit without calling the command",
    )
    args = parser.parse_args(argv)

    try:
        prompt_text = Path(args.prompt).read_text()
    except OSError as exc:
        print(f"step: cannot read prompt: {exc}", file=sys.stderr)
        return 2

    try:
        raw_input = Path(args.input).read_text() if args.input else sys.stdin.read()
        payload = json.loads(raw_input) if raw_input.strip() else {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"step: cannot read input: {exc}", file=sys.stderr)
        return 2

    extra = {}
    for item in args.set:
        key, _, value = item.partition("=")
        extra[key.strip()] = value

    if args.in_schema:
        try:
            in_schema = json.loads(Path(args.in_schema).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"step: cannot read input schema: {exc}", file=sys.stderr)
            return 2
        errors = validate(payload, in_schema)
        if errors:
            for error in errors:
                print(f"step: input invalid: {error}", file=sys.stderr)
            return 2

    schema = None
    if args.schema:
        try:
            schema = json.loads(Path(args.schema).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"step: cannot read schema: {exc}", file=sys.stderr)
            return 2

    if args.dry_run:
        sys.stdout.write(render(prompt_text, build_values(payload, extra)))
        return 0

    try:
        result, attempts = run_step(
            prompt_text,
            payload,
            schema,
            args.llm_cmd,
            args.timeout,
            args.retries,
            extra,
        )
    except StepError as exc:
        report = {
            "schema": SCHEMA,
            "prompt": args.prompt,
            "ok": False,
            "errors": exc.errors,
            "raw": exc.raw[:8000],
        }
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).with_suffix(".error.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
        for error in exc.errors:
            print(f"step: {error}", file=sys.stderr)
        return 3
    except (RuntimeError, ValueError) as exc:
        print(f"step: {exc}", file=sys.stderr)
        return 4

    body = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(body)
        print(f"step: {args.prompt} -> {args.out} (attempt {attempts})", file=sys.stderr)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())

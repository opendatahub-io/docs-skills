#!/usr/bin/env python3
"""Run one model step: render a prompt, pipe it to a command, validate the reply."""

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

FENCE = re.compile(r"```(?:json|jsonc)?\s*\n(?P<body>.*?)\n\s*```", re.DOTALL)


# ------------------------------------------------------------------- rendering


GROUNDING = """
## Rules for this answer

1. If you are not sure about something, say you don't know. Don't guess.
2. Only use the provided documents or links when creating output. If you don't
   have a source for a claim, remove it.
3. For every fact, reference the file or link and/or exact line number you got
   it from.
4. Check each claim. If you can't find a source for it, take it out.
5. Before you answer, explain how you got there step by step.

Rule 5 happens inside the JSON. Make `reasoning` the first key of the object you
return, holding an array of short strings, one per step of how you got there.
Write it before the rest of the object, not after. Five steps at the most, one
sentence each, and no code samples in them: it is your working out, not a second
draft of the answer.

The output contract above otherwise stands: one JSON document, nothing printed
before it, nothing after it, no code fence around it. Anything with braces,
brackets or backticks in it, a code sample above all, goes inside a JSON string
where it cannot be mistaken for the reply.
""".strip()


def ground(prompt):
    """A step's prompt, with the rules its answer has to hold to.

    These ride in the prompt because it is the only channel every step shares.
    A step's command is whatever `llm_cmd` resolves to: the pi bridge inside a
    session, `claude -p` outside one, anything a repository configures. A system
    prompt reaches the first and none of the others.
    """
    return f"{prompt.rstrip()}\n\n{GROUNDING}\n"


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
    """Prompt variables: the whole input as ``{{input}}``, plus its top level."""
    values = {"input": payload}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if PLACEHOLDER.fullmatch("{{%s}}" % key):
                values.setdefault(key, value)
    values.update(extra)
    return values


# ------------------------------------------------------------------ extraction


MISSING = object()


def extract_json(text, schema=None):
    """Recover a JSON document from whatever the CLI printed around it.

    More than one thing in a reply can parse: the document itself, a sample
    quoted in the reasoning, a fenced snippet copied out of the input. The
    schema picks the one shaped like the reply, which keeps a page full of
    code samples from costing a retry.

    Two documents of the same shape raise instead. Shape has nothing left to
    choose on and position is no evidence, so the retry says what went wrong
    rather than returning a quoted example as the step's result.
    """
    stripped = text.strip()
    if not stripped:
        raise ValueError("command produced no output")

    fits = []
    fallback = MISSING
    for document in _documents(stripped):
        if not _fits(document, schema):
            if fallback is MISSING:
                fallback = document
            continue
        # The same document reaches here more than once: a fenced reply is
        # also found as a bare span. One document printed twice is not two.
        if not any(document == seen for seen in fits):
            fits.append(document)
        if not _discriminating(schema):
            # Nothing was matched on, so every object fits and the first of
            # them is as good an answer as this can give.
            return fits[0]

    if len(fits) > 1:
        raise ValueError(
            f"the output holds {len(fits)} documents matching the reply shape; "
            "return exactly one JSON document and quote every example inside a string"
        )
    if fits:
        return fits[0]
    if fallback is MISSING:
        raise ValueError("no JSON object or array found in output")
    return fallback


def _discriminating(schema):
    """Whether `_fits` is deciding on anything a sample could fail."""
    return bool(isinstance(schema, dict) and schema.get("required"))


def _documents(text):
    """Every JSON value the output holds, likeliest first."""
    yield from _parsed(text)
    # Later fences beat earlier ones: the reasoning comes before the answer, so
    # a block quoted on the way to it is the one printed first.
    for match in reversed(list(FENCE.finditer(text))):
        yield from _parsed(match.group("body"))
    for span in _spans(text):
        yield from _parsed(span)


def _parsed(candidate):
    try:
        yield json.loads(candidate)
    except json.JSONDecodeError:
        return


def _fits(document, schema):
    """Whether this is shaped like the reply the step asked for.

    Top level type and required keys, nothing deeper. A payload that breaks a
    `minLength` is still the payload, and the retry should say so rather than
    move on to a code sample that parses and report that instead.
    """
    if not isinstance(schema, dict):
        return True
    expected = schema.get("type")
    if expected and not _type_ok(document, expected):
        return False
    required = schema.get("required") or []
    if not required:
        return True
    return isinstance(document, dict) and all(key in document for key in required)


# Where the working out is kept, once it has been taken off the reply. A run
# sets this to one file and every step in it appends, so the trail reads in
# the order the run happened.
TRAIL_ENV = "DOCS_TRAIL"


def keep_reasoning(prompt, document, path=None):
    """Append this step's working out to the run's trail, when there is one.

    `drop_reasoning` takes the reasoning off the artifact, which is right: no
    step's contract has a place for it. Discarding it outright is not. The
    reasoning is not evidence and it does not make a claim true, but it is the
    only record of what the model thought it was doing, and a reviewer asking
    why a page says something has nothing else to read.
    """
    path = path or os.environ.get(TRAIL_ENV)
    if not path or not isinstance(document, dict):
        return
    reasoning = document.get("reasoning")
    if not reasoning:
        return
    entry = {
        "step": (prompt.strip().splitlines() or [""])[0][:120],
        "reasoning": reasoning,
    }
    try:
        trail = Path(path)
        trail.parent.mkdir(parents=True, exist_ok=True)
        with trail.open("a") as handle:
            handle.write(json.dumps(entry) + "\n")
    except OSError as exc:
        # A trail nobody can write is not a reason to lose the step that
        # produced it.
        print(f"step: cannot write the reasoning trail: {exc}", file=sys.stderr)


def drop_reasoning(document, schema=None):
    """Take the model's working out back off the reply.

    The grounding asks for it as the first key, so that the model reasons
    before it answers rather than after. No step's contract has a place for it,
    and an artifact carrying it would not match the same artifact written by a
    step whose schema names the key itself.
    """
    if not isinstance(document, dict) or "reasoning" not in document:
        return document
    if "reasoning" in ((schema or {}).get("properties") or {}):
        return document
    return {key: value for key, value in document.items() if key != "reasoning"}


def _spans(text):
    """Balanced JSON spans that parse, outermost first."""
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
                    yield span
                    break


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
    """Validate against the JSON Schema subset the step contracts use."""
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
and nothing else. No prose before it, no prose after it, no code fence. Your
working out goes in the `reasoning` key, inside the object.

Validation errors:
{errors}

Your previous reply:
{previous}
""".strip()


def run_step(prompt_text, payload, schema, command, timeout, retries=1, values=None):
    """Render, invoke, extract, validate, retry once with the errors appended."""
    rendered = ground(render(prompt_text, build_values(payload, values or {})))
    attempt_prompt = rendered
    last_errors = []
    last_raw = ""

    for attempt in range(1, retries + 2):
        last_raw = invoke(command, attempt_prompt, timeout)
        try:
            document = extract_json(last_raw, schema)
            keep_reasoning(prompt_text, document)
            result = drop_reasoning(document, schema)
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
        sys.stdout.write(ground(render(prompt_text, build_values(payload, extra))))
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

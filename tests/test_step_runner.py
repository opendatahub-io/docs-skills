"""lib/run/step.py: prompt rendering, JSON recovery, schema validation, retry."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
ENGINE = _ROOT / "skills" / "docs-engine"
sys.path.insert(0, str(ENGINE / "scripts"))

from lib.run import step  # noqa: E402

# ------------------------------------------------------------------- rendering


def test_render_substitutes_known_placeholders():
    out = step.render("Hello {{name}}, you are {{age}}", {"name": "Ada", "age": 36})
    assert out == "Hello Ada, you are 36"


def test_render_leaves_unknown_placeholders_alone():
    """A prompt showing the model a literal template must survive rendering."""
    out = step.render("Use {{unknown}} here", {"name": "Ada"})
    assert out == "Use {{unknown}} here"


def test_render_serializes_non_strings_as_json():
    out = step.render("{{input}}", {"input": {"b": 1, "a": 2}})
    assert json.loads(out) == {"a": 2, "b": 1}


def test_build_values_exposes_top_level_keys():
    values = step.build_values({"module": "pkg/queue", "count": 3}, {})
    assert values["module"] == "pkg/queue"
    assert values["input"]["count"] == 3


# ------------------------------------------------------------------ extraction


@pytest.mark.parametrize(
    "raw",
    [
        '{"ok": true}',
        '```json\n{"ok": true}\n```',
        '```\n{"ok": true}\n```',
        'Here is the result:\n\n```json\n{"ok": true}\n```\n\nLet me know!',
        'Sure thing.\n{"ok": true}\nHope that helps.',
    ],
)
def test_extract_json_survives_cli_chatter(raw):
    """Every CLI wraps its reply differently. All of these must land."""
    assert step.extract_json(raw) == {"ok": True}


def test_extract_json_ignores_braces_inside_strings():
    raw = 'Result:\n{"note": "a } brace in prose", "ok": true}\ndone'
    assert step.extract_json(raw)["ok"] is True


def test_extract_json_handles_top_level_array():
    assert step.extract_json("prefix [1, 2, 3] suffix") == [1, 2, 3]


def test_extract_json_rejects_empty_output():
    with pytest.raises(ValueError, match="no output"):
        step.extract_json("   \n  ")


def test_extract_json_rejects_prose_only():
    with pytest.raises(ValueError, match="no JSON"):
        step.extract_json("I could not complete that request.")


# The reasoning the grounding asks for arrives before the reply, and a page
# about configuration reasons about braces. Every case below is a reply the
# runner used to spend a retry on.


SHAPE = {"type": "object", "required": ["name", "items"]}


def test_extract_json_skips_a_sample_quoted_before_the_reply():
    raw = (
        'Step 1: the source shows {"apiVersion": "v1", "kind": "ConfigMap"}.\n'
        "Step 2: that is the shape to document.\n"
        '{"name": "abc", "items": ["x"]}'
    )
    assert step.extract_json(raw, SHAPE) == {"name": "abc", "items": ["x"]}


def test_extract_json_prefers_the_last_fenced_block():
    raw = (
        "First, the sample the guide gives:\n\n"
        '```json\n{"apiVersion": "v1"}\n```\n\n'
        "Here is the answer:\n\n"
        '```json\n{"name": "abc", "items": ["x"]}\n```\n'
    )
    assert step.extract_json(raw, SHAPE)["name"] == "abc"


def test_extract_json_keeps_a_reply_that_fails_deeper_validation():
    """A payload that breaks a rule is still the payload.

    Moving on to a sample that parses would report the wrong error, and the
    retry would be told to fix something it did not write.
    """
    raw = 'Sample: {"apiVersion": "v1"}\n{"name": "ab", "items": []}'
    assert step.extract_json(raw, SCHEMA) == {"name": "ab", "items": []}


def test_extract_json_falls_back_when_nothing_fits_the_schema():
    raw = 'Only this: {"apiVersion": "v1"}'
    assert step.extract_json(raw, SHAPE) == {"apiVersion": "v1"}


def test_extract_json_without_a_schema_takes_the_first_document():
    raw = 'Sample: {"apiVersion": "v1"}\n{"name": "abc", "items": ["x"]}'
    assert step.extract_json(raw) == {"apiVersion": "v1"}


def test_extract_json_refuses_two_documents_that_both_fit():
    """Shape cannot choose between them, so guessing is the wrong answer.

    One of the two is the reply and the other is a sample; picking by position
    reports a quoted example as the step's result and nothing says so.
    """
    raw = 'The guide shows {"name": "ab", "items": ["sample"]}\n{"name": "abc", "items": ["x"]}'
    with pytest.raises(ValueError, match="2 documents"):
        step.extract_json(raw, SHAPE)


def test_extract_json_accepts_the_same_document_printed_twice():
    """A fenced reply is also found as a bare span. That is one document."""
    raw = 'Here:\n\n```json\n{"name": "abc", "items": ["x"]}\n```\n'
    assert step.extract_json(raw, SHAPE) == {"name": "abc", "items": ["x"]}


def test_extract_json_takes_the_first_when_the_schema_names_no_keys():
    """Nothing to discriminate on: every object fits, so order decides again."""
    raw = 'Sample: {"apiVersion": "v1"}\n{"name": "abc"}'
    assert step.extract_json(raw, {"type": "object"}) == {"apiVersion": "v1"}


# ------------------------------------------------------------------ validation


SCHEMA = {
    "type": "object",
    "required": ["name", "items"],
    "properties": {
        "name": {"type": "string", "minLength": 3},
        "count": {"type": "integer", "minimum": 0},
        "kind": {"type": "string", "enum": ["a", "b"]},
        "items": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def test_validate_accepts_a_conforming_instance():
    assert step.validate({"name": "abc", "items": ["x"]}, SCHEMA) == []


def test_validate_reports_missing_required_key():
    errors = step.validate({"items": ["x"]}, SCHEMA)
    assert any("missing required key 'name'" in e for e in errors)


def test_validate_reports_wrong_type_with_path():
    errors = step.validate({"name": 7, "items": ["x"]}, SCHEMA)
    assert any(e.startswith("$.name: expected string") for e in errors)


def test_validate_reports_enum_and_bounds():
    errors = step.validate({"name": "abc", "items": [], "count": -1, "kind": "z"}, SCHEMA)
    joined = " ".join(errors)
    assert "at least 1 items" in joined
    assert "below minimum" in joined
    assert "is not one of" in joined


def test_validate_rejects_unexpected_key():
    errors = step.validate({"name": "abc", "items": ["x"], "extra": 1}, SCHEMA)
    assert any("unexpected key 'extra'" in e for e in errors)


def test_validate_does_not_treat_bool_as_integer():
    errors = step.validate({"name": "abc", "items": ["x"], "count": True}, SCHEMA)
    assert any("expected integer" in e for e in errors)


def test_validate_resolves_local_refs():
    schema = {
        "type": "object",
        "properties": {"types": {"$ref": "#/$defs/docTypes"}},
        "$defs": {"docTypes": {"type": "array", "items": {"type": "string"}}},
    }
    assert step.validate({"types": ["concept"]}, schema) == []
    assert step.validate({"types": [1]}, schema)


def test_validate_reports_unresolvable_ref():
    errors = step.validate({"x": 1}, {"properties": {"x": {"$ref": "#/nope"}}})
    assert any("unresolvable" in e for e in errors)


# ---------------------------------------------------------------------- runner


def _fake_cli(tmp_path, script):
    """A stand-in for `claude -p`: reads the prompt on stdin, prints a reply."""
    path = tmp_path / "cli.py"
    path.write_text(script)
    return f"{sys.executable} {path}"


def test_run_step_returns_a_validated_result(tmp_path):
    cmd = _fake_cli(
        tmp_path,
        'import sys; sys.stdin.read(); print(\'{"name": "abc", "items": ["x"]}\')',
    )
    result, attempts = step.run_step("Do it: {{input}}", {}, SCHEMA, cmd, 30)
    assert result["name"] == "abc"
    assert attempts == 1


def test_run_step_grounds_every_prompt(tmp_path):
    """The rules reach the model whatever the command is.

    `llm_cmd` resolves to the pi bridge in a session and to a CLI outside one.
    The prompt is the only thing both of them read.
    """
    cmd = _fake_cli(
        tmp_path,
        "import sys\n"
        "prompt = sys.stdin.read()\n"
        "assert 'Don\\'t guess' in prompt, 'prompt reached the model ungrounded'\n"
        'print(\'{"name": "abc", "items": ["x"]}\')\n',
    )
    result, _ = step.run_step("Do it", {}, SCHEMA, cmd, 30)
    assert result["name"] == "abc"


def test_run_step_drops_the_reasoning_key(tmp_path):
    """The working out is scaffolding. A strict schema would reject it."""
    cmd = _fake_cli(
        tmp_path,
        "import sys; sys.stdin.read(); "
        'print(\'{"reasoning": ["read the source"], '
        '"name": "abc", "items": ["x"]}\')',
    )
    result, attempts = step.run_step("go", {}, SCHEMA, cmd, 30)
    assert result == {"name": "abc", "items": ["x"]}
    assert attempts == 1


def test_run_step_keeps_the_reasoning_in_the_trail(tmp_path, monkeypatch):
    """Dropped from the reply, kept on disk: an answer nobody can audit is half of one."""
    trail = tmp_path / "reasoning.jsonl"
    monkeypatch.setenv(step.TRAIL_ENV, str(trail))
    cmd = _fake_cli(
        tmp_path,
        "import sys; sys.stdin.read(); "
        'print(\'{"reasoning": ["read the source"], '
        '"name": "abc", "items": ["x"]}\')',
    )
    result, _ = step.run_step("Write the page", {}, SCHEMA, cmd, 30)
    assert result == {"name": "abc", "items": ["x"]}
    entry = json.loads(trail.read_text().splitlines()[0])
    assert entry["reasoning"] == ["read the source"]
    assert entry["step"] == "Write the page"


def test_run_step_without_a_trail_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(step.TRAIL_ENV, raising=False)
    cmd = _fake_cli(
        tmp_path,
        'import sys; sys.stdin.read(); print(\'{"reasoning": ["x"], "name": "abc", '
        '"items": ["x"]}\')',
    )
    step.run_step("go", {}, SCHEMA, cmd, 30)
    assert not list(tmp_path.glob("*.jsonl"))


def test_drop_reasoning_leaves_a_schema_that_asks_for_it():
    schema = {"type": "object", "properties": {"reasoning": {"type": "array"}}}
    document = {"reasoning": ["a"], "name": "abc"}
    assert step.drop_reasoning(document, schema) == document


def test_run_step_retries_once_with_the_errors_appended(tmp_path):
    """The second attempt must see what was wrong with the first."""
    marker = tmp_path / "attempts"
    cmd = _fake_cli(
        tmp_path,
        f"""
import sys, pathlib
prompt = sys.stdin.read()
marker = pathlib.Path({str(marker)!r})
n = int(marker.read_text()) if marker.exists() else 0
marker.write_text(str(n + 1))
if n == 0:
    print('{{"items": ["x"]}}')
else:
    assert "missing required key" in prompt, "retry prompt lost the errors"
    print('{{"name": "abc", "items": ["x"]}}')
""",
    )
    result, attempts = step.run_step("go", {}, SCHEMA, cmd, 30)
    assert result["name"] == "abc"
    assert attempts == 2


def test_run_step_raises_after_the_retry_still_fails(tmp_path):
    cmd = _fake_cli(tmp_path, "import sys; sys.stdin.read(); print('{\"items\": []}')")
    with pytest.raises(step.StepError) as excinfo:
        step.run_step("go", {}, SCHEMA, cmd, 30)
    assert any("missing required key 'name'" in e for e in excinfo.value.errors)
    assert excinfo.value.raw.strip() == '{"items": []}'


def test_invoke_reports_a_nonzero_exit(tmp_path):
    cmd = _fake_cli(tmp_path, "import sys; sys.stdin.read(); sys.exit(2)")
    with pytest.raises(RuntimeError, match="exited 2"):
        step.invoke(cmd, "prompt", 30)


def test_invoke_reports_a_missing_command():
    with pytest.raises(RuntimeError, match="command not found"):
        step.invoke("definitely-not-a-real-binary-9f8e7d", "prompt", 5)


# ------------------------------------------------------------------------- cli


def test_cli_round_trips_through_cat(tmp_path):
    """`cat` as the llm-cmd is the harness-free smoke test.

    A prompt that is already valid JSON, echoed back verbatim, exercises
    rendering, extraction, validation, and writing without a model.
    """
    prompt = tmp_path / "p.md"
    prompt.write_text("{{input}}")
    payload = tmp_path / "in.json"
    payload.write_text(json.dumps({"name": "abc", "items": ["x"]}))
    schema = tmp_path / "s.json"
    schema.write_text(json.dumps(SCHEMA))
    out = tmp_path / "out.json"

    code = step.main(
        [
            "--prompt",
            str(prompt),
            "--input",
            str(payload),
            "--schema",
            str(schema),
            "--llm-cmd",
            "cat",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert json.loads(out.read_text())["name"] == "abc"


def test_cli_writes_an_error_file_on_validation_failure(tmp_path):
    prompt = tmp_path / "p.md"
    prompt.write_text("{{input}}")
    payload = tmp_path / "in.json"
    payload.write_text(json.dumps({"items": []}))
    schema = tmp_path / "s.json"
    schema.write_text(json.dumps(SCHEMA))
    out = tmp_path / "out.json"

    assert (
        step.main(
            [
                "--prompt",
                str(prompt),
                "--input",
                str(payload),
                "--schema",
                str(schema),
                "--llm-cmd",
                "cat",
                "--out",
                str(out),
            ]
        )
        == 3
    )
    report = json.loads((tmp_path / "out.error.json").read_text())
    assert report["ok"] is False
    assert report["errors"]


def test_cli_dry_run_makes_no_call(tmp_path, capsys):
    prompt = tmp_path / "p.md"
    prompt.write_text("module: {{module}}")
    payload = tmp_path / "in.json"
    payload.write_text(json.dumps({"module": "pkg/queue"}))

    assert (
        step.main(
            [
                "--prompt",
                str(prompt),
                "--input",
                str(payload),
                "--llm-cmd",
                "definitely-not-a-real-binary",
                "--dry-run",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert out.startswith("module: pkg/queue")
    # A dry run is read to see what the model will be sent, which includes the
    # rules the runner appends to every prompt.
    assert step.GROUNDING in out


def test_cli_validates_the_input_before_calling(tmp_path):
    prompt = tmp_path / "p.md"
    prompt.write_text("{{input}}")
    payload = tmp_path / "in.json"
    payload.write_text(json.dumps({"items": []}))
    in_schema = tmp_path / "in-schema.json"
    in_schema.write_text(json.dumps(SCHEMA))

    assert (
        step.main(
            [
                "--prompt",
                str(prompt),
                "--input",
                str(payload),
                "--in-schema",
                str(in_schema),
                "--llm-cmd",
                "definitely-not-a-real-binary",
            ]
        )
        == 2
    )

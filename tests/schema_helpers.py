"""Shared utilities for JSON Schema discovery and validation."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent

_ACTION_COMMENTS_SCHEMA = (
    REPO_ROOT / "skills" / "action-comments" / "schema" / "action-comments.json"
)
_EXTRA_OUTPUT_SCHEMAS = [
    ("action-comments", _ACTION_COMMENTS_SCHEMA),
]


def discover_schemas(kind: str = "output") -> list[tuple[str, Path]]:
    """Return (step_name, schema_path) for all workflow step schemas.

    kind="output" returns sidecar schemas (<step>.json).
    kind="input" returns CLI-args schemas (<step>-input.json).
    """
    results = []
    for schema_dir in sorted(REPO_ROOT.glob("skills/docs-workflow-*/schema")):
        step_name = schema_dir.parent.name.removeprefix("docs-workflow-")
        for schema_file in sorted(schema_dir.glob("*.json")):
            is_input = schema_file.stem.endswith("-input")
            if kind == "input" and is_input:
                results.append((step_name, schema_file))
            elif kind == "output" and not is_input:
                is_primary = (
                    schema_file.stem == step_name
                    or step_name == "tech-review"
                    and schema_file.stem == "technical-review"
                )
                if is_primary:
                    results.append((step_name, schema_file))
    if kind == "output":
        results.extend(_EXTRA_OUTPUT_SCHEMAS)
    return results


def load_schema(path: Path) -> dict:
    """Read and parse a JSON Schema file."""
    return json.loads(path.read_text())


def validate_sidecar(step_name: str, data: dict, kind: str = "output") -> None:
    """Validate data against the schema for step_name. Raises on failure."""
    schemas = {name: path for name, path in discover_schemas(kind)}
    if step_name not in schemas:
        raise ValueError(f"No {kind} schema found for step {step_name!r}")
    schema = load_schema(schemas[step_name])
    Draft202012Validator(schema).validate(data)

#!/usr/bin/env python3
"""What a run is configured to do, and which model does each step."""

from __future__ import annotations

import re
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

CONFIG_NAME = ".docs-gen.yaml"
ARTIFACT_DIR = ".docs-gen"

# Every step that can spend a model call. A key outside this set is a typo,
# and a typo silently ignored leaves the step on a model nobody chose. A step
# belongs here when `build.py` calls `llm_cmd_for` for it, which is what the
# README test checks.
MODEL_STEPS = (
    "requirements",
    "research",
    "place",
    "plan",
    "write",
    "review",
)

DEFAULTS = {
    "llm_cmd": "claude -p",
    "llm_cmd_steps": {},
    "docs_dir": "docs",
    "issue_prefixes": [],
    "vale": {},
    "coverage": {},
    "product": "",
    "version": "",
}

# What a `coverage:` block may say, and what each key may be set to. The gate
# decides whether a run answered its ticket, so a typo here is a gate running
# on a setting nobody chose.
COVERAGE_KEYS = {"ticket_evidence": ("strict", "accept")}


def load_config(repo):
    """`.docs-gen.yaml` at the repository root. One config surface, not two."""
    config = dict(DEFAULTS)
    path = Path(repo) / CONFIG_NAME
    if not path.exists():
        return config
    if yaml is None:
        # The caller reports this. A library that prints is a library that
        # cannot be used from anything with its own output.
        config["_warning"] = f"{CONFIG_NAME} found but PyYAML is missing; using defaults"
        return config
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        # Same story as a half-written artifact: a typo in the config has to
        # report itself, not end the run in a traceback.
        config["_warning"] = f"{CONFIG_NAME} is not valid YAML ({exc}); using defaults"
        return config
    generate = data.get("generate") or {}
    for key, value in generate.items():
        config[key] = value
    return config


def llm_cmd_for(step, config, cli=None, env=None):
    """The command for one step, highest precedence first.

    A per-step entry outranks `DOCS_LLM_CMD`, the pi extension pointing every
    step at the session's model. Naming a step is a deliberate choice about
    that step, so it spawns the command it names.

    A general `llm_cmd` stays below the bridge. Inside a session the session's
    model is the general choice, and a config file overriding what someone
    picked with `/model` is not what that key is for.
    """
    if cli:
        return cli
    per_step = (config.get("llm_cmd_steps") or {}).get(step)
    if per_step:
        return per_step
    return env or config.get("llm_cmd") or DEFAULTS["llm_cmd"]


def step_is_configured(step, config):
    """Whether a repository asked for a model on this step by name."""
    return bool((config.get("llm_cmd_steps") or {}).get(step))


def check_steps(config):
    """Reject a per-step key no step reads."""
    unknown = sorted(set(config.get("llm_cmd_steps") or {}) - set(MODEL_STEPS))
    if unknown:
        raise ValueError(
            f"unknown llm_cmd_steps key(s): {', '.join(unknown)}. "
            f"Known steps: {', '.join(MODEL_STEPS)}"
        )


def ticket_evidence_policy(config):
    """Whether a page resting on the ticket description alone is documented.

    `strict` is the default because a page whose only citation is the ticket
    that asked for it has been checked against nothing outside the request.
    A team whose facts reach documentation through tickets before they reach
    anything public sets `accept`, and takes the coverage reason as the record
    of what carried each requirement.
    """
    coverage = config.get("coverage") or {}
    unknown = sorted(set(coverage) - set(COVERAGE_KEYS))
    if unknown:
        raise ValueError(
            f"unknown coverage key(s): {', '.join(unknown)}. "
            f"Known keys: {', '.join(sorted(COVERAGE_KEYS))}"
        )
    value = coverage.get("ticket_evidence") or "strict"
    if value not in COVERAGE_KEYS["ticket_evidence"]:
        raise ValueError(
            f"coverage.ticket_evidence: {value!r} is not one of "
            f"{', '.join(COVERAGE_KEYS['ticket_evidence'])}"
        )
    return value


_BRIDGE = re.compile(r"\bask\.py\b")


def readable(command):
    """The pi bridge named as what it is, rather than as an interpreter and a path.

    `llm_cmd_for` has to return the real command. This is for the table a
    person reads, where `python3 '/long/path/to/ask.py'` says less than the
    thing it does.
    """
    return "the pi session" if _BRIDGE.search(command) else command


def model_table(config, cli=None, env=None):
    """The resolved command per step, and where each one came from."""
    rows = []
    for step in MODEL_STEPS:
        resolved = llm_cmd_for(step, config, cli, env)
        if cli:
            source = "--llm-cmd"
        elif (config.get("llm_cmd_steps") or {}).get(step):
            source = "llm_cmd_steps"
        elif env:
            source = "DOCS_LLM_CMD"
        elif config.get("llm_cmd") and config["llm_cmd"] != DEFAULTS["llm_cmd"]:
            # load_config seeds from DEFAULTS, so an unchanged value means the
            # file said nothing and the built-in is what is running.
            source = "llm_cmd"
        else:
            source = "built-in"
        rows.append((step, readable(resolved), source))
    width = max(len(step) for step, _, _ in rows)
    return "\n".join(f"{step:<{width}}  {cmd}  [{source}]" for step, cmd, source in rows)


class VersionUnresolved(RuntimeError):  # noqa: N818
    """No source answered which release this run targets."""


_RELEASE = re.compile(r"\d+(?:\.\d+)*")


def resolve_version(config, cli=None, fix_versions=()):
    """Which release a run targets, resolved highest precedence to lowest."""
    if cli:
        return str(cli)
    for candidate in fix_versions or ():
        found = _RELEASE.search(str(candidate))
        if found:
            return found.group(0)
    if config.get("version"):
        value = config["version"]
        if not isinstance(value, str):
            # YAML reads an unquoted `version: 3.10` as the float 3.1 and
            # the run would target the wrong release. Nothing can recover
            # "3.10" once YAML has parsed it, so this is rejected rather
            # than reformatted.
            raise VersionUnresolved(
                f"version: {value!r} in .docs-gen.yaml was read as "
                f"{type(value).__name__}, not a string. YAML parses an unquoted "
                "numeric value like 3.10 as the float 3.1, silently dropping the "
                'trailing zero. Quote it: version: "3.10"'
            )
        return value
    raise VersionUnresolved(
        "no version to target. Looked at --version, the ticket's fix version, "
        "and `version` in .docs-gen.yaml"
    )

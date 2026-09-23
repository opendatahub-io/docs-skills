#!/usr/bin/env python3
"""Build one Vale config from a target repository's config and our artifact voices."""

from __future__ import annotations

import re
import sys
from pathlib import Path


class WorkspaceError(RuntimeError):
    """The workspace cannot be built into safely."""


DEFAULT_BASE_STYLES = ["RedHat", "Std", "Voices", "Direct", "RedHatVoice"]

# A rule's own level, not the run's floor. Only the config can say what a
# downloaded rule is worth here. The key is written only when the style it
# names is available: Vale rejects a whole config over a level set on a style
# it cannot find.
RULE_LEVELS = {
    "RedHat": {"RedHat.Headings": "error", "RedHat.NoGerundsInTitles": "error"},
    # `Direct.Length` ships at `error` and counts the words in a sentence,
    # which a Markdown table row is not. It fired five times on one row of an
    # accelerator table and survived three repair passes with nothing to
    # repair.
    "Direct": {"Direct.Length": "warning"},
}

# One ceiling for every artifact. The per-file numbers these replaced were
# guesses at how much each step should need, and a step that goes over says
# more about its own reduction than about the number it crossed.
DEFAULT_BUDGET = 6000

DEFAULT_BUDGETS = {
    "git_context": DEFAULT_BUDGET,
    "onboarding": DEFAULT_BUDGET,
    "plan": DEFAULT_BUDGET,
    "index": DEFAULT_BUDGET,
}

# (budget key, path glob, the committed voice, the generated budget style)
ARTIFACT_SECTIONS = [
    ("git_context", "[**/git-context.md]", "DocsNotes", "DocsBudgetGitContext"),
    ("onboarding", "[**/ONBOARDING.md]", "DocsNotes", "DocsBudgetOnboarding"),
    ("plan", "[**/plan.md]", "DocsPlan", "DocsBudgetPlan"),
    ("index", "[**/changeset-*/index.md]", "DocsPlan", "DocsBudgetIndex"),
]

# A budget is a target rather than a contract, so it warns and the run
# continues. An artifact over it means the reduction that step exists to
# perform probably did not happen. What stops a run is the rules about what an
# artifact must contain, such as a citation on every bullet.
BUDGET_RULE = """extends: occurrence
message: "Over the {label} word budget of {max_words}. Cut it down."
level: warning
scope: raw
max: {max_words}
token: '\\b[\\w-]+\\b'
"""

_STYLES_PATH = re.compile(r"^\s*StylesPath\s*=\s*(.+?)\s*$", re.MULTILINE)
_DROPPED = re.compile(r"^\s*(StylesPath|Packages|MinAlertLevel)\s*=")


def styles_path_of(config_path):
    """The StylesPath a config names, resolved against the config's own directory."""
    config_path = Path(config_path)
    match = _STYLES_PATH.search(config_path.read_text())
    if not match:
        return None
    value = Path(match.group(1))
    return value if value.is_absolute() else (config_path.parent / value).resolve()


def link_styles(source, destination):
    """Link every style directory under `source` into `destination`, keeping what is there."""
    source = Path(source)
    if not source.is_dir():
        return
    for entry in sorted(source.iterdir()):
        if not entry.is_dir():
            continue
        target = destination / entry.name
        if target.exists() or target.is_symlink():
            continue
        target.symlink_to(entry, target_is_directory=True)


def write_budget_style(styles_dir, style_name, label, max_words):
    """Write a one-rule style whose only job is this artifact's word budget."""
    rule_dir = styles_dir / style_name
    rule_dir.mkdir(parents=True, exist_ok=True)
    (rule_dir / "Words.yml").write_text(BUDGET_RULE.format(label=label, max_words=max_words))


def carry_over_sections(text):
    """A target config's sections, without the globals the generated config owns."""
    kept = [line for line in text.splitlines() if not _DROPPED.match(line)]
    return "\n".join(kept).strip()


_BASED_ON = re.compile(r"^([ \t]*BasedOnStyles[ \t]*=[ \t]*)(.+)$", re.M)


def drop_missing_styles(text, styles_dir):
    """Rewrite each `BasedOnStyles` to name only styles present in `styles_dir`.

    Returns `(text, missing)`. A carried config gets the same treatment the
    generated one gets: `--sync-styles` writes a `BasedOnStyles` naming every
    package it meant to download, so a carried line is exactly where an
    undownloaded style hides, and E100 aborts the whole config over it.
    """
    missing = []

    def rewrite(match):
        names = [name.strip() for name in match.group(2).split(",") if name.strip()]
        available = [name for name in names if (Path(styles_dir) / name).is_dir()]
        missing.extend(name for name in names if name not in available)
        # An empty BasedOnStyles is itself a config error, so the line goes
        # rather than being left with nothing after the `=`.
        return f"{match.group(1)}{', '.join(available)}" if available else ""

    text = _BASED_ON.sub(rewrite, text)
    if missing:
        text = drop_rule_levels(text, missing)
    return text, missing


_RULE_LEVEL = re.compile(r"^[ \t]*([A-Za-z0-9_-]+)\.[A-Za-z0-9_./-]+[ \t]*=", re.M)


def drop_rule_levels(text, styles):
    """Remove `Style.Rule = level` lines naming a style that is not installed.

    Dropping the name from `BasedOnStyles` is not enough on its own: a level
    set on a style Vale cannot find is E100 too, and E100 takes the whole
    config down rather than the line that caused it.
    """
    dropped = set(styles)
    kept = []
    for line in text.splitlines():
        match = _RULE_LEVEL.match(line)
        if match and match.group(1) in dropped:
            continue
        kept.append(line)
    return "\n".join(kept)


def rule_levels(styles):
    """`Rule = level` lines for the styles present, sorted for a stable config."""
    lines = []
    for style in styles:
        for rule, level in sorted(RULE_LEVELS.get(style, {}).items()):
            lines.append(f"{rule} = {level}")
    return lines


def resolve_budgets(budgets):
    """Merge caller budgets over the defaults, refusing a key no artifact reads."""
    unknown = sorted(set(budgets or {}) - set(DEFAULT_BUDGETS))
    if unknown:
        known = ", ".join(sorted(DEFAULT_BUDGETS))
        raise ValueError(f"unknown budget key(s): {', '.join(unknown)}. Known keys: {known}")
    return {**DEFAULT_BUDGETS, **(budgets or {})}


def build(
    workspace,
    package_root,
    target_config=None,
    budgets=None,
    base_styles=None,
    downloaded_styles=None,
):
    """Write a run config into `workspace` and return its path."""
    # Resolved, because Vale reads StylesPath relative to the config file's own
    # directory. A relative workspace wrote `StylesPath = ws/vale/styles` into
    # `ws/vale/config.ini`, which Vale resolved to `ws/vale/ws/vale/styles` and
    # rejected with E201. Verified against vale 3.21.0.
    workspace = Path(workspace).resolve()
    # `link_styles` keeps whatever it finds, so a workspace reused across two
    # target repositories would carry the first one's styles into the second.
    # The caller builds a fresh directory per invocation.
    if (workspace / "vale").exists():
        raise WorkspaceError(f"{workspace / 'vale'} already exists; build into a fresh workspace")
    # Resolved, because the styles directory is reached through symlinks written
    # into the workspace. A relative package_root would be resolved against the
    # workspace instead of the caller's directory and land as a broken link.
    package_root = Path(package_root).resolve()
    resolved = resolve_budgets(budgets)

    styles_dir = workspace / "vale" / "styles"
    styles_dir.mkdir(parents=True, exist_ok=True)

    # Ours first: a target repository must not be able to shadow DocsNotes.
    link_styles(package_root / "styles", styles_dir)
    if downloaded_styles is not None:
        link_styles(downloaded_styles, styles_dir)

    carried = ""
    if target_config is not None:
        target_config = Path(target_config)
        target_styles = styles_path_of(target_config)
        if target_styles:
            link_styles(target_styles, styles_dir)
        carried = carry_over_sections(target_config.read_text())

    # A style Vale cannot find is E100, and E100 aborts the whole config rather
    # than the one section that names it, so a single missing package takes the
    # artifact sections down with it. Dropping the name keeps everything else
    # linting. The names that survive are the ones now linked under styles_dir.
    if carried:
        carried, missing = drop_missing_styles(carried, styles_dir)
        available = []
    else:
        wanted = list(base_styles or DEFAULT_BASE_STYLES)
        available = [name for name in wanted if (styles_dir / name).is_dir()]
        missing = [name for name in wanted if name not in available]
    if missing:
        print(
            f"docs-skills: Vale style(s) not installed, dropped from the config: "
            f"{', '.join(missing)}. Run `/docs --sync-styles` to get them.",
            file=sys.stderr,
        )

    # Suggestion, so that --vale-level has something to filter. Every consumer
    # gates on its own floor through check.at_or_above, and both default to
    # error, so the composed level widens what is available without widening
    # what blocks.
    lines = [f"StylesPath = {styles_dir}", "MinAlertLevel = suggestion", ""]
    if carried:
        lines += [carried, ""]
    elif available:
        # An empty BasedOnStyles is itself a config error, so a general section
        # with nothing left to name is omitted and the artifact sections below
        # carry the run on their own.
        lines += ["[**/*.md]", f"BasedOnStyles = {', '.join(available)}"]
        lines += [*rule_levels(available), ""]

    for key, glob, voice, budget_style in ARTIFACT_SECTIONS:
        write_budget_style(styles_dir, budget_style, key.replace("_", " "), resolved[key])
        lines += [glob, f"BasedOnStyles = {voice}, {budget_style}", ""]

    config_path = workspace / "vale" / "config.ini"
    config_path.write_text("\n".join(lines))
    return config_path

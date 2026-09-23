---
name: docs-engine
description: Holds the shared runtime for the documentation generator skills. Use when changing libraries, prompts, or schemas that several generator steps share. Never invoke it directly.
allowed-tools: Bash, Read
---

# docs-engine

The shared code behind the generator skills, packaged as a skill so that it survives installation.

Nothing invokes this skill. Every skill in this plugin that runs a script imports from it.

## Why the shared code lives in a skill

Skill installers copy each skill directory separately and drop symlinks with a warning along the way, so a tree shared above the skills survives neither the copy nor a link. What an installer does guarantee is that every skill lands as a flat sibling under one directory.

The generator skills rely on that guarantee. Each one opens with the same seven lines, which is the whole of the bootstrap:

```python
ENGINE = Path(__file__).resolve().parents[2] / "docs-engine"
if not (ENGINE / "scripts" / "lib" / "run" / "step.py").exists():
    raise SystemExit(
        "docs-skills: the docs-engine skill is missing. It ships alongside this one "
        "and carries the shared runtime; install it, or run from a checkout."
    )
sys.path.insert(0, str(ENGINE / "scripts"))
```

`parents[2]` is `skills/` in a checkout and `<skills-dir>/` after an install, so the same two lines reach this directory either way. No build step, no vendored duplicate, no environment variable.

The `exists()` check is the reason the block is not a bare `sys.path.insert`. Remove this skill from an installation and every other one stops with a message naming it, rather than with an import traceback nobody can act on.

Everything the bootstrap would otherwise recompute lives in [scripts/lib/run/engine.py](scripts/lib/run/engine.py): `PROMPTS`, `SCHEMAS`, `CONFIG`, `LANGUAGES`, `TOPICS`, and the package root that owns `styles/`.

## What is here

```
scripts/lib/ast/       the walkers and extractors; languages.yaml documents them
scripts/lib/git/       git_context.py, api_surface.py, commit_select.py, digest.py
scripts/lib/md/        docs_meta.py, fences.py, render.py, sections.py,
                       changeset.py, language_file.py, ownership.py
scripts/lib/pipeline/  config.py and workspace.py: what a run resolves before it starts
scripts/lib/research/  ticket.py, rhd.py, excerpt.py: the external CLIs and what they return
scripts/lib/run/       step.py (the single model call), engine.py (where things are),
                       report.py (what a step says), ask.py, coverage.py, evidence.py
scripts/lib/vale/      check.py, compose.py, repair.py
prompts/               one file per model step
schemas/               what each model step must return
languages/             the per-language reference a writer is given
config/                path filters, example .docs-gen.yaml, gitignore fragment
reference/             the contract shared across skills
```

[reference/generated-documents.md](reference/generated-documents.md) holds the ownership, fenced-region, and determinism rules that both writers enforce. [scripts/lib/md/ownership.py](scripts/lib/md/ownership.py) applies them. Change the behaviour and change both.

## Invoking the libraries directly

Each library module has a command-line entry point that is useful on its own.

```bash
LIB="$(dirname "$0")/scripts/lib"

python3 "$LIB/git/git_context.py" context --repo . --out git-context.json
python3 "$LIB/md/docs_meta.py" validate --repo .
python3 "$LIB/md/fences.py" check docs/*.md
python3 "$LIB/vale/check.py" docs/guide.md --level error
python3 "$LIB/run/step.py" --prompt P --input I --schema S --llm-cmd "claude -p"
```

## What a step says

`run/report.py` gives every step one line format: `docs-<step>: message`, with
`error:` or `warning:` after the prefix when the message reports an outcome.
The pi extension colours by that severity, so a step that decides its own
severity here is the only thing that decides it.

```python
from lib.run.report import logger

log = logger("docs-plan")
log(f"{len(deliverables)} deliverable(s)")
log("no research to plan from", "warning")
```

The history and fingerprinting layer has its own skill. See [docs-git-context](../docs-git-context/SKILL.md).

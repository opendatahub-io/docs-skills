---
name: docs-engine
description: Shared runtime for the documentation generator skills. Not invoked directly. Holds the git and API fingerprinting libraries, the Markdown ownership and rendering layer, the model step runner, the prompts and schemas, and the per-language files that docs-sync, docs-write, docs-review, docs-repo-analyze, and docs-changelog all read.
allowed-tools: Bash, Read
---

# docs-engine

The generator's shared code, in a skill directory of its own.

Nothing invokes this skill. It exists so that the code five other skills depend
on has somewhere to live that survives installation.

## Why it is a skill

A skill installer copies each skill directory on its own and drops symlinks with
a warning on the way, so a tree shared above the skills does not survive the
copy and cannot be linked in either. It does place every skill as a flat sibling
under one directory.

That is the property the generator skills rely on. From any of their scripts,
this skill is two levels up:

```python
def _find_engine():
    here = Path(__file__).resolve()
    for base in (here.parent, *here.parents):
        if (base / "scripts" / "lib" / "run" / "step.py").exists():
            return base
        sibling = base / "docs-engine"
        if (sibling / "scripts" / "lib" / "run" / "step.py").exists():
            return sibling
```

The same walk finds `skills/docs-engine/` in a checkout and
`<skills-dir>/docs-engine/` after an install, so there is no build step, no
vendored duplicate, and no environment variable.

Removing this skill from an installation breaks the other five. They fail with a
message naming it rather than an import traceback.

## What is here

```
scripts/lib/git/     git_context.py, api_surface.py, extract_changed_ranges.py
scripts/lib/md/      docs_meta.py, language_file.py, fences.py, render.py
scripts/lib/ast/     languages.yaml, per-language parse rules
scripts/lib/run/     step.py, the single model call
prompts/             one file per model step
schemas/             what each model step must return
languages/           per-language documentation conventions
config/              path filters, example .docs-gen.yaml, gitignore fragment
```

## Invoking the libraries directly

Each module has a command line entry point, useful on its own.

```bash
LIB="$(dirname "$0")/scripts/lib"

python3 "$LIB/git/git_context.py" context --repo . --out git-context.json
python3 "$LIB/md/docs_meta.py" validate --repo .
python3 "$LIB/md/language_file.py" validate
python3 "$LIB/md/fences.py" check docs/*.md
python3 "$LIB/run/step.py" --prompt P --input I --schema S --llm-cmd "claude -p"
```

See [docs-git-context](../docs-git-context/SKILL.md) for the history and
fingerprinting layer, which is documented as a skill in its own right.

# docs-skills

A Claude Code plugin providing documentation review, writing, and workflow tools. This file defines the shared project conventions for all AI coding agents. For Claude Code-specific instructions, see [CLAUDE.md](CLAUDE.md).

## Repository structure

```text
.claude-plugin/plugin.json   Plugin packaging metadata (name, version, description)
skills/<skill>/SKILL.md      Skill definitions with frontmatter
tests/                       pytest suite and the synthetic fixture repository

skills/docs-engine/          Shared runtime for the generator. Not invoked directly
  scripts/lib/git/           git_context.py, api_surface.py
  scripts/lib/md/            docs_meta.py, language_file.py, fences.py, render.py
  scripts/lib/ast/           languages.yaml, per-language parse rules
  scripts/lib/run/step.py    The single model call. Prompt in, validated JSON out
  languages/<lang>.md        Per-language documentation conventions
  prompts/<step>.md          One file per model step
  schemas/<step>-out.json    What each model step must return
  config/                    Path filters, example .docs-gen.yaml, gitignore fragment
```

The shared code lives inside `skills/docs-engine/` rather than at the repository
root. An installer copies each skill directory on its own and drops symlinks on
the way, so a tree above the skills does not survive installation. It does place
every skill as a flat sibling, which is what the other skills use to reach the
engine.

There are no `agents/`, `hooks/`, `reference/`, or `eval/` directories. Subagent
definitions went with the ticket-driven pipeline they served.

## Calling scripts from skills

The runtime working directory is the project root, not the skill directory, so a
bare `scripts/foo.py` fails. Resolve from the file doing the calling.

```bash
# Same-skill script
python3 "$(dirname "$0")/scripts/write.py" --repo .

# The shared runtime, a sibling skill
python3 "$(dirname "$0")/../docs-engine/scripts/lib/git/git_context.py" context --repo .

# A PEP 723 script, for the tree-sitter extractor's dependencies
uv run --script "$(dirname "$0")/../docs-engine/scripts/lib/ast/extract_public_api_treesitter.py" \
  --module pkg/queue --lang go --files pkg/queue/queue.go
```

The same paths work from a checkout and from an installed copy, because both put
the skills side by side.

## Conventions

**No harness variables.** Nothing reads `${CLAUDE_PLUGIN_ROOT}` or
`${CLAUDE_SKILL_DIR}`, because no harness sets a plugin root. Python scripts
find the engine with a walk from `__file__`:

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

The same walk resolves `skills/docs-engine/` in a checkout and
`<skills-dir>/docs-engine/` after an install, so there is no build step and no
duplicated copy. `SKILL.md` uses `$(dirname "$0")/../docs-engine/`.

**Skill names carry a `docs-` prefix.** This applies to every skill in the
repository, not only the generator's. A destination-path collision makes the
installer skip the entire plugin with a warning rather than just the colliding
skill, so one unprefixed name like `changelog` can make all 59 skills here
vanish from an installation. The `ibm-sg-*` and `rh-ssg-*` skills are the
exception, already namespaced by their own prefixes.

**No subagent dispatch.** No `Agent`, no `Task`, no fan-out. Where the plan
calls for per-module work, it is a sequential loop over the engine's `step.py`.
Parallelism is the harness's to supply; the skill supplies a list.

**Every model call goes through the engine's `lib/run/step.py`.** Prompt in, JSON out,
validated against a schema, one retry with the errors appended. A step that
needs a model gets a prompt in `prompts/` and a schema in `schemas/`. Nothing
calls a model any other way.

**`allowed-tools` stays within `Bash, Read, Write`.** Every harness offers those
three under some name.

**Guards live in scripts, never in prompts.** Whether a file may be written,
which bytes may move, and whether doc comments reach source are decided by
`docs-write`'s script. A prompt instruction is a request; a function that never
receives the surrounding text is a guarantee.

## Skill naming

**Skills** (invoked via the Skill tool) use bare names: `docs-sync`, `docs-write`, `docs-query-code`. Qualified names (`docs-skills:docs-sync`) also work.

There are no agents to name. Every model step is a `step.py` invocation rather
than a subagent dispatch.

## Contributing rules

- Use kebab-case for skill and agent names, and prefix every skill with `docs-`
- Bump version in `.claude-plugin/plugin.json` when making changes
- New Python scripts with external dependencies must use PEP 723 inline metadata
- New stdlib-only scripts use plain `python3` invocation
- Run `make lint` before committing (skillsaw + ruff + shellcheck)
- Install test dependencies with `pip install -r requirements.txt` before running `make test`
- Use `feat:`, `fix:`, `docs:`, `chore:` commit prefixes
- Generator skills carry no harness variables and no subagent dispatch (see above)
- A new language is two files under `skills/docs-engine/`: an entry in
  `scripts/lib/ast/languages.yaml` and a `languages/<lang>.md` whose frontmatter
  validates against `schemas/language-file.json`
- When referencing Python in install steps, always use `python3`

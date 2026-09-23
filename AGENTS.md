# docs-skills

A pi package providing documentation generation from code repositories. This file defines the shared project conventions for every AI coding agent working in this repository.

## Repository structure

```text
package.json                 pi package manifest: name, version, pi.extensions, pi.skills
tsconfig.json                Typechecks the extensions against the pi version package.json pins
extensions/                  pi extensions, loaded when a session starts
  docs.ts                    /docs and /docs-sync, and the socket bridge to the session model
  vale-gate.ts               Lints what pi writes, in the turn it was written
vale/docs.ini                The Vale packages and rule levels a run composes from
styles/                      The Vale styles this package owns. Downloaded packages are ignored
skills/<skill>/SKILL.md      Skill definitions with frontmatter
tests/                       pytest suite and the synthetic fixture repository

skills/docs-engine/          Shared runtime for the generator. Not invoked directly
  scripts/lib/git/           git_context.py, api_surface.py, commit_select.py, digest.py
  scripts/lib/md/            docs_meta.py, fences.py, render.py, ownership.py, sections.py, changeset.py
  scripts/lib/ast/           languages.yaml, per-language parse rules, exclusions.py
  scripts/lib/vale/          check.py, compose.py, repair.py
  scripts/lib/pipeline/      config.py, workspace.py
  scripts/lib/run/step.py    The single model call. Prompt in, validated JSON out
  scripts/lib/run/ask.py     The bridge that sends a step's prompt to the pi session
  languages/<lang>.md        Per-language documentation conventions
  prompts/<step>.md          One file per model step
  schemas/<step>-out.json    What each model step must return
  reference/                 style-topics.md, generated-documents.md
  config/                    Path filters, example .docs-gen.yaml, gitignore fragment
```

The shared code lives inside `skills/docs-engine/` rather than at the repository
root. An installer copies each skill directory on its own and drops symlinks on
the way, so a tree above the skills does not survive installation. It does place
every skill as a flat sibling, which is what the other skills use to reach the
engine.

There are no `agents/`, `hooks/`, or `eval/` directories. Subagent definitions
went with the ticket-driven pipeline they served.

## The two entry points

`/docs` runs the plan-driven chain over one repository: git context, repository
analysis, a plan, a document per deliverable, then review.

`/docs-sync` runs the incremental chain for CI: the same analysis, an API
fingerprint diff against the watermark, a rewrite of the modules that moved,
then review. It stops early when nothing changed.

Both spawn the same engine and read the same `.docs-gen.yaml`.

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
`${CLAUDE_SKILL_DIR}`, because no harness sets a plugin root. A Python script
finds the engine by its fixed position as a sibling:

```python
ENGINE = Path(__file__).resolve().parents[2] / "docs-engine"
if not (ENGINE / "scripts" / "lib" / "run" / "step.py").exists():
    raise SystemExit(
        "docs-skills: the docs-engine skill is missing. It ships alongside this one "
        "and carries the shared runtime; install it, or run from a checkout."
    )
sys.path.insert(0, str(ENGINE / "scripts"))
```

Two levels up from a skill script is always the skills directory, in a checkout
and in an install alike. A walk that stops at the first directory holding
`scripts/lib/run/step.py` would also find the engine, and it is the wrong
answer: `lib/run/engine.py` derives `PACKAGE_ROOT` as `ENGINE.parent.parent` to
reach `styles/` and `vale/`, and a walk that halted early cannot. Stating the
position also names what is missing when it is missing, rather than failing on
an import several frames later.

**Skill names carry a `docs-` prefix,** with `docs` itself as the entry point.
A destination-path collision makes an installer skip the entire package with a
warning rather than just the colliding skill, so one unprefixed name like
`changelog` can make every skill here vanish from an installation.

**No subagent dispatch.** No `Agent`, no `Task`, no fan-out. Where the plan
calls for per-module work, it is a sequential loop over the engine's `step.py`.
Parallelism is the harness's to supply; the skill supplies a list.

**Every model call goes through the engine's `lib/run/step.py`.** Prompt in,
JSON out, validated against a schema, one retry with the errors appended. A step
that needs a model gets a prompt in `prompts/` and a schema in `schemas/`.
Nothing calls a model any other way.

**`allowed-tools` stays within `Bash, Read, Write`.** Every harness offers those
three under some name.

**Guards live in scripts, never in prompts.** Whether a file may be written,
which bytes may move, and whether doc comments reach source are decided by
`docs-write`'s script. A prompt instruction is a request; a function that never
receives the surrounding text is a guarantee.

**Vale carries the mechanical prose rules.** Terminology, punctuation, passive
voice, inflated wording and heading form are checked by `lib/vale/`, not by
standing prompt instructions. A rule that a linter can decide does not belong in
a prompt, where it costs tokens on every call.

## Skill naming

**Skills** (invoked via the Skill tool) use bare names: `docs`, `docs-sync`,
`docs-write`, `docs-query-code`. Qualified names (`docs-skills:docs-sync`) also
work.

There are no agents to name. Every model step is a `step.py` invocation rather
than a subagent dispatch.

## Coding guidelines

Behavioral rules to reduce common mistakes. These bias toward caution over speed. Use judgment for trivial tasks.

### Think before coding

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them rather than picking silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what is confusing. Ask.

### Simplicity first

- No features beyond what was asked.
- No duplication of existing functionality.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that was not requested.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical changes

When editing existing code:

- Do not "improve" adjacent code, comments, or formatting.
- Do not refactor things that are not broken.
- Match existing style, even where you would do it differently.
- If you notice unrelated dead code, mention it rather than deleting it.

When your changes create orphans:

- Remove imports, variables and functions that YOUR changes made unused.
- Do not remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the request.

## Skill logic must live in scripts

Anything deterministic belongs in a script, not in prose a model re-derives each run. Path resolution, JSON assembly, schema validation, git plumbing, and every ownership guard are script-level. A `SKILL.md` says when to reach for the skill and what its arguments mean; it does not restate what the script already does.

Ownership is the clearest case. Whether a file may be written, and which bytes may move, is decided in `docs-write`'s script. A prompt instruction is a request; a function that never receives the surrounding text is a guarantee.

## Referencing files from skills

`@` references are a user input feature resolved by a CLI when someone types in the chat prompt. They are NOT resolved inside skill body text, which becomes the system prompt verbatim. Use a relative path and a normal link instead.

## Debugging

- **Wrong or missing documents**: read `.docs-gen/write-report.json`. Every result carries a status and a reason, including refusals by the ownership contract.
- **A run did nothing**: `/docs` exits 1 when the plan is empty, and `/docs-sync` exits 1 when the loop guard fires or no module changed. Its stderr says which. `.docs-gen/relevance.json` carries the per-module verdict.
- **A model step failed**: `step.py` writes `<out>.error.json` with the validation errors and the raw reply that failed them.
- **Claims that do not match the code**: `.docs-gen/review.json` lists every finding with a severity and the document it came from.
- **Prose that will not pass**: `.docs-gen/vale-run/` holds each repair attempt. A rule that is wrong about these documents is lowered in the repository's own `.vale.ini`, which overrides the composed config.

## Contributing rules

- Use kebab-case for skill names, and prefix every skill with `docs-`
- Bump version in `package.json` when making changes
- New Python scripts with external dependencies must use PEP 723 inline metadata
- New stdlib-only scripts use plain `python3` invocation
- Run `make lint` before committing (skillsaw + tsc + ruff + shellcheck)
- Install test dependencies with `pip install -r requirements.txt` before running `make test`
- Install the Node dev dependencies with `npm ci` before running `make typecheck`
- Use `feat:`, `fix:`, `docs:`, `chore:` commit prefixes
- Skills carry no harness variables and no subagent dispatch (see above)
- A new language is two files under `skills/docs-engine/`: an entry in
  `scripts/lib/ast/languages.yaml` and a `languages/<lang>.md` whose frontmatter
  validates against `schemas/language-file.json`
- When referencing Python in install steps, always use `python3`

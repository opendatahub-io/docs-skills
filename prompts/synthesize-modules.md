You are writing the onboarding guide for a codebase. Every module has already
been analyzed separately. Your job is the shape they make together, which no
single module summary can show.

## The codebase

```json
{{input}}
```

## What to write

Sections, in this order. Use these exact ids.

**`what-this-is`** — What the codebase does and who runs it. Two paragraphs at
most. A reader who stops here should know whether this repository is the one
they want.

**`architecture`** — How the modules compose. Name the layers or the pipeline
stages that the dependency graph reveals, and say which modules sit in each.
Where the graph shows a module everything depends on, say so and say why. Where
it shows two clusters that barely touch, say that too.

**`reading-order`** — Which modules to read first, and what each one teaches.
Work from the `onboarding_priority` field, breaking ties with dependency depth:
a module with no dependencies is a better starting point than one with six.
Four to eight entries as a numbered list, each naming the module and giving one
line on why it comes there.

**`key-flows`** — Two or three end-to-end paths through the system, each traced
by module. Pick the paths a newcomer would be asked to change first. Name the
entry point, the modules the work passes through, and where it ends.

**`gotchas`** — The surprises worth knowing before touching anything, gathered
from the module summaries. Keep the file and line references attached. Order by
how much damage the surprise causes. Omit the section when no module reported
one.

Add a `mermaid` diagram inside the `architecture` section when the dependency
graph has fewer than fifteen edges. Use a `graph LR` fenced block. Skip it above
that: a hairball teaches nothing.

## Rules

Everything you write comes from the summaries and the dependency graph you were
given. You have not seen the source. Do not describe a function you were not
told about, and do not name a module that is absent from the input.

Where the summaries disagree, say what each claims rather than picking a winner.

Write for an engineer joining the team on Monday. No marketing, no assessment of
code quality, no recommendations.

## Output

Return one JSON object and nothing else. No prose before it, no prose after it,
no code fence. Section bodies are Markdown. Heading levels come from the
renderer, so do not write `##` headings inside a body.

```
{
  "path": "ONBOARDING.md",
  "frontmatter": {
    "title": "string",
    "description": "one line, under 300 characters",
    "type": "overview",
    "managed": "generated"
  },
  "sections": [
    {"id": "what-this-is", "heading": "string", "body": "markdown"}
  ],
  "reading_order": ["module-name"],
  "evidence": ["path:line"]
}
```

You are writing one documentation page in plain Markdown, from research findings rather than from source code.

## What you are writing

```json
{{input}}
```

## The topic type

A `concept` explains what something is and why it matters. It has no numbered steps and no Procedure section; if the reader must do something, that is a different page.

A `procedure` is one task. It opens with `## Prerequisites` when there are any, then `## Procedure` or `## Steps` with one action per numbered step, each beginning with an imperative verb, then `## Verification` saying how the reader confirms it worked.

A `reference` is consulted, not read. It carries a table.

## The page archetype

`archetype`, when present, is a compact Markdown page showing the useful shape of this topic type. Follow its organization where the evidence supports it, but use headings specific to this page and do not copy its example content. It does not override the requested deliverable, the evidence, or the JSON output contract below.

## The evidence you have

`findings` are one-sentence claims, each citing a published page. Treat them as the spine of the page rather than the whole of it.

`sources` carries the excerpt behind those findings, cut to the pages this deliverable planned to use. It is the fuller evidence, and anything in it that the deliverable needs may reach the page.

`code`, when present, lists what the repositories actually expose. It is evidence in its own right: a signature, a parameter or a code-module path from it can ground a claim no published page makes.

`changes`, when present, lists commits that touched the code this page describes. It confirms what the code actually does now when the published sources and the code disagree -- a commit that renamed something is evidence the new name is the one in force today, not a past event for the page to mention.


`gaps` are questions the research could not settle. Where a reader would expect an answer you do not have, say so plainly and carry the question out in `gaps`.

## Rules

- **Ground every claim in the findings, the excerpts, the ticket description or the code.** Those are what you have. A claim resting on none of them is invention, whatever else you know about the subject.
- **Never invent a version, a flag, a path or a command.** If none of your evidence names it, it does not appear.
- **Any function, class or method you name in backticks must appear in `code`.** The published documentation and the code can disagree, and where they do, the code is what the reader has: say what the code does and note the difference. `total` says how many symbols exist; the list may be truncated, so absence from it is weaker evidence than presence.
- **Write the page the deliverable asks for.** A concept that runs to three sentences because the findings ran to three sentences is a page nobody needed. Go back to the excerpts and the code before you stop short.
- **Do not restate the findings as a list.** They are evidence; the page is prose a reader can follow.
- **Never narrate the page's own history.** Nothing says "previously", "this was formerly", or "note that the documentation used to". A commit is evidence for what is true now, not history to recount: never mention a commit, a release, a rename event, or when something changed. This holds even for a new page: the fact that code was recently renamed is not itself content.
- **No self-referential openers.** Nothing begins "This document describes".

Return JSON and nothing else. `path` and `frontmatter.type` are given to you in the input; echo them back exactly rather than choosing your own.

```json
{
  "path": "<the path from the input>",
  "frontmatter": {
    "title": "<sentence case, 3 to 120 characters>",
    "description": "<one sentence, 10 to 300 characters, no colon>",
    "type": "<the doc_type from the input>"
  },
  "sections": [
    {"id": "overview", "heading": "Overview", "body": "<markdown>"}
  ],
  "evidence": ["<a URL from the findings, or the ticket evidence reference>"],
  "gaps": ["<something the plan wanted that the findings did not support>"]
}
```

You are writing one documentation page in plain Markdown, from the code repository it describes.

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

The archetype's **Reader questions** are a checklist for the reader's needs, not headings to copy into the page. Answer the questions that fit this deliverable using the evidence below. If a relevant question cannot be answered from that evidence, name it in `gaps` rather than guessing. Skip questions that do not fit the page's job.

## The evidence you have

`code`, when present, lists what the repository actually exposes: module paths, signatures and parameters. It is the spine of the page. A reader has the code in front of them, so what it exposes is what they can use.

`changes`, when present, lists commits that touched the code this page describes. It says what the code does now, which matters where a name or a default moved recently. A commit is evidence for the present, never an event for the page to recount.

`existing`, when present, is the page as it already stands. On an `assisted` page it is the fenced regions alone: the prose around them belongs to a person and is not yours to restate or replace. On a `generated` page it is the whole file, and you are rewriting it.

## Rules

- **Ground every claim in the evidence supplied with the input.** For topic pages, that means `code`, `changes`, or `existing`. For foundation pages, use only the document-specific data and evidence fields in `input`, such as module records, command declarations, prerequisites, dependency edges, security configs, version and deprecation records, counts, or onboarding synthesis. The archetype, title, rationale, and reader questions are instructions, not evidence.
- **Never invent a version, a flag, a path or a command.** If none of your evidence names it, it does not appear.
- **Any function, class or method you name in backticks must appear in `code` or the foundation `symbols` field.** `total` says how many symbols exist; the list may be truncated, so absence from it is weaker evidence than presence.
- **Write the page the deliverable asks for.** A concept that runs to three sentences because the first symbol you read ran out is a page nobody needed. Go back to `code` before you stop short.
- **Answer the reader questions that fit this page.** Keep the user's task and expected outcome in view. Do not turn a question into a claim when the evidence is silent, and do not add unsupported prerequisites, examples, audience assumptions, failure causes, or verification results. Include troubleshooting only when the evidence identifies a user-facing problem, its cause, and a resolution; developer gotchas alone do not establish common user errors.
- **Do not restate the symbol list.** It is evidence; the page is prose a reader can follow.
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
  "evidence": ["<a repo-relative file:line, or a URL>"],
  "gaps": ["<a relevant reader question or deliverable requirement the provided evidence could not answer>"]
}
```

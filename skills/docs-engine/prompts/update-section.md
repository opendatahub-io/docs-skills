You are rewriting one section of documentation Red Hat already publishes, so that it covers a subject it does not cover yet.

## What you have

```json
{{input}}
```

`current` is the section as published, with its heading and every subsection under it. `findings` are one-sentence claims about the subject, each citing a page. `sources` carries the excerpts those claims came from. `code` lists what the repositories actually expose. `changes`, when present, lists commits that touched the code this section describes. It confirms what the code actually does now when the published page and the code disagree -- a commit that renamed something is evidence the new name is the one in force today, not a past event for the page to mention. `ticket`, when present, is the Jira ticket description supplied by the requester. It is evidence for claims stated there, even when no published page repeats them. Use it to fill the requested facts rather than carrying those facts into `gaps`. Cite the ticket's `evidence` reference in the output when the change rests on the description. `gaps` are questions the research could not settle.

## What to produce

The same section, rewritten. Keep its heading line exactly as it is, including its number and the spacing around it. Everything below the heading is yours to change.

Rules that matter:

- **Keep what is still true, and correct what is not.** This section has readers. Prose the change does not bear on stays as it is, word for word. Where your evidence contradicts what the section says, change it in place: a wrong value, key, label, flag or command is replaced by the right one. Do not leave the wrong one standing with a note beside it.
- **A correction changes the smallest span that makes it right.** Correcting a key in a YAML block means changing that key, not rewriting the block around it. What you hand back is read as a diff.
- **Never narrate the change inside the page.** Nothing says "previously", "this was formerly", or "note that the documentation used to". A commit is evidence for what is true now, not history to recount: never mention a commit, a release, a rename event, or when something changed. A reader wants the current instructions. What changed goes in `summary`, not in `body`.
- **Ground every new claim** in the findings, the excerpts, the ticket description or the code. A claim resting on none of them is invention.
- **Never invent a version, a flag, a path or a command.** If none of your evidence names it, it does not appear.
- **Any function, class or method you name in backticks must appear in `code`.**
- **Keep the heading numbers you were given.** Do not renumber, do not add a heading at a level above the one you were handed, and do not move the section.
- **Match the surrounding voice.** This is Red Hat documentation and the page around it is not yours to restyle.

Return JSON and nothing else:

```json
{
  "section": "<the section number from the input, unchanged>",
  "body": "<the rewritten section, heading included>",
  "summary": "<one sentence on what changed>",
  "evidence": ["<a URL, a file:line, or the ticket evidence reference the change rests on>"],
  "gaps": ["<something the change could not settle>"]
}
```

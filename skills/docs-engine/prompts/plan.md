You are deciding what documents to write about a topic, given what is already published about it.

## What you have

The findings from a research pass, each carrying the URL it came from, and the questions those sources did not answer.

```json
{{input}}
```

If a `requirements` block is present, it is what the ticket asked the documentation to do, each with a number. Nothing else in this payload says what the work is for.

If a `placement` block is present, it lists places in documentation that is already published where this subject belongs. Each carries the guide, a section number, and whether the subject should rewrite that section or follow it as something new.

If a `changes` block is present, it lists commits from the repositories this subject's code lives in, chosen for how closely they match the subject rather than for their type. Each carries a subject line, its conventional type and scope where it has one, whether it is a breaking change, a short SHA, a pull request number, and a date, labeled with the repository it came from when more than one was read.

## What to produce

A deliverable is one document someone will write. For each, decide:

- **path** — a file name in kebab case, no directory, ending `.md`.
- **type** — `concept`, `procedure`, or `reference`. A concept explains what something is and why it matters. A procedure is a task with steps someone follows. A reference is a table or list consulted rather than read.
- **title** — a sentence-case heading. A procedure title opens with an imperative verb, never the `-ing` form.
- **rationale** — one sentence on why this document is needed, naming the gap or finding that justifies it.
- **sources** — the URLs from the findings that this document draws on.
- **requirements** — the numbers of the requirements this document answers, when a `requirements` block is present.

Rules that matter:

- **Plan only what the research supports.** A deliverable with no finding and no gap behind it is invention, and it will be written from nothing. A placement `update` target is support in its own right: the published section it names is the evidence, so a subject nothing has been published about yet can still be planned as a change to that section.
- **A gap is a reason to write, not a reason to stop.** If the sources do not answer a question the topic raises, that is usually a document worth having; say so in the rationale.
- **Do not plan a document that already exists and is correct.** Put a topic in `covered` only when the findings show that the requested state is already published completely and accurately. A finding that calls published content incorrect, conflicting, outdated, or in need of correction requires a deliverable; never put that work in `covered`.
- **Split by type, not by size.** A task and the concept behind it are two documents even when both are short. Never plan one document that explains and instructs.
- **Keep it small.** Three good deliverables beat nine speculative ones.
- **Update before you add.** When placement offers an `update` target that covers the deliverable, take it: a reader already reaches that section, and a new page is one more thing for them to find. Plan a `new` page when placement offers no home, or when the subject needs a different topic type from the section that would carry it.
- **An `update` target means writing is required.** Produce an update deliverable for it; the presence of the existing section is not evidence that the requested correction is already covered.
- **A deliverable that takes a target copies its `guide_url` and `section` verbatim.** Inventing either produces a page the writer refuses.
- **A commit that changes behaviour a published page describes is a reason to plan an update to that page**, whether or not a finding already flagged it.
- **Account for every requirement.** Each one is answered by a deliverable that claims its number, or it goes in `deferred` with the reason nothing in this plan answers it. A requirement no deliverable claims is reported as unanswered whatever the run writes, so claiming one is not a formality: claim it only where the document really does answer it, and defer the rest rather than spreading a number across pages that touch the subject.
- **A breaking commit is a reason to plan a document on its own.** Reader- facing behaviour changed; that stands whether or not the sources found anything else to say about it.

Return JSON and nothing else:

```json
{
  "deliverables": [
    {
      "path": "configure-the-mirror-registry.md",
      "type": "procedure",
      "title": "Configure the mirror registry",
      "rationale": "<one sentence>",
      "kind": "update",
      "target": {"guide_url": "<a guide url from placement>", "section": "8.3.3"},
      "sources": ["<a url from the findings>"],
      "requirements": [1]
    }
  ],
  "covered": ["<a topic the published sources already handle>"],
  "deferred": [{"requirement": 2, "reason": "<why nothing in this plan answers it>"}]
}
```

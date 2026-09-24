You are deciding what documentation to write about a code repository, given what it contains and what is already written about it.

## What you have

```json
{{input}}
```

`modules` is every code module the analyzer found: its path, what kind of thing it is, how many files it holds, the public symbols it exposes, and where a summary exists, what it is for. This is the spine. A document is worth writing because a module exists and exposes something a reader has to understand.

`existing` lists the pages already in the documentation tree, each with its title and its `managed` value. A page marked `manual` belongs to a person and will not be written; a page marked `generated` or `assisted` can be changed.

`history`, when present, is a digest of the repository's recent history: what moved, where it landed, and which areas change most.

`changes`, when present, lists commits chosen for how closely they match the subject. Each carries a subject line, its conventional type and scope where it has one, whether it is a breaking change, a short SHA and a date.

`topic`, when present, narrows the job to one subject. Without it, decide for the repository as a whole.

## What to produce

A deliverable is one document someone will write. For each, decide:

- **path** — a file name in kebab case, no directory, ending `.md`. For an `update`, the path of a page in `existing`.
- **type** — `concept`, `procedure`, or `reference`. A concept explains what something is and why it matters. A procedure is a task with steps someone follows. A reference is a table or list consulted rather than read.
- **title** — a sentence-case heading. A procedure title opens with an imperative verb, never the `-ing` form.
- **kind** — `new` for a page that does not exist, `update` for a page in `existing` that should change.
- **rationale** — one sentence on why this document is needed, naming the module or the change that justifies it.
- **sources** — the module paths this document draws on, copied from `modules`, or the page path when it is an update.

Rules that matter:

- **Plan only what the code supports.** A deliverable no module, symbol or commit stands behind is invention, and it will be written from nothing.
- **Update before you add.** Where `existing` already holds a page covering the subject, plan an update to it rather than a second page: a reader already reaches that one, and a new page is one more thing for them to find.
- **Never plan an update to a `manual` page.** It belongs to a person, the writer will refuse it, and the deliverable is wasted. Plan a new page instead, or leave the subject alone.
- **An `update` path must appear in `existing`, spelled exactly as it is there.** Inventing one produces a page the writer refuses.
- **Split by type, not by size.** A task and the concept behind it are two documents even when both are short. Never plan one document that explains and instructs.
- **Keep it small.** Three good deliverables beat nine speculative ones. A module with four public symbols and no summary is rarely worth its own page.
- **Do not plan a document that already exists and is correct.** Put a subject in `covered` only when `existing` shows it is documented completely and accurately.
- **A breaking commit is a reason to plan a document on its own.** Reader-facing behaviour changed, and that stands whether or not anything else says so.
- **Never plan a page about the repository's history.** A commit is evidence for what is true now. A changelog is generated separately and is not yours to plan.

Return JSON and nothing else:

```json
{
  "deliverables": [
    {
      "path": "configure-the-scheduler.md",
      "type": "procedure",
      "title": "Configure the scheduler",
      "kind": "new",
      "rationale": "<one sentence>",
      "sources": ["pkg/scheduler"]
    }
  ],
  "covered": ["<a subject the existing pages already handle>"]
}
```

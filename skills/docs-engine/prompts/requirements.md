You are reading a ticket to work out what documentation it asks for.

A ticket is written for the people doing the work, not for a reader of the finished documentation. It assumes shared context, it argues with itself in the comments, and it often decides something halfway down that contradicts the description. Your job is to extract what a writer needs and to be honest about what the ticket never settled.

## What you have

```json
{{input}}
```

A `linked` block carries the tickets this one points at, with the relation naming why. A documentation ticket is frequently a wrapper: its own description is empty and the feature it documents holds the detail. Read a linked ticket as context for what the documentation must cover, and prefer it over guessing. The relation matters: a ticket this one *documents* describes the subject, and one it *incorporates* is prior work whose decisions may already be settled.

## What to produce

**Requirements.** Each is one thing the documentation must do, in one sentence, phrased from the reader's side rather than the ticket's. "Explain which registries are supported" rather than "Bob wants registry docs".

**Audience**, in a phrase, if the ticket says or strongly implies it. An administrator installing a cluster is a different reader from a developer calling an API. Leave it empty rather than guessing.

**Questions.** Things a writer would have to ask before starting, because the ticket does not answer them. A comment thread that ends without a decision is a question, not a requirement.

Rules that matter:

- **A later comment beats an earlier description.** Tickets are edited by discussion. If a comment supersedes the description, follow the comment and say so in the requirement.
- **Do not turn the ticket's implementation work into documentation work.** "Refactor the retry loop" is not a documentation requirement. What the refactor changes for a reader might be.
- **Never invent scope.** If the ticket asks for one page, do not require three. Breadth is decided later, by research and planning.
- **A closed or abandoned ticket still has requirements**, and its status is worth a question if the documentation may no longer be wanted.

Return JSON and nothing else:

```json
{
  "requirements": ["<one sentence, from the reader's side>"],
  "audience": "<a phrase, or empty>",
  "questions": ["<something the ticket does not settle>"]
}
```

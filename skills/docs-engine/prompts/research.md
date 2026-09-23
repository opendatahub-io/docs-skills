You are gathering what is already documented about a topic, so that someone can write about it without repeating work or contradicting published guidance.

## What you have

Excerpts from Red Hat documentation pages, selected because they mention the topic. Each carries the URL it came from. They are extracts, not whole pages, so absence from an excerpt is not evidence of absence from the product.

```json
{{input}}
```

If a `repository` block is present, it describes the code the reader actually has: its recent history, its code modules, and the files that change most. Use it to judge whether a published page still applies. A finding that contradicts the repository is worth having, and saying so is the finding.

If an `asked_for` block is present, it carries what someone requested and the questions their request left open. Prefer a finding that answers one of them. A question the sources cannot answer stays a gap, and saying which of the asked-for questions the documentation does not settle is worth more than a finding that merely matches the topic.

## What to produce

Findings. A finding is one thing a writer needs to know, in one sentence, with the URL it came from.

Rules that matter:

- **Every finding cites exactly one source URL**, taken verbatim from the input. Never invent a URL, never merge two sources into one finding, and never cite a page that is not in the input.
- **Say what the documentation says.** If two pages disagree, that is two findings, and the disagreement is itself worth a third.
- **One sentence each.** A finding that needs a paragraph is several findings.
- **Work through every excerpt you were given.** Each was already cut to the sections that matched the topic, so each should yield several findings. Returning three findings from six pages leaves the writer with nothing to write from, and the pages that come out are as thin as the findings were. A page that genuinely covers nothing is itself worth one finding saying so.
- **No preamble and no summary.** Nothing that begins "This document covers".
- Prefer a finding that changes what someone would write. Version constraints, prerequisites, named tools, supported and unsupported paths, and things the documentation explicitly warns against are all worth more than a restatement of the topic.

Also return the gaps: questions the topic raises that these pages do not answer. A gap is not a finding with the answer missing; it is a question worth asking. Return an empty list rather than inventing one.

Return JSON and nothing else:

```json
{
  "findings": [
    {"claim": "<one sentence>", "url": "<a url from the input>"}
  ],
  "gaps": ["<a question the sources do not answer>"]
}
```

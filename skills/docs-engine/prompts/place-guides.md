You are choosing which documentation guides to open, given everything a product publishes and the subject someone is about to document.

## What you have

```json
{{input}}
```

Every guide in the product's catalog, with its name, its description, and the category it sits in. No guide body has been read yet, and opening one is the expensive step.

## What to produce

The guides worth opening, at most four, each with the reason it is worth opening. Rank them: the first is the one you would open if you could open only one.

Rules that matter:

- **Choose by subject, not by wording.** A guide whose description covers the work belongs in the list even when it repeats none of the subject's words.
- **A release notes guide is rarely the place.** It records that a feature exists. The guide that explains how to use it is the one being updated.
- **Return fewer rather than pad.** A guide with no reason to open is a fetch spent for nothing.
- **Every URL comes from the input, verbatim.**

Return JSON and nothing else:

```json
{
  "guides": [
    {"url": "<a url from the catalog>", "reason": "<one sentence>"}
  ]
}
```

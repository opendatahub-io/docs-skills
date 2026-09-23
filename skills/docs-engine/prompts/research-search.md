You are searching for published documentation about a subject, because every search already tried found nothing.

## What you have

```json
{{input}}
```

`tried` lists the queries already run against Red Hat documentation, most specific first. None of them found a page.

## What to produce

Up to three search queries, ordered most promising first. They run inside a product's documentation already pinned to one product and version, so do not name the product or the version in the query itself.

Rules that matter:

- **Search for the thing a page would be titled**, not for the sentence describing the requirement. A query is a few words: the feature's name, the resource or setting it involves, or the task a reader performs with it.
- **Vary the angle rather than the wording.** Three spellings of one idea return the same nothing three times. Try the feature's own name, then the task a reader performs, then the object they configure.
- **Do not repeat a query in `tried`**, and do not return a query that only differs from one by punctuation or case.
- **Return fewer than three rather than pad.**

Return JSON and nothing else:

```json
{"queries": ["<a few words>"]}
```

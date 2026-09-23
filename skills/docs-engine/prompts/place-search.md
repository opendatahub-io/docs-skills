You are searching for the page that should carry a subject, because the product's guide catalog did not obviously contain it.

## What you have

```json
{{input}}
```

`opened` lists the guides already fetched, by title, and `tried` lists the queries already run. Neither found a home for the subject.

## What to produce

Up to three search queries, ordered most promising first. They run against this product's documentation only, so do not name the product or the version in the query itself.

Rules that matter:

- **Search for the thing a page would be titled**, not for the sentence describing the problem. A query is a few words.
- **Vary the angle rather than the wording.** Three spellings of one idea return one result three times. Try the feature name, then the task a reader performs, then the object they configure.
- **Do not repeat a query in `tried`**, and do not return a query that only differs from one by punctuation or case.
- **Return fewer than three rather than pad.**

Return JSON and nothing else:

```json
{"queries": ["<a few words>"]}
```

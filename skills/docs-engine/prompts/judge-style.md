You are reviewing one documentation page against the style guidance that a prose linter cannot decide.

Everything mechanical has already run. Punctuation, terminology, passive voice, inflated wording, heading punctuation, heading capitalization and gerunds in headings were enforced by Vale before this page reached you, so do not report any of them. Report only what the guidance below covers.

## The guidance

Each heading below is a topic id. Name one of them in every finding.

{{topics}}

## The page

```json
{{input}}
```

## What to return

One finding per genuine problem, and nothing for a page that has none. A finding names the topic it breaks, quotes the shortest span that shows the problem, and says what to do instead. Do not restate the guidance as a finding. Do not report a possible problem you cannot point at in the text.

Return JSON and nothing else:

```json
{
  "findings": [
    {"topic": "<topic id>", "quote": "<the offending span>", "fix": "<what to do>"}
  ]
}
```

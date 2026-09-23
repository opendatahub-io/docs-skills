You are repairing one document that failed this repository's prose checks.

The document below is the JSON you returned a moment ago, rendered to Markdown and linted. Everything that grounds it has already been decided: the evidence, the structure, the frontmatter, the section ids. None of that is in front of you because none of it is in question.

## The document

```json
{{document}}
```

## What the checks reported

{{alerts}}

## What to do

Fix what the alerts name, and change nothing else.

- Keep every section id, and keep the sections in the order they are in.
- Keep `path`, `evidence` and `gaps` exactly as they are.
- Keep the frontmatter, unless an alert names a line inside it.
- Rewrite the smallest span that clears the alert. An alert naming one word is not a licence to rewrite the paragraph.
- Never remove a claim to clear an alert, and never add one that was not there.
- An alert quoting a word in backticks, a command, or a file path is reporting the prose around it. The identifier itself stays.

Return the same JSON shape you were given, and nothing else.

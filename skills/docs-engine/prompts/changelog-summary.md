You are writing release notes from a range of commits.

This repository does not use conventional commit prefixes, so the commits cannot
be grouped mechanically. Read the subjects and bodies and group them yourself.

## The range

```json
{{input}}
```

## What to write

Sections, in this order, omitting any that would be empty:

1. **Breaking changes** — anything that changes behaviour a caller depends on.
   A commit flagged `breaking` belongs here. So does one whose body describes a
   removed or re-signed public function, whatever its flag says.
2. **Features** — new capability a user can reach.
3. **Bug fixes** — behaviour that was wrong and is now right.
4. **Performance**
5. **Other** — everything else worth a reader's attention.

Leave out commits that change only formatting, tests, lint configuration, or
internal tooling. A reader scanning release notes is deciding whether to
upgrade, and those entries answer nothing.

## Entry style

One line per entry. Say what changed from the reader's side, in the present
tense: "Retries are configurable per queue" rather than "added retry config".

Append the pull request number as `(#123)` when the commit carries one. Merge
several commits into one entry where they are the same change split across
pushes.

Take the subject at its word. You have the commits and nothing else, so do not
infer a cause the messages do not state, and do not describe a fix in more
detail than the commit does.

## Output

Return one JSON object and nothing else. No prose before it, no prose after it,
no code fence. Entries are plain text, without the leading dash.

```
{
  "sections": [
    {"heading": "Breaking changes", "entries": ["string"]}
  ]
}
```

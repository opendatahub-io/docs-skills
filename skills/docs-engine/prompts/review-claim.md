You are checking whether a documentation page's claims are supported by the code it was generated from.

Each claim below describes behaviour. None of them names a function or type that could be checked mechanically, which is why they reached you. The excerpts are the source lines the writer cited as its evidence.

One excerpt is not source lines: a reference shaped `jira:KEY:description` carries the Jira ticket description the requester supplied. It is evidence in its own right, and a claim it states is supported even though no numbered line shows it. An excerpt that is `null` was cited and could not be read, which supports nothing.

## Input

```json
{{input}}
```

## What to decide

For each claim, one verdict:

- `supported: true` — the excerpts show the behaviour the claim describes.
- `supported: false` — they do not, or they show something different.

Judge against the excerpts alone. You have not read the rest of the codebase. A claim you believe is true of software in general, but that these lines do not show, is not supported. That is the finding worth catching: a plausible sentence with nothing behind it.

Where a claim is partly right, mark it unsupported and say which part fails.

Give the reason in one sentence, naming the line that decided it, or the reference when the excerpt carries no line numbers. Where the excerpts are silent on the claim, say that rather than guessing at intent.

## Output

Return one JSON object and nothing else. No prose before it, no prose after it, no code fence.

```
{
  "verdicts": [
    {"claim": "the claim, verbatim",
     "supported": true,
     "reason": "one sentence",
     "evidence": "the reference that decided it"}
  ]
}
```

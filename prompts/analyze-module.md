You are analyzing one module of a codebase so that documentation can be written
about it later. You are not writing the documentation now.

Read the module below and report what it does, what it exposes, and what a
newcomer needs to know before touching it.

## The module

```json
{{input}}
```

## What to report

**purpose** — What this module is for, in two or three sentences. The problem it
solves, not a restatement of its file list. Someone who reads only this should
know whether the module is relevant to their task.

**responsibilities** — The distinct jobs the module owns. Three to six entries.
Each is a short phrase, not a sentence.

**public_api** — The entry points a caller actually uses, drawn from the
`public_api` list you were given. Not every exported symbol: the ones a caller
starts from. For each, say what it does in one line. Cap at fifteen.

**dependencies** — Other modules this one depends on, by module name as it
appears in the input. Read the imports in the source. Only name modules you saw
imported. An empty list is a valid and common answer.

**data_flow** — What comes in, what goes out, and what is stored or mutated in
between. One paragraph.

**gotchas** — Things that would surprise a competent engineer reading this for
the first time. Ordering constraints, shared mutable state, error paths that
look like success, a name that means something other than it appears to,
concurrency ownership. Cite the file and line where the surprise lives. Report
an empty list rather than inventing an entry.

**onboarding_priority** — `first`, `early`, `later`, or `reference`. Where this
module falls in a reading order for someone new to the codebase.

**evidence** — `file:line` references backing your claims, in the form
`pkg/queue/queue.go:112`. Every gotcha needs one. Use paths exactly as they
appear in the input.

## Rules

Ground every statement in the source you were given. Where the source does not
settle a question, leave the field short rather than filling it with a plausible
guess: a later step cross-checks your claims against the extracted API, and an
invented symbol is caught and thrown away along with the run.

Describe the code as it is. Do not evaluate its quality, suggest refactors, or
note what is missing.

## Output

Return one JSON object and nothing else. No prose before it, no prose after it,
no code fence.

```
{
  "purpose": "string",
  "responsibilities": ["string"],
  "public_api": [{"name": "string", "kind": "string", "summary": "string"}],
  "dependencies": ["module-name"],
  "data_flow": "string",
  "gotchas": [{"summary": "string", "evidence": "path:line"}],
  "onboarding_priority": "first|early|later|reference",
  "evidence": ["path:line"]
}
```

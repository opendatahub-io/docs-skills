You are compacting a batch of code module summaries, so that a later pass can read every module in one go.

## What you have

```json
{{input}}
```

`modules` is a batch of module summaries. Each carries the module's path, what it is for, what it is responsible for, what it depends on, how data moves through it, where it sits in a reading order, the traps in it, and the file and line each claim rests on.

This is one batch of several. You are not writing the guide; you are making this batch small enough to sit alongside the others when the guide is written.

## What to produce

One compact record per module, in the order you were given them.

Rules that matter:

- **Keep every module.** A module you drop is a module the guide will not mention. The output has exactly as many records as the input.
- **Keep the module path verbatim.** It is how the next pass joins your record to the dependency graph.
- **Keep every dependency.** The graph is what the guide is mostly about, and a dropped edge is a relationship nobody sees.
- **Keep every gotcha, whole, with its file and line still attached.** They are the most expensive thing in the input to rediscover, and the first thing a new reader needs.
- **Copy `onboarding_priority` and `data_flow` across unchanged.** The guide orders its reading list by the first and traces its end-to-end flows from the second. Neither is prose to compress, and a module that arrives without them is a module the guide cannot place.
- **Keep the evidence.** Each claim you carry forward keeps the `file:line` it came from. A claim that arrives without one cannot be checked.
- **Compress the prose, not the facts.** `purpose` becomes one sentence. `responsibilities` become short phrases. Nothing that names a symbol, a path, a version or a flag is a candidate for cutting.
- **Drop `public_api` and nothing else.** It is the bulk of what you were given and the guide never reads it. Everything else in the input has a section that needs it.
- **Never infer across modules.** You are seeing part of the repository. A relationship you did not receive is not yours to propose.

Return JSON and nothing else:

```json
{
  "modules": [
    {
      "module": "<the path from the input, unchanged>",
      "purpose": "<one sentence>",
      "responsibilities": ["<short phrase>"],
      "dependencies": ["<a module path from the input>"],
      "data_flow": "<from the input, unchanged>",
      "onboarding_priority": "<first|early|later|reference, from the input, unchanged>",
      "gotchas": [{"summary": "<the trap, kept whole>", "evidence": "<path/to/file.py:12>"}],
      "evidence": ["<path/to/file.py:12>"]
    }
  ]
}
```

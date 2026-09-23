You are compacting a batch of code module summaries, so that a later pass can read every module in one go.

## What you have

```json
{{input}}
```

`modules` is a batch of module summaries. Each carries the module's path, what it is for, what it is responsible for, what it depends on, the traps in it, and the file and line each claim rests on.

This is one batch of several. You are not writing the guide; you are making this batch small enough to sit alongside the others when the guide is written.

## What to produce

One compact record per module, in the order you were given them.

Rules that matter:

- **Keep every module.** A module you drop is a module the guide will not mention. The output has exactly as many records as the input.
- **Keep the module path verbatim.** It is how the next pass joins your record to the dependency graph.
- **Keep every dependency.** The graph is what the guide is mostly about, and a dropped edge is a relationship nobody sees.
- **Keep every gotcha.** They are the most expensive thing in the input to rediscover, and the first thing a new reader needs.
- **Keep the evidence.** Each claim you carry forward keeps the `file:line` it came from. A claim that arrives without one cannot be checked.
- **Compress the prose, not the facts.** `purpose` becomes one sentence. `responsibilities` become short phrases. Nothing that names a symbol, a path, a version or a flag is a candidate for cutting.
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
      "gotchas": ["<the trap, kept whole>"],
      "evidence": ["<path/to/file.py:12>"]
    }
  ]
}
```

# Get started

One path through the software, from nothing to a result the reader can see.

## Rules for this page

- One path only. Where two ways exist, pick the one that works for the most
  readers and leave the other to a how-to page.
- Every step produces something the reader can observe. A step whose effect is
  invisible belongs inside the step before it.
- Show expected output after any step whose result is not obvious. A reader who
  cannot tell whether a step worked has no way back.
- Every command comes from `allowed_commands`. A command absent from that list
  is one nothing in the repository declares, and printing it sends the reader
  somewhere that does not exist.
- State prerequisites with their versions, from `prerequisites`.
- No alternatives, no options, no asides about how the internals work.
- End at a working thing, then name what to read next.

## Shape

## Prerequisites

The versions and tools a reader needs, each with the value the repository
states.

## Procedure

1. One action, beginning with an imperative verb.

   ```bash
   make build
   ```

2. The next action.

   ```console
   $ make test
   ok      example/pkg     0.4s
   ```

## Verification

How the reader confirms the whole thing worked, with the output that proves it.

## Next steps

Two or three links into the rest of the documentation, each saying what the
reader will find.

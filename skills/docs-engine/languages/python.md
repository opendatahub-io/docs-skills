---
language: python
extensions: [.py, .pyi]
docs_dir: docs
artifacts:
  library: [concept, task]
  service: [concept, task, overview]
  cli: [task]
reference_generator:
  tool: pdoc
  command: "pdoc --output-directory {out} {package}"
  produces: reference
  url: https://pdoc.dev
doc_comment:
  format: google
  writable: false
  url: https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings
test_globs:
  - "test_*.py"
  - "*_test.py"
  - "tests/**/*.py"
---

# Documenting Python

## Where documentation lives

A package publishes prose under `docs/`, with `README.md` at the root carrying
installation and a first example. Import paths in prose are written as the user
would type them, so `myproject.scheduler.Queue` rather than
`src/myproject/scheduler/queue.py`.

A module that ships a `py.typed` marker is declaring its annotations part of the
public contract. Document the types as part of the signature.

## Defer to pdoc

pdoc renders signatures, type annotations, inheritance, and every docstring
already in the source. It does that better than prose written from an API
listing, and it never goes stale. Do not write a reference page that restates a
signature.

What pdoc cannot produce, and what belongs here:

- Why the module exists and which problem it solves
- How its pieces fit together, and what calls what
- Getting from an empty file to a working call
- Which of several plausible entry points is the intended one
- Failure modes, and what a caller does about them

## Docstrings

Google style, as the `doc_comment` field records. Summary line in the
imperative, blank line, then `Args:`, `Returns:`, and `Raises:` sections.

The plugin reports missing or thin docstrings as a gap and does not write them.
A docstring change is a change to source, which lands in code review under
different ownership than a documentation change.

## Examples

Take examples from tests before inventing them. `test_*.py` and `tests/` hold
the API being called for real, with the imports and the setup a reader needs.
An invented example rots on the next signature change; one lifted from a test
breaks the test suite first.

Prefer a doctest-shaped example when the call is short enough to fit:

```python
>>> from myproject.scheduler import Queue
>>> queue = Queue(retries=3)
>>> queue.submit("job-1")
'job-1'
```

Reach for a fenced block with imports and setup when the example needs more than
a few lines. Every example carries its imports. A reader who cannot copy the
block into a file and run it has been given a fragment.

## Naming in prose

Class names keep their casing: `Queue`, `HTTPAdapter`. Functions and methods are
written with their parentheses on first mention, `submit()`, and without
afterwards. Module and package names stay lowercase. Backtick every identifier.

Write "the `retries` argument", not "the retries parameter". Argument is what
Python's own documentation calls it.

## Kind by kind

**Library.** A concept page for the module's purpose and design, a task page for
getting started. Reference comes from pdoc.

**Service.** Add an overview page covering the process model, configuration, and
what the service talks to. Environment variables and settings objects belong
there rather than in a per-module concept page.

**CLI.** A task page per real job the tool does. Command syntax comes from
`--help` output, which stays correct on its own. Document what a reader is
trying to accomplish, not the flag list.

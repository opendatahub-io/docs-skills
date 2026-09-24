---
language: go
extensions: [.go]
docs_dir: docs
artifacts:
  library: [concept, procedure]
  service: [concept, procedure, overview]
  cli: [procedure]
reference_generator:
  tool: godoc
  command: "go doc -all {package}"
  produces: reference
  url: https://pkg.go.dev
doc_comment:
  format: godoc
  writable: false
  url: https://go.dev/doc/comment
test_globs:
  - "*_test.go"
---

# Documenting Go

## Where documentation lives

Package documentation belongs in the source, as a comment on the package clause, conventionally in `doc.go` when it runs longer than a few lines. pkg.go.dev renders it for anyone who imports the package.

Prose that does not fit a package comment goes under `docs/`. That covers architecture spanning several packages, operational guides for a service, and anything a reader needs before they know which package to import.

Import paths in prose are the full module path, `github.com/org/repo/pkg/queue`, because that is what a reader types into an import block.

## Defer to pkg.go.dev

`go doc` and pkg.go.dev already render every exported symbol with its signature and its doc comment. Writing a reference page duplicates a listing that regenerates itself on every push.

What belongs in prose instead:

- Which packages a newcomer reads first, and in what order
- How the packages compose, and where the boundaries fall
- Concurrency ownership: who starts a goroutine, who closes a channel, what a caller must not do from more than one goroutine
- Configuration and deployment for a service
- Error semantics: which errors are sentinel values worth `errors.Is`, which wrap, and what a caller does with each

## Doc comments

Go's convention, as the `doc_comment` field records. A complete sentence beginning with the identifier's own name: `// Submit enqueues a job and returns its assigned id.` No `Args:` or `Returns:` block; Go's tooling reads the signature.

The plugin reports exported symbols missing a doc comment as a gap and does not write them. Editing source puts a docs run into code review with different ownership.

## Examples

`Example_*` functions in `*_test.go` are the idiomatic source. They compile, they run under `go test`, and pkg.go.dev renders them beside the symbol they document. Cite one rather than writing a fenced block that no compiler checks.

```go
func ExampleQueue_Submit() {
	q := queue.New(queue.WithRetries(3))
	id, err := q.Submit(context.Background(), "job-1")
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(id)
	// Output: job-1
}
```

Where prose needs an inline snippet, handle the error. A Go example that drops an error teaches the wrong habit and would not pass review in the codebase it documents.

## Naming in prose

Exported identifiers keep their casing: `Queue`, `ServeHTTP`. Package names stay lowercase and are written bare, `queue`, with the full import path given on first mention. Interfaces are named as themselves, `io.Reader`, without an article: "a type implementing `io.Reader`".

Write "the `ctx` parameter". Go's own documentation says parameter.

Initialisms keep their case throughout, so `HTTPServer` and `ID` and `URL`, in prose exactly as in source.

## Kind by kind

**Library.** A concept page for what the package family is for and how the packages relate. A procedure page for getting from `go get` to a working call. Reference comes from pkg.go.dev.

**Service.** Add an overview page: process model, flags and environment, readiness and liveness behaviour, and the services it depends on. A `cmd/` directory usually marks the entry point worth documenting first.

**CLI.** A procedure page per job the tool does. Flag listings come from the tool's own `--help`, which cannot drift. Cobra command trees give a natural page split.

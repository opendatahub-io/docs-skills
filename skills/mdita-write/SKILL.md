---
name: mdita-write
description: Write Markdown DITA topics and maps, then convert to DITA XML using DITA-OT with the org.lwdita plugin. Use when asked to create DITA documentation, write Markdown DITA topics, generate concept/task/reference content, create DITA maps, or convert Markdown to DITA XML.
allowed-tools: Bash, Read, Write, Edit, Glob
argument-hint: "[topic-type] [description]"
---

# Markdown DITA writing and conversion skill

Resolve relative paths against this skill's directory. For platform mappings, read [runtime compatibility](../../reference/runtime-compatibility.md).

Write Markdown DITA topics and maps, then convert them to DITA XML using DITA-OT with the `org.lwdita` plugin.

## Prerequisites

Requires Java 17+, DITA-OT 4.x, and the `org.lwdita` plugin, version 6.0.0. Install the plugin from the [v6.0.0 release](https://github.com/aireilly/org.lwdita/releases/tag/v6.0.0):

```bash
dita install https://github.com/aireilly/org.lwdita/releases/download/v6.0.0/org.lwdita-6.0.0.zip
```

To verify the download before installing, check its SHA-256 against the expected value:

```bash
curl -sL https://github.com/aireilly/org.lwdita/releases/download/v6.0.0/org.lwdita-6.0.0.zip | sha256sum
# expected: bcec1d72dfc2597107a8a937c27a2ac5b32bb9833a2ef17813c22f7722b501db
```

The conversion script checks for Java, DITA-OT, and the plugin, and reports what to install if anything is missing.

## Synopsis

```
/mdita-write                           # Interactive: ask what to write
/mdita-write concept <description>     # Write a concept topic
/mdita-write task <description>        # Write a task topic
/mdita-write reference <description>   # Write a reference topic
/mdita-write map <description>         # Write a Markdown DITA map
/mdita-write convert <file>            # Convert existing Markdown DITA to DITA XML
```

## Reference files

Read these before writing Markdown DITA content:

- [Markdown DITA syntax reference](reference/markdown-dita-syntax.md): front matter, topic types, block elements, maps
- [Concept topic example](reference/markdown-dita-concept.md): nested topics, tables, definition lists, code blocks, admonitions
- [Task topic example](reference/markdown-dita-task.md): prerequisites, context, steps with substeps and choices, verification, and next steps section headings
- [Reference topic example](reference/markdown-dita-reference.md): lookup tables, definition lists, code blocks, admonitions
- [Map example](reference/markdown-dita-map.mditamap): topic references, topic heads, ordered sequences, relationship tables

## Usage workflow

When asked to write Markdown DITA content:

1. **Determine the topic type**: concept (explains what), task (explains how), or reference (lookup info)
2. **Read the syntax reference** and the matching example file for the correct structure
3. **Write the Markdown DITA file** using the `.md` extension and set the topic type with an H1 class: `# Title {.concept}`, `{.task}`, or `{.reference}`
4. **Convert to DITA XML** using the conversion script
5. **Fix issues and retry**: the conversion script also runs `dita validate` against each generated file, so a `"status": "error"` result can mean either a failed transform or DTD-invalid output (for example a task with two `<result>` elements, which the `org.lwdita` transform will serialize without complaint since it doesn't reparse its own output against the DTD). Read the reported error, adjust the Markdown source, and reconvert. Loop until `"status": "success"` — that status is the only signal that the output is genuinely DTD-valid DITA, so do not report the task done before reaching it.

## Conversion to DITA XML

After writing Markdown DITA files, convert them to DITA XML using the conversion script:

```bash
bash scripts/mdita_convert.sh <input> [output_dir]
```

Arguments:

- `input`: path to a `.md` or `.mditamap` file (not a directory; use a map to convert multiple topics at once)
- `output_dir`: output directory (default: `./dita-output`). The script clears prior `.dita` and `.ditamap` files here before converting

The script outputs JSON with the conversion results, always including a `status` field:

```json
{"status": "success", "dita_version": "DITA-OT version 4.3.1", "input": "guide.mditamap", "output_dir": "./dita-output", "file_count": 2, "files": ["dita-output/topic.dita", "dita-output/guide.ditamap"]}
```

On failure (missing prerequisites, invalid input, or a conversion error), the script exits non-zero and emits `{"status": "error", "error": "..."}` or, once prerequisites are met, `{"status": "error", "dita_version": "...", "input": "...", "output_dir": "...", "stderr": "..."}`.

The script also validates every generated `.dita`/`.ditamap` file against its DTD with `dita validate`. If that fails — the transform can produce structurally invalid output (for example two `<result>` elements in a task) without itself failing — the script reports `{"status": "error", "dita_version": "...", "input": "...", "output_dir": "...", "error": "Generated DITA is not valid against its DTD...\n<file>:\n<dita validate output>"}`. Treat this the same as a conversion failure: fix the Markdown source and reconvert.

## Example invocations

- "Write a Markdown DITA concept topic about container orchestration"
- "Create a Markdown DITA task for installing a command-line tool"
- "Write a Markdown DITA reference topic for CLI command options"
- "Create a Markdown DITA map for a product guide"
- "Convert this Markdown file to DITA XML"
- "Write a task topic with prerequisites and verification steps"

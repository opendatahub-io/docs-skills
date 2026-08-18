---
name: mdita-write
description: Write Markdown DITA topics and maps, then convert to DITA XML using DITA-OT with the org.lwdita plugin. Use when asked to create DITA documentation, write Markdown DITA topics, generate concept/task/reference content, create DITA maps, or convert Markdown to DITA XML.
allowed-tools: Bash, Read, Write, Edit, Glob
argument-hint: "[topic-type] [description]"
---

# Markdown DITA writing and conversion skill

Write Markdown DITA topics and maps, then convert them to DITA XML using DITA-OT with the `org.lwdita` plugin.

## Prerequisites

Requires Java 17+, DITA-OT 4.x, and the `org.lwdita` plugin. The conversion script checks for all three and reports what to install if anything is missing.

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
- [Concept topic example](reference/markdown-dita-concept.md): sections, tables, definition lists, admonitions
- [Task topic example](reference/markdown-dita-task.md): prerequisites, context, steps with substeps and choices, verification, next steps
- [Reference topic example](reference/markdown-dita-reference.md): lookup tables, definition lists, admonitions
- [Map example](reference/markdown-dita-map.mditamap): topic references, topic heads, ordered sequences, relationship tables

## Usage workflow

When asked to write Markdown DITA content:

1. **Determine the topic type**: concept (explains what), task (explains how), or reference (lookup info)
2. **Read the syntax reference** and the matching example file for the correct structure
3. **Write the Markdown DITA file** using the `.md` extension with the appropriate `$schema` in YAML front matter
4. **Convert to DITA XML** using the conversion script to validate the output
5. **Fix issues**: if conversion fails, adjust the source and retry

## Conversion to DITA XML

After writing Markdown DITA files, convert them to DITA XML using the conversion script:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/mdita_convert.sh <input> [output_dir]
```

Arguments:

- `input`: path to a `.md` or `.mditamap` file (not a directory; use a map to convert multiple topics at once)
- `output_dir`: output directory (default: `./dita-output`). The script clears prior `.dita` and `.ditamap` files here before converting

The script outputs JSON with the conversion results:

```json
{"status": "success", "dita_version": "DITA-OT 4.2.3", "input": "guide.mditamap", "output_dir": "./dita-output", "file_count": 2, "files": ["dita-output/topic.dita", "dita-output/guide.ditamap"]}
```

## Example invocations

- "Write a Markdown DITA concept topic about container orchestration"
- "Create a Markdown DITA task for installing a command-line tool"
- "Write a Markdown DITA reference topic for CLI command options"
- "Create a Markdown DITA map for a product guide"
- "Convert this Markdown file to DITA XML"
- "Write a task topic with prerequisites and verification steps"

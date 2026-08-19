# Markdown DITA syntax reference

Complete syntax reference for Markdown DITA as processed by the `org.lwdita` DITA-OT plugin, version 6.0.0. This describes the Markdown DITA format documented in the [DITA-OT reference](https://www.dita-ot.org/dev/reference/markdown/markdown-dita-syntax).

## Topic type

The topic type is set by a class on the H1 heading, using Pandoc-style header attributes:

```markdown
# Installing the tool {.task}
```

| H1 class | Topic type |
|----------|------------|
| `{.concept}` | Concept (explanatory content) |
| `{.task}` | Task (step-by-step procedures) |
| `{.reference}` | Reference (lookup information) |
| *(no class)* | Generic topic |

The class also sets the topic `@id` from the title (for example, `# Installing the tool {.task}` produces `id="installing-the-tool"`). To set an explicit id, use the `id:` field in the YAML front matter or combine attributes on the heading: `# Installing the tool {#install-tool .task}`.

> The `$schema` YAML field is an alternative way to select a topic type, but it routes the file through a reduced parser that does **not** support `!!!` admonitions. Use the H1 class for topics and reserve `$schema` for maps (see [Maps](#maps)).

## YAML front matter

Front matter is optional for topics. When present, its keys map to DITA `<prolog>` metadata:

```yaml
---
id: installing-cli
author: Documentation Team
category: Installation
keyword:
  - cli
  - installation
---
```

| YAML key | DITA output |
|----------|-------------|
| `id` | Topic `@id` attribute |
| `author` | `<author>` |
| `source` | `<source>` |
| `publisher` | `<publisher>` |
| `permissions` | `<permissions @view="...">` |
| `audience` | `<audience @type="...">` (inside `<metadata>`) |
| `category` | `<category>` (inside `<metadata>`) |
| `keyword` | `<keyword>` (inside `<metadata><keywords>`) |
| *(any other key)* | `<data name="..." value="..."/>` |

## Topic structure

The H1 heading becomes the topic title. The first paragraph after the H1 becomes the `<shortdesc>`. Content that follows becomes the topic body. If there is no paragraph directly under the H1 (for example, the next line is a heading or a table), no `<shortdesc>` is generated.

Every heading below H1 creates a **nested topic**, not a section. An H2 creates a topic nested inside the H1 topic; an H3 creates a topic nested inside the H2 topic, and so on. Each nested topic takes the same type as its parent (a concept nests concepts, a task nests tasks).

```markdown
# Topic title {.concept}

Body content for the top-level topic.

## Nested topic

Body content for the nested topic.

### Deeper nested topic

This H3 creates a topic nested inside the H2 topic.
```

You cannot author a `<section>` with a heading. The processor wraps some block content (such as definition lists and blockquotes that follow other content) in a `<section>` automatically.

## Concept topics

Use concept topics for explanatory content — what something is, why it matters, how it works. Each heading below H1 creates a nested `<concept>` topic.

```markdown
# About containers {.concept}

Containers package applications with their dependencies for consistent deployment.

## Architecture

Container runtime manages isolated processes using kernel features.

## Benefits

- Consistent environments across development and production
- Resource efficiency compared to virtual machines
- Fast startup times
```

## Task topics

Use task topics for step-by-step procedures. Task semantics come from the **body structure**, not from headings. Write the whole procedure in the topic body with no H2 headings. Any H2 heading in a task creates a nested `<task>` topic instead of a task section, so avoid headings within a single procedure.

The processor maps the body content by position:

| Body content | DITA element |
|--------------|--------------|
| First paragraph after H1 | `<shortdesc>` |
| Paragraph(s) between the short description and the first list | `<context>` |
| Ordered list | `<steps>` |
| Paragraph(s) after the list | `<result>` |

### Step mapping

Within the ordered list, list structure maps to task step elements:

| Markdown construct | DITA element |
|--------------------|--------------|
| Ordered list | `<steps>` |
| List item | `<step>` |
| First paragraph in item | `<cmd>` (the command) |
| Additional paragraphs in item | `<info>` (supplemental info) |
| Nested ordered list | `<substeps>` / `<substep>` |
| Nested unordered list in a step | `<ul>` / `<li>` |
| Body-level unordered list (in place of the ordered list) | `<steps-unordered>` |

There is no Markdown construct that produces `<prereq>` or `<postreq>`. State prerequisites in the short description or context paragraph, and put follow-up actions in the trailing result paragraph.

### Task example

```markdown
# Installing the command-line tool {.task}

Install the CLI tool to manage resources from the terminal.

The installation downloads a binary and installs it to your system path. Before
you start, make sure you have administrator privileges and a network connection.

1. Download the installer for your platform.

2. Run the installer with administrator privileges.

   Additional information about the installation step.

3. Generate an API key with these substeps:

   1. Navigate to the settings page.
   2. Click **Create API Key**.
   3. Save the key securely.

4. Choose an authentication method:

   - Use environment variables for automated systems
   - Use a configuration file for interactive sessions
   - Use command-line flags for one-time operations

Run `tool --version` to confirm the installation succeeded, then configure
authentication credentials using `tool login`.
```

The first paragraph becomes `<shortdesc>`, the following paragraph becomes `<context>`, the ordered list becomes `<steps>` (with `<substeps>` and a nested `<ul>`), and the trailing paragraph becomes `<result>`.

## Reference topics

Use reference topics for lookup information — API references, command options, parameter lists, configuration tables.

```markdown
# Command-line reference {.reference}

The following commands manage connection operations.

| Command | Description | Example |
|---------|-------------|---------|
| connect | Establish connection | `tool connect --url https://api.example.com` |
| disconnect | Close connection | `tool disconnect` |
| status | Show connection status | `tool status` |
```

## Maps

Map files organize topics into a hierarchy. Use the `.mditamap` extension and the `$schema: urn:oasis:names:tc:dita:xsd:map.xsd` front matter to identify the file as a map:

```markdown
---
$schema: urn:oasis:names:tc:dita:xsd:map.xsd
---

# Product documentation

- [Welcome](welcome.md)
- Getting started
  - [Prerequisites](prereqs.md)
  - [Installation](install.md)
- Administration
  - [User management](users.md)
  - [Backup and recovery](backup.md)
```

When a map references Markdown topics, DITA-OT parses them as Markdown DITA. A referenced `.md` file is recognized by its extension in this context; inside a hand-written DITA map, use `format="markdown"` (or `format="md"`) on the `<topicref>` because the extension is not consulted there.

### Map element mapping

| Markdown construct | DITA element | Notes |
|--------------------|--------------|-------|
| Bullet item with link | `<topicref>` | Links to a topic file |
| Bullet item without link | `<topichead>` with `<navtitle>` | Navigation heading without topic |
| Ordered list items | `<topicref>` with `collection-type="sequence"` | Sequential reading order |
| Nested bullet lists | Nested `<topicref>` hierarchy | Sub-topics |
| Trailing table | `<reltable>` | Relationship table |

### Map with relationship table

```markdown
---
$schema: urn:oasis:names:tc:dita:xsd:map.xsd
---

# Documentation map

- [Concepts](concepts/index.md)
- [Tasks](tasks/index.md)

| Concepts | Tasks |
|----------|-------|
| [About feature](concepts/about.md) | [Enable feature](tasks/enable.md) |
| [Architecture](concepts/arch.md) | [Configure feature](tasks/configure.md) |
```

## Admonitions

Admonitions use the Material for MkDocs `!!!` syntax. Put the type keyword after `!!!`, leave a blank line, then indent the content by four spaces:

```markdown
!!! note

    General information for the reader.

!!! warning "Backup required"

    A warning with a custom title.

!!! tip

    A helpful suggestion.
```

Each admonition maps to a `<note>` element. The keyword sets the `@type` attribute (for example, `!!! tip` produces `<note type="tip">`). The blank line after the `!!!` marker is required; without it the marker passes through as literal text.

Standard DITA note types include `note`, `tip`, `fastpath`, `restriction`, `important`, `remember`, `attention`, `caution`, `notice`, `danger`, `warning`, and `trouble`.

## Definition lists

Definition lists use the term + `:   definition` syntax:

```markdown
API
:   Application Programming Interface. A contract for software interaction.

REST
:   Representational State Transfer. An architectural style for web services.
```

Maps to DITA `<dl>` with `<dlentry>`, `<dt>` (term), and `<dd>` (definition).

## Fenced code blocks

Triple backticks with a language identifier create `<codeblock>` elements with `outputclass="language-*"`:

````markdown
```bash
#!/bin/bash
echo "Hello, world!"
```

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
```
````

## Tables

Pipe tables map to CALS `<table>` elements (not simpletable, unlike the MDITA core profile):

```markdown
| Command | Description | Example |
|---------|-------------|---------|
| `start` | Start the service | `tool start` |
| `stop` | Stop the service | `tool stop` |
| `status` | Check service status | `tool status` |
```

Tables support header rows and column alignment using standard Markdown table syntax.

## Blockquotes

The `>` prefix creates `<lq>` (long quote) elements:

```markdown
> Container orchestration automates deployment, scaling, and management of
> containerized applications.
```

## Images

Image syntax maps to DITA `<image>` elements:

```markdown
![Architecture diagram](images/architecture.png)

![Workflow diagram](images/workflow.svg "Deployment workflow")
```

- `![alt text](url)` → `<image href="url">` with a nested `<alt>` element
- When a title is present (`"title"`), the image is wrapped in a `<fig>` with a `<title>`
- A block-level image (the sole child of a paragraph) gets `placement="break"`
- An inline image has no `placement` attribute

## Links

Link syntax maps to `<xref>` elements:

```markdown
See the [installation guide](install.md) for details.

Visit the [product website](https://example.com) for more information.
```

- `[text](url)` → `<xref href="url">`
- Absolute URLs get `scope="external"` and `format="html"`
- A `.pdf` target gets `format="pdf"`
- Relative links remain relative and carry no `format` attribute

## Inline elements

Standard Markdown inline formatting maps to DITA elements:

| Markdown | DITA element | Example |
|----------|--------------|---------|
| `**bold**` | `<b>` | **important text** |
| `*italic*` or `_italic_` | `<i>` | *emphasized text* |
| `` `code` `` | `<codeph>` | `variable_name` |
| `~~strikethrough~~` | `<line-through>` | ~~deprecated feature~~ |
| `^superscript^` | `<sup>` | 2^10^ |
| `~subscript~` | `<sub>` | H~2~O |

Multiple inline elements can be combined: `` **bold `code`** `` produces `<b><codeph>code</codeph></b>`.

Do **not** use the `++inserted++` syntax. The parser recognizes it but has no DITA renderer for it, so it aborts the build with `No renderer configured for ...ext.ins.Ins`.

## Footnotes

Footnote syntax creates `<fn>` elements:

```markdown
Containers provide isolation[^1] and resource limits[^2].

[^1]: Isolation uses kernel namespaces and cgroups.
[^2]: CPU and memory limits prevent resource exhaustion.
```

- `[^id]` in body text creates an `<fn callout="...">` reference
- `[^id]: text` at the end of the file defines the footnote content

## Header attributes

Headings support `{#id .class}` attribute syntax:

```markdown
## Installation steps {#install .procedure}
```

- `{#id}` sets the `@id` attribute on the nested topic
- `{.class}` sets the `@outputclass` attribute (on H1, the built-in classes `concept`, `task`, and `reference` set the topic type instead)
- Multiple attributes can be combined: `{#my-id .my-class}`

## Raw DITA XML

Inline DITA XML elements can be embedded directly:

```markdown
Click the <uicontrol>Save</uicontrol> button to continue.

Use the <filepath>/etc/config.yaml</filepath> file for configuration.

The <ph>placeholder phrase</ph> can contain <b>formatted text</b>.
```

Supported inline elements include:

- `<uicontrol>` — UI controls (buttons, menu items)
- `<filepath>` — File paths
- `<cmdname>` — Command names
- `<varname>` — Variable names
- `<ph>` — Generic phrase element
- `<shortcut>` — Keyboard shortcuts
- `<systemoutput>` — Command output
- `<userinput>` — User input

## Conversion notes

- The output DITA file takes its name from the input file (`install.md` → `install.dita`), not from the topic `id`.
- Convert a `.md` topic directly, or reference it from a `.mditamap` to convert several topics at once.

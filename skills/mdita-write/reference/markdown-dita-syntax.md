# Markdown DITA syntax reference

Complete syntax reference for Markdown DITA as processed by the `org.lwdita` DITA-OT plugin in Markdown DITA mode.

## YAML front matter

Every Markdown DITA topic starts with YAML front matter. The `$schema` field with a DITA URI triggers Markdown DITA processing mode and determines the topic type:

```yaml
---
$schema: urn:oasis:names:tc:dita:xsd:concept.xsd
id: my-topic-id
author: Documentation Team
category: User Guide
keyword:
  - container
  - orchestration
  - deployment
---
```

### Schema URIs by topic type

| `$schema` value | Topic type |
|-----------------|------------|
| `urn:oasis:names:tc:dita:xsd:concept.xsd` | Concept (explanatory content) |
| `urn:oasis:names:tc:dita:xsd:task.xsd` | Task (step-by-step procedures) |
| `urn:oasis:names:tc:dita:xsd:reference.xsd` | Reference (lookup information) |
| `urn:oasis:names:tc:dita:xsd:topic.xsd` | Generic topic |

### Metadata field mapping

YAML metadata fields map to DITA `<prolog>` elements:

| YAML key | DITA element | Example |
|----------|--------------|---------|
| `id` | Topic `@id` attribute | `id: installing-cli` |
| `author` | `<author>` | `author: Jane Smith` |
| `source` | `<source>` | `source: https://example.com/spec` |
| `publisher` | `<publisher>` | `publisher: ACME Corp` |
| `permissions` | `<permissions @view="...">` | `permissions: internal` |
| `audience` | `<audience @type="...">` | `audience: administrator` |
| `category` | `<category>` | `category: Installation` |
| `keyword` | `<keyword>` (inside `<keywords>`) | `keyword: [cli, install]` |
| `resourceid` | `<resourceid @appid="...">` | `resourceid: CLI-INSTALL-001` |
| *(other)* | `<data name="..." value="..."/>` | `custom_field: value` |

## Topic structure

The H1 heading becomes the topic title. The first paragraph after the H1 becomes `<shortdesc>`. H2 headings create sections in concept and reference topics, or specialized task sections in task topics. H3 and deeper headings create nested topics (not sections).

```markdown
# Topic title

This first paragraph becomes the short description.

## Section heading

Section content with paragraphs, lists, tables, code blocks.

## Another section

More content.

### Nested topic

This H3 creates a nested topic, not a section within "Another section".
```

## Concept topics

Use concept topics for explanatory content — what something is, why it matters, how it works. H2 headings create `<section>` elements. H3+ headings create nested topics.

```markdown
---
$schema: urn:oasis:names:tc:dita:xsd:concept.xsd
id: about-containers
---

# About containers

Containers package applications with their dependencies for consistent deployment.

## Architecture

Container runtime manages isolated processes using kernel features.

## Benefits

- Consistent environments across development and production
- Resource efficiency compared to virtual machines
- Fast startup times
```

## Task topics

Use task topics for step-by-step procedures. Markdown DITA recognizes four special H2 section titles that map to specialized task elements:

| Heading text | DITA element | Purpose |
|--------------|--------------|---------|
| Prerequisites | `<prereq>` | Requirements before starting |
| About this task | `<context>` | Background and procedure overview |
| Verification | `<result>` | How to verify success |
| Next steps | `<postreq>` | What to do after completion |

### Step mapping

Ordered lists map to DITA task step structures:

| Markdown construct | DITA element |
|--------------------|--------------|
| Ordered list | `<steps>` |
| List item | `<step>` |
| First paragraph in item | `<cmd>` (the command) |
| Additional paragraphs in item | `<info>` (supplemental info) |
| Nested ordered list | `<substeps>` / `<substep>` |
| Nested unordered list | `<choices>` / `<choice>` |
| Body-level unordered list | `<steps-unordered>` |

### Task example with sections

```markdown
---
$schema: urn:oasis:names:tc:dita:xsd:task.xsd
id: installing-tool
---

# Installing the command-line tool

Install the CLI tool to manage resources from the terminal.

## Prerequisites

- Linux, macOS, or Windows system
- Administrator privileges
- Network connection

## About this task

The installation downloads a binary and installs it to your system path.

1. Download the installer for your platform.

2. Run the installer with administrator privileges.

   Additional information about the installation step.

3. Verify the installation.

## Verification

Run `tool --version` to confirm the installation succeeded.

## Next steps

Configure authentication credentials using `tool login`.
```

### Task example without section headings

When an ordered list appears at the body level (not under any H2 heading), it produces specialized `<steps>` elements with full task semantics:

```markdown
---
$schema: urn:oasis:names:tc:dita:xsd:task.xsd
id: configuring-auth
---

# Configuring authentication

Configure authentication credentials for API access.

1. Create a configuration directory.

2. Generate an API key with these substeps:

   1. Navigate to the settings page.
   2. Click **Create API Key**.
   3. Save the key securely.

3. Choose an authentication method:

   - Use environment variables for automated systems
   - Use a configuration file for interactive sessions
   - Use command-line flags for one-time operations

4. Test the connection.
```

## Reference topics

Use reference topics for lookup information — API references, command options, parameter lists, configuration tables.

```markdown
---
$schema: urn:oasis:names:tc:dita:xsd:reference.xsd
id: cli-commands
---

# Command-line reference

Complete reference for all CLI commands.

## Connection commands

| Command | Description | Example |
|---------|-------------|---------|
| connect | Establish connection | `tool connect --url https://api.example.com` |
| disconnect | Close connection | `tool disconnect` |
| status | Show connection status | `tool status` |

## Common flags

All commands support these flags.
```

## Maps

Map files organize topics into a hierarchy. Use the `.mditamap` extension and `$schema: urn:oasis:names:tc:dita:xsd:map.xsd`:

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

[product]: https://example.com/product
```

### Map element mapping

| Markdown construct | DITA element | Notes |
|--------------------|--------------|-------|
| Bullet item with link | `<topicref>` | Links to a topic file |
| Bullet item without link | `<topichead>` with `<navtitle>` | Navigation heading without topic |
| Ordered list items | `<topicref collection-type="sequence">` | Sequential reading order |
| Nested bullet lists | Nested `<topicref>` hierarchy | Sub-topics |
| Reference-style link at end | `<keydef>` | Key definition for reuse |
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

Fenced syntax with `!!!` creates `<note>` elements with `@type` attributes:

```markdown
!!! note
    This is a note without a title.

!!! warning "Backup required"
    This is a warning with a custom title.

!!! tip
    Tips provide helpful suggestions.
```

### Admonition types

All standard DITA note types are supported:

| Type | Use for |
|------|---------|
| `note` | General information |
| `tip` | Helpful suggestions |
| `fastpath` | Shortcuts or efficiency tips |
| `restriction` | Limitations or constraints |
| `important` | Critical information |
| `remember` | Key points to recall |
| `attention` | Important warnings |
| `caution` | Potential problems |
| `notice` | Legal or policy notices |
| `danger` | Physical harm warnings |
| `warning` | Data loss or system damage warnings |
| `trouble` | Troubleshooting information |

Other values produce `type="other" othertype="<value>"`.

## Definition lists

Definition lists use the term + `:   definition` syntax:

```markdown
API
:   Application Programming Interface. A contract for software interaction.

REST
:   Representational State Transfer. An architectural style for web services.

JSON
:   JavaScript Object Notation. A lightweight data interchange format.
```

Maps to DITA `<dl>` with `<dlentry>`, `<dt>` (term), and `<dd>` (definition).

## Fenced code blocks

Triple backticks with a language identifier create `<codeblock>` elements with `outputclass="language-*"`:

````markdown
```bash
#!/bin/bash
echo "Hello, world!"
```

```python
def greet(name):
    print(f"Hello, {name}!")
```

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
```
````

## Tables

Pipe tables map to CALS `<table>` elements (not simpletable, unlike MDITA core profile):

```markdown
| Command | Description | Example |
|---------|-------------|---------|
| `start` | Start the service | `tool start` |
| `stop` | Stop the service | `tool stop` |
| `restart` | Restart the service | `tool restart` |
| `status` | Check service status | `tool status` |
```

Tables support header rows and column alignment using standard Markdown table syntax.

## Blockquotes

The `>` prefix creates `<lq>` (long quote) elements:

```markdown
> Container orchestration automates deployment, scaling, and management of
> containerized applications. It handles service discovery, load balancing,
> and health monitoring across distributed systems.
```

Blockquotes can contain multiple paragraphs by continuing the `>` prefix on each line.

## Images

Image syntax maps to DITA `<image>` elements:

```markdown
![Architecture diagram](images/architecture.png)

![Workflow diagram](images/workflow.svg "Deployment workflow")
```

- `![alt text](url)` → `<image href="url" alt="alt text">`
- When a title is present (`"title"`), wraps in `<fig>` with `<title>`
- Block-level images (sole child of a paragraph) get `placement="break"`
- Inline images get `placement="inline"`

## Links

Link syntax maps to `<xref>` elements:

```markdown
See the [installation guide](install.md) for details.

Visit the [product website](https://example.com) for more information.

Download the [configuration template](config/template.yaml).
```

- `[text](url)` → `<xref href="url">`
- Absolute URLs get `scope="external"`
- File extensions are detected and set as `@format` (e.g., `format="dita"` for `.dita`, `format="pdf"` for `.pdf`)
- Relative links remain relative in the output

## Inline elements

Standard Markdown inline formatting maps to DITA elements:

| Markdown | DITA element | Example |
|----------|--------------|---------|
| `**bold**` | `<b>` | **important text** |
| `*italic*` or `_italic_` | `<i>` | *emphasized text* |
| `` `code` `` | `<codeph>` | `variable_name` |
| `~~strikethrough~~` | `<line-through>` | ~~deprecated feature~~ |
| `^superscript^` | `<sup>` | 2^10^ |

Multiple inline elements can be combined: `**bold `code`**` produces `<b><codeph>code</codeph></b>`.

## Footnotes

Footnote syntax creates `<fn>` elements:

```markdown
Containers provide isolation[^1] and resource limits[^2].

[^1]: Isolation uses kernel namespaces and cgroups.
[^2]: CPU and memory limits prevent resource exhaustion.
```

- `[^id]` in body text creates an `<fn>` reference
- `[^id]: text` at the end defines the footnote content
- Footnotes are rendered as `<fn>` elements inline at the reference point

## Header attributes

Headers support `{#id .class}` attribute syntax:

```markdown
## Prerequisites {#prereqs}

## Installation steps {#install .procedure}

## Configuration {#config .advanced}
```

- `{#id}` sets the `@id` attribute on the section or topic
- `{.class}` sets the `@outputclass` attribute
- Multiple attributes can be combined: `{#my-id .my-class}`

## Raw DITA XML

Inline DITA XML elements can be embedded directly in Markdown DITA mode:

```markdown
Click the <uicontrol>Save</uicontrol> button to continue.

Use the <filepath>/etc/config.yaml</filepath> file for configuration.

Press <uicontrol><shortcut>Ctrl+S</shortcut></uicontrol> to save.

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

# Style topics

The documentation style guidance that a prose linter cannot decide. Vale
enforces punctuation, terminology, passive voice, inflated wording, heading
punctuation, heading capitalization, and gerunds in headings, and none of that
appears here.

This file is the only copy. Each `##` heading below is a topic id:

- `prompts/judge-style.md` receives these sections as `{{topics}}`, and a
  reviewing model names the topic it found a problem under.
- `schemas/judge-style-out.json` constrains that name, and `docs-review` builds
  the enum from the headings here.
- The `docs-style` skill links to this file for anyone writing prose.

The bar for a topic is that Vale cannot decide it. When a new Vale rule starts
covering one, delete its section here.

## accessibility

- Anything a sighted reader takes from position or color must also be available as text.
- Give every image alt text describing what it does rather than what it looks like.
- Name a control instead of pointing at it.
- Make link text describe where it goes.
- Color may reinforce meaning. It must never carry meaning alone.

## admonitions

- Use NOTE, IMPORTANT, WARNING, or TIP, singular and sparing.
- CAUTION does not render.
- Never open a topic with an admonition, stack two of them, or put a procedure inside one.

## claims recommendations

- Say what the product can do rather than what it will do for the reader.
- Avoid superlatives, comparisons against competitors, and any promise of an outcome.
- Prefer "helps" and "is designed to" over "ensures" and "guarantees".
- Qualify a performance number with the conditions that produced it.
- Do not describe unannounced features.

## code examples

- Write examples that run.
- Use realistic names and values instead of foo or bar.
- Fence every block with its language and keep the block safe to copy whole.
- Mark anything the reader must substitute so it cannot be mistaken for a literal value.
- Draw example addresses from the reserved ranges: example.com, 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24.

## headings

- Name what the section is about, specifically enough to be useful out of context: "Install the CLI on Linux" over "Installation".
- Never skip a heading level.

## minimalism

- Cut whatever does not help the reader act.
- Keep conceptual material out of procedures.
- Include the verification and recovery a reader needs when the task fails.

## information personal

- No real personal data anywhere, examples included.
- Use fictional names, addresses, and telephone numbers.
- Redact screenshots before publishing.
- Keep employee names, internal email addresses, and internal identifiers out of published content.

## procedures

- One action per step, each opening with an imperative verb.
- Number the steps that must happen in order.
- Put prerequisites before the procedure rather than inside it.
- Open an optional step with "Optional:".
- State the expected result of any step whose success is not obvious.
- Split anything past nine steps into separate tasks.

## tables

- Use tables for data, never for layout.
- Give every table a caption and every column a filled header cell.
- Keep the structure flat, with no spanned cells and no stacked header rows, which a screen reader cannot linearize.
- Put N/A or a dash in an empty cell.

## preview technology

- State support status exactly.
- Technology Preview takes initial capitals and never appears as Tech Preview.
- A Technology Preview feature is not supported.
- Describe what the feature provides rather than what is supported.
- Carry the required IMPORTANT admonition until the feature reaches general availability, then remove it.


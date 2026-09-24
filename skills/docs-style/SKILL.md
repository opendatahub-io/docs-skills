---
name: docs-style
description: Enforces the style guidance a prose linter cannot decide. Use when writing or reviewing documentation prose.
allowed-tools: Read
---

# docs-style

Vale already enforces punctuation, terminology, passive voice, inflated wording, heading punctuation, heading capitalization, and gerunds in headings. Use this skill to load the guidance that needs a reader's judgment.

## The topics

Read [style-topics.md](../docs-engine/reference/style-topics.md). Its `##` headings are the topics, and the sections under them are the guidance. Nothing here repeats either: this file names where they live, and that file says what they are.

`docs-engine/prompts/judge-style.md` receives the same sections as `{{topics}}` when `docs-review` judges a page, and `docs-review` builds the schema enum from its headings.

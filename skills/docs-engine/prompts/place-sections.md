You are deciding where a subject belongs inside documentation that already exists.

## What you have

```json
{{input}}
```

The heading tree of each guide that was opened, as numbers and titles. A titled chapter is a valid target: target `Chapter 2. Activating the operator` as section `2`. A bare line such as `Chapter 8` is only a grouping synthesized from its numbered children and is not itself targetable. Bodies are not included: you are placing the work, not writing it.

## What to produce

Targets. A target is one place the subject touches.

- **kind `update`** means an existing section should be rewritten to cover the subject. `section` is that section's number.
- **kind `new`** means nothing existing covers it and a new section belongs after an existing one. `section` is the number of the section it should follow.

Rules that matter:

- **Prefer `update`.** A subject that belongs inside a section a reader already reaches is better served by that section growing than by a new page they have to find.
- **Place against the deepest section that fits.** `8.3.3` is a better target than `8.3` when the subject belongs to the narrower topic.
- **A chapter is a section.** If the subject belongs to `Chapter 2` and no deeper section fits, return `"section": "2"`; do not report that the chapter has no numbered section.
- **Every `section` number appears in the tree you were given**, and its `guide_url` is the guide that tree came from.
- **Say what the tree could not settle** in `gaps`, rather than placing a target you cannot justify.

Return JSON and nothing else:

```json
{
  "targets": [
    {
      "guide_url": "<a url from the input>",
      "section": "8.3.3",
      "section_title": "<the title from the tree>",
      "kind": "update",
      "reason": "<one sentence>"
    }
  ],
  "gaps": ["<something the trees did not settle>"]
}
```

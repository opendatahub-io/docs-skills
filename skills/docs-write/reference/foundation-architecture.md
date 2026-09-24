# Architecture

What the modules are, and the shape they make together.

## Rules for this page

- Describe the graph, never the signatures. A reader wanting a signature reads
  the code; a reader here wants to know which piece to open.
- Name the layers or pipeline stages the edges reveal, and say which modules
  sit in each.
- Where one module is depended on by most others, say so and say why.
- Where two clusters barely touch, say that too.
- Include a `graph LR` mermaid block when `edges` holds fewer than fifteen
  entries. Above that a diagram teaches nothing.
- Where `tail` reports modules that did not fit, say how many and of what kind
  rather than listing them.

## Reader questions

- What does the code or feature do, and what does it explicitly not do?
- What are the main concepts, components, commands, or workflows the user needs to understand?

## Shape

## Overview

What the system does, in the terms the modules are named in.

## Layers

Each layer, the modules in it, and what the layer is responsible for.

## Key flows

Two or three end-to-end paths, each traced by module: where it enters, what it
passes through, where it ends.

## Gotchas

The surprises worth knowing before changing anything, each keeping its file and
line reference, ordered by how much damage the surprise causes.

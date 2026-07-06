---
name: docs-orchestrator
description: Documentation workflow orchestrator. Reads the step list from .agent_workspace/docs-workflow.yaml (or the plugin default). Runs steps sequentially, manages progress state, handles iteration and confirmation gates. Claude is the orchestrator — the YAML is a step list, not a workflow engine.

argument-hint: <ticket> [--workflow <name>] [--pr <url>...] [--source-code-repo <url-or-path>...] [--no-source-repo] [--auto-discover-repos] [--max-secondary-repos <N>] [--mkdocs] [--draft] [--docs-repo-path <path>] [--create-jira <PROJECT>] [--create-merge-request]

allowed-tools: Read, Write, Glob, Grep, Edit, Bash, Skill, AskUserQuestion
---

# Docs Orchestrator

**When the user invokes `/docs-orchestrator`, run THIS skill directly. Do NOT redirect to `docs-workflow-start` or any other skill.**

The Python state machine driver owns all orchestrator logic. Claude calls the driver, parses JSON actions, and executes them.

## Pre-flight

Install the workflow completion Stop hook (safe to re-run):

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/setup-hooks.sh
```

Do not source `.env` files or check for tokens/CLIs — downstream scripts handle their own prerequisites.

## Initialize

If the ticket argument is missing, STOP and ask the user.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docs_orchestrator.py init <TICKET> \
  [--workflow <name>] \
  [--pr <url>...] \
  [--source-code-repo <url-or-path>...] \
  [--no-source-repo] \
  [--auto-discover-repos] \
  [--max-secondary-repos <N>] \
  [--mkdocs] \
  [--draft] \
  [--docs-repo-path <path>] \
  [--create-merge-request] \
  [--create-jira <PROJECT>] \
  [--plugin-root ${CLAUDE_PLUGIN_ROOT}]
```

The script handles argument parsing, source resolution, workflow YAML loading, progress file creation or resume, and step classification. It emits a single JSON action to stdout. Parse it and enter the action loop.

## Action loop

Read the JSON `action` field and act:

### `run_skill`

The response contains `skill`, `args`, `step`, `message`, and optional `warnings` and `messages` arrays.

1. Display `message`. Display any `warnings` (prefix with WARNING) and `messages`.
2. Invoke: `Skill: <skill>, args: "<args>"`
3. After the skill completes, report the result:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docs_orchestrator.py step-done <TICKET> <step>
```

If the skill failed (threw an error, produced no output), add `--failed`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docs_orchestrator.py step-done <TICKET> <step> --failed
```

4. Parse the new JSON response and loop back to the action check.

### `complete`

Display `message` and the `summary` object (completed steps, MR/PR URL, JIRA URL, module/file counts). Display any `warnings`. The workflow is done.

### `fail`

Display `message` and `reason`. Display any `warnings`. Stop.

## Querying status

To check workflow status without advancing it:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docs_orchestrator.py status <TICKET>
```

To get the next action without recording a step-done:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/docs_orchestrator.py next <TICKET>
```

## Guardrails

Rules the script cannot enforce — Claude must follow these during execution:

1. **Synchronous primary agents.** When a step skill instructs you to dispatch an Agent, pass `run_in_background: false` for the step's primary agent (the one whose output file the step verifies). Fan-out agents within a step may remain background.

2. **No stub results.** If you cannot invoke a step's skill (e.g., context compaction removed its instructions), dispatch the step via an Agent subagent in a fresh context or mark it failed. Never write a placeholder `step-result.json` or mark a step `completed` with generic text.

3. **Pipeline diagnostics via Agent.** The `pipeline-diagnostics` step runs last after 10+ skill invocations. Context compaction will have removed its skill instructions. Always dispatch it via the Agent tool in a fresh context.

4. **Commit confirmation gate.** Before the `create-merge-request` step, ask the user to confirm. Show: branch name, target repo, file count. If declined, call `step-done <TICKET> create-merge-request --failed`.

## Output conventions

Every step writes to `.agent_workspace/<ticket>/<step-name>/`. See [output and state reference](references/output-and-state.md) for the folder structure and [step-result schema](schema/step-result-schema.md) for sidecar format.

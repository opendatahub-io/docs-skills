# Runtime compatibility

The plugin uses one set of skills for Claude Code and Codex. Apply the rules in this file only when the current skill uses platform-specific paths or subagents.

## Bundled paths

Claude Code expands `${CLAUDE_SKILL_DIR}` and `${CLAUDE_PLUGIN_ROOT}` in command examples. Codex does not define those variables. Before running a command in Codex, replace:

- `${CLAUDE_SKILL_DIR}` with the absolute directory containing the loaded `SKILL.md`.
- `${CLAUDE_PLUGIN_ROOT}` with the absolute plugin directory containing `.codex-plugin/plugin.json`.

Do not run a command with an unresolved `CLAUDE_*` variable. Keep the target project as the command's working directory unless the skill explicitly says otherwise.

## Subagents

Instructions that name the Agent tool or a `subagent_type` describe Claude Code's native custom-agent interface.

- In Claude Code, use the fully qualified `docs-skills:<agent-name>` type exactly as shown.
- In Codex, create a collaboration subagent for the same bounded task. Tell it to read `<plugin-root>/agents/<agent-name>.md` and follow the body as its role instructions, then include the task-specific prompt from the skill. Pass the absolute plugin root and tell the subagent to use it wherever the definition says `${CLAUDE_PLUGIN_ROOT}`.
- Treat Claude model labels as quality tiers: `haiku` means a fast model, `sonnet` a balanced model, and `opus` the strongest reasoning model. Use the closest available Codex model or the current default when no explicit mapping is available.
- Preserve requested parallelism and isolation. If the runtime cannot create subagents, report that limitation instead of silently skipping the delegated work.

Agent definitions can mention Claude tool names such as Read, Grep, or Glob. In Codex, use the equivalent filesystem or search capability.

## Tool and invocation names

- Invoke a Claude Code skill as `/skill-name` and a Codex skill as `$skill-name`.
- Treat `AskUserQuestion` as the runtime's user-input mechanism. In Codex, use the available input tool or ask the question directly when no such tool is exposed.
- Treat the Skill tool as a request to invoke the named skill. If Codex cannot nest a skill invocation, read that skill's `SKILL.md` and follow it directly.
- Use Codex web tools for `WebSearch` and `WebFetch` instructions.

## Claude Code hooks

Codex does not load `hooks/hooks.json` or settings under `.claude/`. Skip Claude-specific hook installation steps. When running `docs-orchestrator`, keep processing its action loop until the driver returns `complete` or `fail`; source resolution is also handled by the driver.

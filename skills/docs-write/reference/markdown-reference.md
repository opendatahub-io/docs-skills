# CLI command reference

## Reader questions

- Who are the intended users, and what do they already know?
- What job does the user need to accomplish with this code, feature, or tool?
- What does the code or feature do, and what does it explicitly not do?
- What is the shortest realistic example that shows the code or feature being used successfully?
- What are the main concepts, components, commands, or workflows the user needs to understand?
- What problems or errors do users commonly encounter, why do they happen, and how are they resolved?
- How does the user verify that the installation, example, or task worked, and where should they go next?

Use this reference to look up command syntax, common options, and exit codes.

## Command syntax

```text
tool [global-options] <command> [command-options] [arguments]
```

## Commands

| Command | Description | Example |
| --- | --- | --- |
| `connect` | Establish a connection. | `tool connect --host server.example.com` |
| `disconnect` | End the current connection. | `tool disconnect` |
| `list` | List available resources. | `tool list --type service` |
| `get` | Show one resource. | `tool get example-resource` |

## Common options

| Option | Description | Accepted values |
| --- | --- | --- |
| `--namespace` | Select a namespace. | A namespace name |
| `--output` | Set the output format. | `json`, `yaml`, or `table` |
| `--dry-run` | Preview the operation without applying it. | None |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | The command succeeded. |
| `1` | The command failed. |
| `2` | The command syntax was invalid. |
| `126` | The command could not run because permission was denied. |
| `127` | The executable was not found. |

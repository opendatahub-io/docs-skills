# CLI command reference

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

---
id: cli-command-reference
author: Documentation Team
category: Reference
keyword:
  - cli
  - commands
  - reference
---

# CLI command reference {.reference}

## Connection commands

The following commands manage connection operations.

| Command | Description | Example |
|---------|-------------|---------|
| `connect` | Establish a connection | `connect --host localhost --port 8080` |
| `disconnect` | Terminate the current connection | `disconnect` |
| `status` | Show connection status | `status` |
| `whoami` | Display the current user | `whoami` |
| `version` | Show CLI version information | `version` |

## Resource commands

| Command | Description | Example |
|---------|-------------|---------|
| `list` | Display available resources | `list --type pods` |
| `get` | Retrieve a specific resource | `get resource-name` |
| `create` | Create a new resource | `create --file config.yaml` |
| `update` | Modify an existing resource | `update resource-name --field value` |
| `delete` | Remove a resource | `delete resource-name` |
| `describe` | Show detailed resource information | `describe resource-name` |

## Common flags

`-n`
:   Specify the namespace or context for the operation.

`-o`
:   Set the output format. Valid values: `json`, `yaml`, `table`, `text`.

`--dry-run`
:   Preview the operation without making changes.

`-l`
:   Filter resources by label selector expression.

`--all`
:   Operate across all resources or namespaces.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Command succeeded |
| `1` | General error |
| `2` | Misuse of command syntax |
| `126` | Permission denied |
| `127` | Command not found |

!!! important

    Some commands require elevated privileges. Ensure you have the necessary
    permissions before executing administrative operations.

---
id: installing-cli-tool
author: Documentation Team
category: Installation
keyword:
  - cli
  - installation
  - setup
---

# Installing the command-line tool {.task}

The command-line tool is a utility for managing and automating tasks from the terminal. It extends basic shell commands with additional features for workflow automation.

## Prerequisites

- A running system with network access
- Administrator or elevated privileges on your workstation
- Either `curl` or `wget` installed

## About this task

The installation downloads a signed binary, verifies it, and installs it to a directory on your `PATH`. You perform this installation once per workstation.

## Steps

1.  Download the CLI archive for your operating system:

    ```bash
    curl -LO https://example.com/downloads/cli/latest/linux/cli.tar.gz
    ```

    !!! tip

        You can also download the CLI from the official website by visiting
        the downloads page and selecting your platform.

2.  Extract the archive:

    ```bash
    tar -xvf cli.tar.gz
    ```

3.  Move the binary to a directory in your PATH:

    1.  Check your current PATH:

        ```bash
        echo $PATH
        ```

    2.  Identify the target directory:

        ```bash
        ls /usr/local/bin/
        ```

    3.  Move the CLI binary:

        ```bash
        sudo mv cli /usr/local/bin/
        ```

4.  Choose an authentication method:

    -   Use environment variables for automated systems
    -   Use a configuration file for interactive sessions
    -   Use command-line flags for one-time operations

## Verification

Confirm the installation by checking the version:

```bash
cli version
```

The output shows the version information:

```
CLI Version: 1.0.0
Build Date: 2025-08-05
Platform: linux/amd64
```

## Next steps

Configure shell completion for the CLI to speed up your workflow, then run `cli status` to confirm connectivity.

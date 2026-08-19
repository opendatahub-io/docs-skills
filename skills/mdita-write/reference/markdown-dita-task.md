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

Before you start, make sure you have a running system with network access, administrator or elevated privileges on your workstation, and either `curl` or `wget` installed.

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

4.  Choose a verification method:

    -   Run `cli version` to check the installed version
    -   Run `which cli` to confirm the binary location
    -   Run `cli --help` to display available commands

5.  Verify the installation:

    ```bash
    cli version
    ```

    The output shows the version information:

    ```
    CLI Version: 1.0.0
    Build Date: 2025-08-05
    Platform: linux/amd64
    ```

After the CLI is installed, confirm it is working by running `cli --help` and `cli status`. Then configure shell completion for the CLI to speed up your workflow.

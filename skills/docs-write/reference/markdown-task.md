# Install the command-line tool

## Reader questions

- Who are the intended users, and what do they already know?
- What job does the user need to accomplish with this code, feature, or tool?
- What should the user be able to do after reading the documentation?
- What does the code or feature do, and what does it explicitly not do?
- What are the prerequisites, dependencies, environment requirements, and installation steps?
- What is the shortest realistic example that shows the code or feature being used successfully?
- What problems or errors do users commonly encounter, why do they happen, and how are they resolved?
- How does the user verify that the installation, example, or task worked, and where should they go next?

Install the command-line tool on a workstation so that you can run it from your terminal.

## Prerequisites

- A supported operating system
- Permission to install an executable in a directory on your `PATH`
- `curl` and `tar`

## Procedure

1. Download the archive for your operating system:

   ```bash
   curl -LO https://downloads.example.com/tool/tool-linux.tar.gz
   ```

2. Extract the archive:

   ```bash
   tar -xvf tool-linux.tar.gz
   ```

3. Move the executable to a directory on your `PATH`:

   ```bash
   sudo mv tool /usr/local/bin/tool
   ```

## Verification

Display the installed version:

```bash
tool version
```

The command prints the version and exits successfully.

## Next steps

Configure authentication, then run `tool status` to confirm that the tool can connect to its service.

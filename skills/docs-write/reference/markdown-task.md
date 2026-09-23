# Install the command-line tool

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

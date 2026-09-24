# Security

The security surface this repository actually has, and nothing else.

## Rules for this page

- Every claim rests on a module, a symbol, or a config file in the payload.
- Describe what the code does about authentication, authorization, transport
  and secrets, where the evidence covers it. Omit the heading where it does not.
- Never speculate about threats, and never assess whether the design is good.
- Name the tools in `configs` and what each one checks.
- No vulnerability reporting process unless the evidence carries one. That
  belongs to a policy file, which a maintainer owns.

## Shape

## Surface

The modules that handle security-relevant work, and what each one is
responsible for.

## Transport and secrets

Where the evidence covers it: how connections are secured and where secrets
come from.

## Tooling

The security checks the repository runs, each named with what it looks for.

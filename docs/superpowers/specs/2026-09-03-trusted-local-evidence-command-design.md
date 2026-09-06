# Trusted-local Evidence Command Policy

## Goal

Keep existing shell-capable `harness evidence --command` workflows while making execution trust boundary explicit and testable.

## Boundary

`--command` is executable shell text supplied directly by local Harness operator. It is not an API, configuration, remote payload, CI metadata, or untrusted-user input channel. Callers must not forward untrusted values into this option.

## Design

`collect_evidence` retains `subprocess.run(command, shell=True, ...)`. Entry-point naming and validation document trusted-local provenance. CLI help and user documentation warn that command supports shell syntax and executes with local operator privileges. No escaping or allowlist is applied because it would imply untrusted-input safety and break valid shell constructs.

## Error handling and observability

Preserve timeout and command result behavior. Policy violation is represented by rejecting any future non-local forwarding path before execution; this change adds no remote input surface.

## Verification

- Unit tests prove shell syntax remains supported.
- CLI/help or docs tests prove trusted-local warning exists.
- Regression tests ensure existing evidence execution semantics remain unchanged.

## Non-goals

- argv-only or dual execution mode.
- Accepting commands from remote/configuration/API sources.
- Timeout/decode handling, control-plane refactor, or formatting; separate tasks.

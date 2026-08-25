---
name: minimal-implementation
description: Run before implementation to record minimal necessary approach using Harness Decision Ladder.
---

# Minimal Implementation Check

Run in `PLANNED`, before `IMPLEMENTING`. Do not implement code.

Read `.harness/current-task.yaml`, requirements, invariants, design/plan, and dependency manifest. Answer ladder in order:

1. Does capability need to exist?
2. Does equivalent repository capability exist?
3. Can stdlib solve it?
4. Can platform-native capability solve it?
5. Can installed dependency solve it?
6. Can small local implementation solve it?
7. Only then choose new abstraction.

Search repository before creation. First `found` short-circuits later checks: write `checked: false, result: skipped`. Requirement/invariant-required security, audit, compatibility, migration, accessibility, NFR, and trust-boundary complexity remains necessary.

Write YAML matching `schemas/minimal-implementation.schema.json`, then run:

```bash
harness check minimal --file /path/to/decision.yaml
```

Do not transition to `IMPLEMENTING` until command succeeds.

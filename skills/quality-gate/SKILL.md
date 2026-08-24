---
name: quality-gate
description: "Use when task state is GATING and a go/no-go decision is needed before CONVERGED. Runs quality_gate.py and maps its exit code to state transitions; MUST NOT assess quality by judgement."
---

# Quality Gate Skill

You run the gate. You never evaluate quality yourself.

## Invocation

```bash
harness gate
```

(In-harness-repo equivalent: `python scripts/quality_gate.py`.)

## Exit Code → Action Mapping

| Exit | Meaning | Action |
|---|---|---|
| 0 | PASS | Transition GATING → CONVERGED (validate via `scripts/state_machine.py`), then convergence skill decides DONE. |
| 1 | BLOCKED | Transition GATING → BLOCKED. Copy blockers from stdout into `gate.blocked_by`. Dispatch per blocker type (finding → reproduce-finding; failed requirement → IMPLEMENTING). |
| 2 | INVALID_HARNESS_STATE | Fix harness state first (missing file, bad YAML, unknown state). Do NOT loop implementation for this. |

## Hard Boundaries (不得违反)

1. **禁止 Skill 自己评估**："综合来看质量足够好" is forbidden. Exit code 0 is
   the ONLY pass signal.
2. **Only exit 0 permits GATING → CONVERGED.**
3. Gate must be re-run after ANY new evidence, finding update, or commit —
   a previous PASS is void once inputs change.

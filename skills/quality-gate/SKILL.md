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
| 0 | Command completed | Read `DECISION:` and then `harness status`. `CONVERGED` permits `harness transition DONE`; `CONTINUE` requires `harness resume`; `ESCALATED` ends autonomous work. |
| 1 | Invalid invocation/state | Fix reported CLI precondition. Do not edit state or blockers yourself. |

`harness gate` persists `gate.blocked_by` and task state itself. Never copy blockers or transition Gate states manually.

## Hard Boundaries (不得违反)

1. **禁止 Skill 自己评估**："综合来看质量足够好" is forbidden. Persisted
   `DECISION: CONVERGED` is the ONLY pass signal.
2. **Only `DECISION: CONVERGED` permits `CONVERGED → DONE`.**
3. Gate must be re-run after ANY new evidence, finding update, or commit —
   a previous PASS is void once inputs change.

---
name: quality-gate
description: "Use when task state is GATING and a go/no-go decision is needed before CONVERGED. Runs `harness gate` and follows `DECISION:`; MUST NOT assess quality by judgement."
---

# Quality Gate Skill

You run the gate. You never evaluate quality yourself.

## Invocation

```bash
harness gate
```

Do not run `python scripts/quality_gate.py` as a product command. It does not
move `GATING → CONVERGED` and is not equivalent to `harness gate`.

## Related Commands

```bash
harness gate preflight
harness impact scope --format yaml
harness evidence run --type unit_test --command "pytest"
harness evidence attach --type build --file external-proof.json
harness finding resume-review FND-001
```

## Exit Code → Action Mapping

| Exit | Meaning | Action |
|---|---|---|
| 0 | Command completed | Read stdout `DECISION:` and then `harness status`. `CONVERGED` with `DIRECTIVE: NONE` permits `harness transition DONE`; `CONTINUE` with `DIRECTIVE: RESUME_TYPED_RECOVERY` requires `harness resume`; `ESCALATED` with `DIRECTIVE: NONE` ends autonomous work. |
| 1 | Invalid invocation/state, or a repairable alignment rejection | Fix a reported CLI precondition only when stderr has no `DIRECTIVE: HALT_AND_WAIT`. User-authority stderr means stop. `ALIGNMENT_FREEZE_INVALID` is repairable and is not a halt. An unrecognized `DIRECTIVE` is not permission to resume, and a free-text `Next:` line is not a command. |
| 2 | Invalid Harness data | Stop; report invalid input. Gate does not write task on validation error. |

On exit `0`, a missing, unknown, duplicate, or decision-conflicting `DIRECTIVE:` is not permission to resume or transition; stop and inspect persisted task. `harness gate` persists `gate.blocked_by` and task state itself. Never copy blockers or transition Gate states manually. Guard `POLICY: USER_AUTHORITY_REQUIRED` / `DIRECTIVE: HALT_AND_WAIT` is not Gate `DECISION:`; stop and request user decision without calling `harness resume` or advancing task.

## Hard Boundaries (不得违反)

1. **禁止 Skill 自己评估**："综合来看质量足够好" is forbidden. Stdout
   `DECISION: CONVERGED` is the ONLY pass signal. It is command output, not a
   field in `current-task.yaml`. Persisted authority is `state: CONVERGED`
   and gate metadata.
2. **Only `DECISION: CONVERGED` permits `CONVERGED → DONE`.**
3. Gate must be re-run after ANY new evidence, finding update, or commit —
   a previous PASS is void once inputs change.

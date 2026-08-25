# Task Recovery Design

## Goal

Allow user-authorized recovery from any active Engineering Harness task without bypassing state-machine history or losing task artifacts.

## Command

```bash
harness task recover TASK-005 \
  --title "Package self-contained wheel isolation" \
  --reason "TASK-004 is stale; CR-004 needs isolated contract"
```

`ID` must match `TASK-[0-9]+`. `--reason` is required and non-empty. `--title` defaults to an empty string.

## Scope

Add `task recover`. Keep existing `task new` behavior unchanged: it still requires prior task state `DONE` or `ESCALATED`.

## Recovery flow

1. Load active `.harness/current-task.yaml`.
2. Reject terminal active tasks (`DONE`, `ESCALATED`); callers use `task new` instead.
3. Create `.harness/history/<old-id>-<UTC timestamp>/`.
4. Copy active YAML files into archive:
   - `current-task.yaml`
   - `requirements.yaml`
   - `invariants.yaml`
   - `gate.yaml`
5. Move active `findings/` and `evidence/` directories into archive. This preserves generated artifacts without leaving them active.
6. Write archive `recovery.yaml`:
   - `recovered_at` UTC ISO-8601 timestamp
   - `reason`
   - `previous_task_id`
   - `previous_state`
   - `replacement_task_id`
7. Recreate empty active `findings/` and `evidence/` directories.
8. Replace active YAML files from bundled `harness.templates` resources.
9. Set new task ID and title. New task remains template state `CREATED`.

## Invariants

- Recovery never deletes prior task YAML, findings, or evidence.
- Recovery requires explicit human reason in persisted audit record.
- Recovered task starts at `CREATED`; no state transition is forged.
- Normal completion path remains unchanged.
- Failed validation occurs before archive or active-file mutation.

## Error handling

- Invalid ID, empty reason, terminal task, or missing active task: print error and return nonzero.
- Existing archive collision: return nonzero without replacing archive.
- File-operation failure may leave archive plus active state; archive audit and absence of destructive deletion support manual recovery. Implementation uses moves only after archive directory creation.

## Verification

Unit tests verify:

1. invalid IDs and empty reasons reject without archive;
2. terminal task rejects and leaves active task intact;
3. active-task recovery copies YAML, moves findings/evidence, writes complete audit, and creates `TASK-005` in `CREATED`;
4. `task new` still rejects active tasks;
5. CLI parser requires `--reason`.

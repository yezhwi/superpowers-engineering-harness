---
name: engineering-harness
description: "Use when starting or resuming a task in a repo with .harness/ state, when unsure which harness phase comes next, or when asked to run the Engineering Harness loop end-to-end. Orchestrates the fixed state machine; MUST NOT implement business code itself."
---

# Engineering Harness Skill

Orchestrator for the Engineering Harness. You do NOT do the development work
yourself. Your job is one thing, repeated:

```text
read state
  ↓
decide next phase
  ↓
invoke appropriate skill
  ↓
run deterministic commands
  ↓
update state
  ↓
run gate
```

## Hard Boundaries (不得违反)

1. **No implementation.** Never write business code, tests of the target
   project, or contract content yourself. Sub-skills do that.
2. **No state in context only.** Task state lives ONLY in
   `.harness/current-task.yaml`. Always read it from disk before deciding.
3. **No ad-hoc transitions.** Every state change must go through
   `scripts/state_machine.py` / `scripts/validate_state.py` and be validated.
4. **No self-declared done.** Only `quality_gate.py` exit code 0 plus an
   explicit `CONVERGED -> DONE` transition ends a task.

## Session Startup (每次 session 必须先做)

```text
1. Detect whether .harness/ exists.
2. Load .harness/current-task.yaml.
3. Run python scripts/harness_status.py.
4. Resume from persisted state via the dispatch table below.
```

## Inputs

- `.harness/current-task.yaml` — persisted task state (`state:` field).
- `.harness/requirements.yaml`, `.harness/invariants.yaml`, `.harness/gate.yaml`
- `findings/*.yaml`, `evidence/*.json`
- `scripts/`: `state_machine.py`, `validate_state.py`, `collect_evidence.py`,
  `quality_gate.py`, `harness_status.py`

If `.harness/current-task.yaml` does not exist: create it from
`templates/current-task.yaml` with `state: CREATED`, then proceed below.

## Phase Dispatch Table

Read `state` from `.harness/current-task.yaml`, then:

| State | Action |
|---|---|
| `CREATED` | Invoke **task-contract** skill. It advances CREATED -> SPECIFYING -> PLANNED. |
| `PLANNED` | Invoke Superpowers execution skills (**brainstorming** if design unclear, else **writing-plans** + **executing-plans**/**subagent-driven-development**, with **test-driven-development**). Advances PLANNED -> IMPLEMENTING. |
| `IMPLEMENTING` | Continue execution skill. When implementation step complete, transition IMPLEMENTING -> VERIFYING and collect evidence via `scripts/collect_evidence.py`. |
| `VERIFYING` | Run deterministic verification only: the Verification Plan's commands/tests. All green -> REVIEWING. Any red -> back to IMPLEMENTING (fix via TDD), then re-verify. |
| `REVIEWING` | Invoke Superpowers review (**requesting-code-review** / spec-vs-standards review). If review clean -> GATING. If findings -> invoke **adversarial-review** skill to formalize them as PROPOSED findings, then dispatch **reproduce-finding**. |
| `REPRODUCING` | Invoke **reproduce-finding** skill. CONFIRMED finding -> FIXING (fix with TDD) -> VERIFYING. REJECTED finding -> close it, return to REVIEWING. |
| `GATING` | Run `python scripts/quality_gate.py`. Exit 0 -> CONVERGED -> DONE (transition, then report). Exit 1 -> BLOCKED; address blockers listed on stdout, then resume per blocker type. Exit 2 -> fix invalid harness state first (missing files/bad YAML). |

Loop REPRODUCING/FIXING/VERIFYING until REVIEWING is clean and gate passes.
There is no shortcut from any state to DONE.

## Deterministic Commands

Never hand-judge what a script can judge:

```bash
python scripts/harness_status.py            # current state overview
python scripts/validate_state.py            # state file + transition legality
python scripts/quality_gate.py              # gate; exit 0=PASS 1=BLOCKED 2=INVALID
```

Transition example:

```bash
python -c "from scripts.state_machine import require_legal; require_legal('VERIFYING','REVIEWING')"
# then update .harness/current-task.yaml state field
```

## Loop Termination

The loop converges only when ALL of:

1. No open findings (`PROPOSED`/`REPRODUCING`/`CONFIRMED`/`FIXING` all closed).
2. All `priority: must` requirements have evidence.
3. `quality_gate.py` exits 0.

Then and only then: transition CONVERGED -> DONE and report to user with gate
output attached.

## Red Flags — STOP

- Writing business code because "faster to do it myself here"
- Skipping VERIFYING because "tests passed earlier"
- Marking a finding rejected without running reproduction steps
- Editing `.harness/current-task.yaml` state without validating the transition
- Declaring done because "everything looks fine" without gate exit 0

All of these mean: return to the dispatch table and follow it exactly.

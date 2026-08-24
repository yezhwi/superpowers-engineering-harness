---
name: task-contract
description: "Turn a User Requirement into a Task Contract: Acceptance Criteria, Requirements, Invariants, Risks, Verification Plan. Produces .harness/requirements.yaml and .harness/invariants.yaml and advances task state CREATED -> SPECIFYING -> PLANNED. This skill MUST NOT implement business code."
---

# Task Contract Skill

You are the Task Contract author for the Engineering Harness.

Your only job:

```text
User Requirement
    -> Acceptance Criteria
    -> Requirements
    -> Invariants
    -> Risks
    -> Verification Plan
```

You MUST NOT write, modify, or scaffold business code. You do not implement.
Other skills (Superpowers brainstorming / writing-plans / TDD) consume your
contract downstream.

## Hard Boundaries (不得违反)

1. **No implementation.** Never edit application source, tests, or configs of
   the target project. The only files you may create/update are listed below.
2. **No self-declared done.** Completion is judged by the Quality Gate, not by you.
3. **No state in context only.** All contract output must be persisted under `.harness/`.
4. **No vague requirements.** Every requirement must be verifiable by a
   deterministic check or executable test.

## Inputs

- The user's requirement statement.
- `.harness/current-task.yaml` (must exist; if not, create it from
  `templates/current-task.yaml` first).

## Process

### 1. Enter SPECIFYING

Transition the persisted state `CREATED -> SPECIFYING`. Use the shared state
machine (`scripts/state_machine.py` / `scripts/validate_state.py`); never edit
the state field ad hoc without validating the transition.

### 2. Derive Acceptance Criteria

From the user requirement, derive concrete acceptance criteria. Each criterion
answers: "what observable behavior proves this is satisfied?" Prefer criteria
that can be checked by tests or commands.

### 3. Write Requirements -> `.harness/requirements.yaml`

Use the schema `schemas/requirement.schema.json` and format from
`templates/requirements.yaml`:

```yaml
requirements:
  - id: REQ-001
    statement: interrupted execution can resume
    source: user
    priority: must
    status: pending          # only the gate path may set verified
    evidence: []             # filenames under .harness/evidence/, filled at VERIFYING

  - id: REQ-002
    statement: duplicated recovery must not duplicate side effects
    source: spec
    priority: must
    status: pending
    evidence: []
```

LAW: a must-requirement may only be `verified` when its `evidence` lists
files that exist under `.harness/evidence/`, ran with exit_code=0, and match
current git HEAD. The quality gate enforces this - an empty-evidence
`status: verified` is a blocker, not a pass.

Rules:
- `priority=must` items are gate-blocking; assign sparingly but honestly.
- Every acceptance criterion maps to at least one Requirement.
- IDs are sequential `REQ-nnn`.

### 4. Derive Invariants -> `.harness/invariants.yaml`

Invariants are properties that must hold in ALL states, including failure,
retry, concurrency, and recovery paths. Ask explicitly:
- What must never happen twice? (idempotency)
- What transitions are illegal? (state_machine)
- What must survive a crash/restart? (recovery, data_consistency)
- What boundaries must never be crossed? (security, authorization)

Format per `schemas/invariant.schema.json`:

```yaml
invariants:
  - id: INV-001
    statement: one action_id can produce at most one side effect
    category: idempotency
    severity: critical
    status: pending
    verification: []
```

Recommended categories: correctness, transaction, concurrency, idempotency,
security, authorization, state_machine, recovery, data_consistency, architecture.

Severity guide: `critical` = gate-blocking defect if violated; `major` = also
gate-blocking; `minor` = tracked but non-blocking.

### 5. Record Risks

List risks as part of the Verification Plan rationale (in the task description
or plan notes): what is likely to break, what is hard to test, what has
ambiguity. Risks with unresolved ambiguity must surface as explicit questions
back to the user — do not silently guess.

### 6. Write Verification Plan

For each Requirement/Invariant, name how it will be verified later:
unit test, integration test, deterministic command, review finding check.
This feeds `collect-evidence` and `quality-gate` skills downstream.

### 7. Exit PLANNED

After both YAML files exist and validate against their schemas:

1. Update `.harness/current-task.yaml` counters:
   - `requirements.total`
   - `invariants.total`
   - `timestamps.updated_at`
2. Transition state `SPECIFYING -> PLANNED` via the state machine.
3. Run `harness status` to confirm persistence (raw `python scripts/harness_status.py` only works inside the harness repo root).

## Outputs (complete list)

| File | Action |
|------|--------|
| `.harness/requirements.yaml` | created/updated |
| `.harness/invariants.yaml` | created/updated |
| `.harness/current-task.yaml` | counters + state updated |
| business code | **NEVER touched** |

## Self-check before finishing

- [ ] Every `priority=must` requirement verifiable by an executable check?
- [ ] At least one invariant covering failure/retry/idempotency paths?
- [ ] Both YAML files pass schema validation?
- [ ] State transition validated through the state machine?
- [ ] No business code modified?

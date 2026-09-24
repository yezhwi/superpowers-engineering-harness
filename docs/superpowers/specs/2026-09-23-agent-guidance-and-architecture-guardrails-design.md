# Agent Guidance and Architecture Guardrails — Design

## Problem and Goal

An Agent repairing local failures can make tests green while breaking Harness architecture: it follows misleading CLI `Next:` text, invents a non-`GATING` Gate route, or changes state-machine topology to legalize an unsafe shortcut. Harness must give actionable stop/continue guidance and make its architectural constraints executable. Wording alone cannot enforce Agent behaviour; CLI guards and regression tests provide enforcement.

This design complements [Autonomous Convergence Policy](2026-09-23-autonomous-convergence-policy-design.md). It keeps that policy's fingerprint algorithm, escalation precedence, and default `max_iterations`. It changes only the blocker set those rules see: Gate fingerprints and escalates the current assessment, after the stale-record filter in [Current Gate Facts](#current-gate-facts).

## Two Distinct Outcomes

- **Guard Rejection:** A phase-entry guard (for example `IMPLEMENTING -> VERIFYING`) detects frozen-contract drift or an unresolved user decision. Requested transition fails; task remains in its prior state. Agent stops and reports to user. This is **not** `ESCALATED`, a Gate decision, or permission to realign automatically. The explicit operator edge `IMPLEMENTING -> SPECIFYING` stays legal when invoked with its existing required `--reason`. Skills must not recommend that edge after `HALT_AND_WAIT`.
- **Gate Convergence:** Only `harness gate` in `GATING` issues `DECISION: CONVERGED | CONTINUE | ESCALATED`, updates convergence metadata/iteration, and follows the existing `GATING -> BLOCKED -> ESCALATED` path. No parallel Gate or new state-machine edge.

`HALT_AND_WAIT` means Agent stops, not that task must enter a terminal state. Operator can later resolve the user decision and use an existing explicit workflow. A `--reason` string alone is not proof of user authority; this design does not claim to authenticate who invoked a command or build a new authorization system.

## Invariants

1. `harness gate` accepts only `GATING`. Other states, including `BLOCKED` and `ESCALATED`, fail with exit `1` and without changing task bytes. Stderr names `harness gate` and the required state `GATING`. It must not tell the Agent to run the deprecated `converge` command.
2. Only Gate emits `DECISION:` on stdout, changes `task.convergence` or convergence iteration, and enters `CONVERGED` or `ESCALATED` as a convergence decision. `DECISION:` is **output**, not a persisted field; task state and metadata are persisted.
3. `ESCALATED` has exactly one state-machine inbound edge: `BLOCKED`. Generic `harness transition` cannot select `BLOCKED`, `CONVERGED`, or `ESCALATED` directly, even if an internal edge exists. `harness resume` must not turn a user-authority marker into `BLOCKED -> ESCALATED`; such decisions remain Gate-only.
4. Guard rejection does not change task state, `gate.status`, `gate.blocked_by`, iteration, or convergence metadata. An authoritative Guard may persist or update an alignment Finding for audit. A diagnostic `align status`, `align diff`, or `align check` is read-only and persists nothing. Guard Findings and leftover `gate.blocked_by` entries are not Gate results.
5. A user-authority Guard prints `POLICY: USER_AUTHORITY_REQUIRED` and `DIRECTIVE: HALT_AND_WAIT` on stderr. It must not recommend `SPECIFYING`, Gate invocation, evidence collection, `align freeze`, authorization, or Decision acceptance as an **autonomous next step**. Repairable rejections stay repairable and must not reuse this policy or directive.
6. A stale Guard diagnostic cannot escalate a later Gate. Gate evaluates the current facts below, not obsolete `gate.blocked_by` entries and not an alignment Finding whose drift is no longer present.

## Current Gate Facts

User-authority at `harness gate` comes only from this assessment:

1. A Decision for the current task whose status is `PROPOSED` → `DECISION_UNRESOLVED`.
2. A fresh sealed-freeze / contract-hash comparison run in this assessment → `CONTRACT_CHANGED` or `SCOPE_DRIFT_*`.
3. Every other blocker this same assessment produces.

These are not current facts:

- A previously stored `task.gate.blocked_by` entry. Gate does not merge that list into the assessment. When Gate persists a decision it replaces `blocked_by` with this assessment's blockers.
- An open alignment Finding whose `reason_code` and `boundary_ref` are not reproduced by the fresh drift check. The Finding stays on disk. Gate omits it from blockers, from the fingerprint, and from the escalation decision. Gate does not close, reject, or supersede it.

When the fresh check reproduces the same `reason_code` and `boundary_ref`, the live blocker may carry that Finding id. The defect Finding transition workflow has no close path for this alignment audit record. This design does not add one. A clean recompute leaves the file in place, and later Gates keep ignoring it until a fresh check reproduces it.

`PASS` means this assessment has no current blockers and no current user-authority fact. A stale `blocked_by` entry or a non-reproduced alignment Finding does not turn `PASS` into `ESCALATED`.

Fingerprint field order, empty-value normalization, precedence (`USER_AUTHORITY_REQUIRED`, then `REPEATED_REGRESSION`, then `NO_PROGRESS`, then `MAX_ITERATIONS`, then `CONTINUE`), and the default `max_iterations` stay as in the convergence policy. The fingerprint hashes the current blocker set after the filter above.

`select_recovery` may still return `ESCALATED` for a user-authority code. That return means there is no typed repair target. It is not a state-machine edge. `harness resume` treats that return as refusal: exit `2`, leave the task in `BLOCKED`, and do not call the transition.

## Phase 1 — Restore Guard/Gate Separation

Confirm the topology already required by the state machine: `ESCALATED` is reachable only from `BLOCKED`, and `IMPLEMENTING -> BLOCKED` / `IMPLEMENTING -> ESCALATED` are absent. Keep `IMPLEMENTING -> SPECIFYING` as the explicit operator realign edge. Do not add a Gate edge.

- Remove convergence state and convergence-metadata writes from alignment and transition commands. A user-authority phase-entry Guard rejects with exit `1`, keeps task bytes except for the audit Finding, and emits `POLICY: USER_AUTHORITY_REQUIRED` plus `DIRECTIVE: HALT_AND_WAIT` on stderr. That includes the diagnostic that today prints `Next: repair alignment.yaml` for `CONTRACT_CHANGED`. The Guard must not append `gate.blocked_by` or set `recover_to`.
- User-authority codes for this halt are `CONTRACT_CHANGED`, every `SCOPE_DRIFT_*` code, and an unresolved current-task Decision (`OPEN_DECISION` at align/entry, `DECISION_UNRESOLVED` at Gate). Repairable rejections — `OPEN_LOOP`, unfrozen alignment, incomplete test plan, evidence preflight failure — keep their repair diagnostic, exit `1`, and emit neither `POLICY: USER_AUTHORITY_REQUIRED` nor `DIRECTIVE: HALT_AND_WAIT`.
- `align check`, `align status`, and `align diff` do not persist Findings, task data, or convergence bookkeeping.
- `recover_to: ESCALATED` is not an executable Guard or `resume` route. After `DECISION: CONTINUE`, `recover_to` still describes typed recovery for non-authority blockers. `harness resume` refuses a user-authority code instead of transitioning.
- `harness gate` validates task, blocker documents, and convergence metadata before any write. Schema-invalid convergence already fails closed; keep that, and make the failure byte-identical. Compute the decision first, then persist one coherent task write of assessment, state, iteration, and convergence metadata. A validation error exits `2` and leaves `.harness/current-task.yaml` byte-identical. Exit `1` remains the wrong-phase result; exit `2` remains corrupt task or metadata.
- Preserve Gate-only convergence sequence. `PASS` in the first line is the current-fact `PASS` defined above:

```text
GATING + PASS                                  -> CONVERGED
GATING + blocked/new fingerprint               -> BLOCKED, DECISION: CONTINUE
GATING + blocked/authority or loop guard       -> BLOCKED -> ESCALATED, DECISION: ESCALATED
IMPLEMENTING + user-authority Guard rejection  -> IMPLEMENTING, DIRECTIVE: HALT_AND_WAIT
```

The last line is a Guard rejection, not a Gate outcome. Agent reports the blocker and waits. It must not force `GATING` or invoke Gate to obtain a terminal status.

Phase 1 acceptance is behavioral, through the public CLI. These checks ship with the Phase 1 code, not in a later phase:

1. `harness gate` outside `GATING`, including a repeated call after `ESCALATED`, exits `1` and preserves task bytes.
2. User-authority Guard rejection leaves state, `gate.status`, `gate.blocked_by`, iteration, and convergence metadata unchanged. An audit Finding is asserted separately. `align check`, `align status`, and `align diff` leave every `.harness/` file byte-identical under drift and open-Decision cases.
3. Generic `harness transition BLOCKED|CONVERGED|ESCALATED` cannot bypass Gate from any working state, with or without blockers.
4. The `ESCALATED` inbound set is exactly `{BLOCKED}`. This assertion lives in a dedicated test module so editing the ordinary transition-table tests does not silently update it.
5. Live drift at `GATING` escalates `USER_AUTHORITY_REQUIRED`. A stale `blocked_by` entry, or an open alignment Finding that the fresh check does not reproduce, does not escalate. Current `PASS` converges and deletes the fingerprint. An injected Finding without live drift does not escalate.
6. `harness resume` on `BLOCKED` with a user-authority blocker exits `2` and stays `BLOCKED`.
7. Malformed present convergence metadata exits `2` and leaves `current-task.yaml` byte-identical.
8. User-authority stderr contains `POLICY: USER_AUTHORITY_REQUIRED` and `DIRECTIVE: HALT_AND_WAIT`, and does not recommend `harness gate`, `SPECIFYING`, `decision accept`, or `align freeze`.

## Phase 2 — Stable CLI Guidance Contract

Phase 1 ships the two halt lines. Phase 2 makes Gate directives stable and points Skills at those lines. Do not add `STATUS` or `BLOCKER subject=` until a grammar is specified: one line, a code matching `[A-Z0-9_]+`, and a quoted subject with defined escaping. Until then, user-authority stderr is:

```text
POLICY: USER_AUTHORITY_REQUIRED
DIRECTIVE: HALT_AND_WAIT
```

- User-authority Guard rejection: exit `1`; those two lines on stderr. No `DECISION:`. Human-readable detail may follow and must not contain an autonomous command that contradicts `HALT_AND_WAIT`.
- Repairable rejection: exit `1`; no `DIRECTIVE` line. Existing repair text remains the guidance. Absence of `DIRECTIVE` on that command is not `HALT_AND_WAIT`.
- Successful `harness gate`: exit `0`; `DECISION:` on stdout, keeping the existing spelling and parentheticals. `DECISION: CONTINUE` also prints `DIRECTIVE: RESUME_TYPED_RECOVERY` on stdout. `DECISION: CONVERGED` and `DECISION: ESCALATED` print `DIRECTIVE: NONE` and never print `RESUME_TYPED_RECOVERY`. Exit code alone is never a convergence decision.
- Invalid Harness state: exit `2`; no `DIRECTIVE`, and no task write.
- `DIRECTIVE` values: `HALT_AND_WAIT`, `RESUME_TYPED_RECOVERY`, `NONE`. On `harness gate`, a missing or unrecognized directive is not permission to resume. An unrecognized directive on any command is not permission to run a free-text `Next:` line. `HALT_AND_WAIT` outranks generic retry guidance.
- Update `SKILL.md`, `skills/engineering-harness/SKILL.md`, `skills/convergence/SKILL.md`, `skills/quality-gate/SKILL.md`, and affected alignment guidance. `DECISION:` is stdout, and the persisted authority is `state` plus gate metadata. The `IMPLEMENTING` dispatch stops when the Guard prints `HALT_AND_WAIT` and reports to the user. Agents must not infer an executable command from free-text `Next:`.

Phases are sequential. Phase 2 does not reopen the Phase 1 write or escalation rules.

## Phase 3 — Executable Architecture Guardrails

Put the Phase 1 behavioral checks in a dedicated test module or marker that the repository test command runs (`python -m pytest tests/ -q`). Connect that target to CI when a CI workflow exists or is introduced. This repository currently has no `.github/workflows/`, so adding a test file does not by itself establish a CI gate.

Supplement with narrow static checks for `DECISION:` prints and convergence-metadata writes outside the Gate decision path. Do not treat strings quoted by tests, docs, or Skills as production output. Static checks cannot replace the behavioral tests; aliases and helpers can defeat a simple search.

## Compatibility and Error Handling

Legacy tasks lacking convergence metadata remain valid. Malformed present metadata fails without mutation. Preserve existing Gate decision spelling, state names, and the exit split above (`1` wrong phase, `2` corrupt state).

Current user-authority facts are the recomputed Decision and drift results in [Current Gate Facts](#current-gate-facts). Close or supersede an alignment audit Finding only if an existing explicit operator workflow already applies. When no such path exists, leave the Finding on disk and keep ignoring it on a clean recompute. Never carry an obsolete `gate.blocked_by` entry forward as authority. If the existing workflow cannot distinguish operator approval from Agent-issued CLI text, document that limitation rather than claiming authenticated authorization or weakening Gate/Guard invariants.

## Non-goals

- Autonomous commit, tag, push, publish, deploy, authorization, or Decision acceptance.
- Treating `HALT_AND_WAIT` text as physical control of an LLM.
- A new workflow engine, a new Finding-close path, a parallel Gate, a broad AST linter, or task-based file locks.
- Automatic closure of alignment audit Findings.
- Removing the explicit `IMPLEMENTING -> SPECIFYING` operator transition.
- Changing fingerprint field order, escalation precedence, or the default `max_iterations`.

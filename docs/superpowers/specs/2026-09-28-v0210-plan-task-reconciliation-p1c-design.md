# v0.2.10 Plan Task Reconciliation P1C Design

**Status:** Draft for review
**Scope:** P1C deterministic Q3/STRICT task-level Plan Reconciliation
**Depends on:** P0 final reconciliation, P1A authoritative Context integration, P1B read-only plan status

## 1. Purpose

P1C adds deterministic task-level Plan Reconciliation for Q3/STRICT tasks configured with:

```yaml
plan_reconciliation:
  enabled: true
  mode: task_and_final
```

P0 proves final disposition and current proof. P1C additionally proves that Harness accepted Plan Item lifecycle transitions in canonical order while implementation was in progress.

P1C addresses long-task drift, context compression, Agent restart, model switching, and multi-session recovery. It does not claim to observe unrecorded implementation activity. Its proof boundary is persisted Harness transitions and the facts validated when those transitions were accepted.

## 2. Goals

P1C must:

- require Q3 Plan Items to follow a deterministic `begin -> reconcile` lifecycle;
- permit only the canonical next item to begin;
- permit at most one active item;
- persist a replayable transition journal in canonical execution state;
- require complete item-owned proof when accepting `COMPLETE`;
- require an accepted current-task Decision for `SKIPPED` and `SUPERSEDED`;
- distinguish historical item proof from proof fresh against the final workspace;
- support item-local block and resume without changing top-level Harness task state;
- make exact command retries idempotent;
- serialize concurrent mutations and publish atomically;
- preserve P0, P1A, and P1B contracts outside deterministic P1C extensions;
- leave Q2/final and FAST/Q1 behavior unchanged.

## 3. Non-goals

P1C does not:

- author, rewrite, reorder, or semantically judge `plan.yaml`;
- remap execution history after Plan fingerprint change;
- synthesize history from existing execution dispositions;
- parse or synchronize Markdown checkboxes;
- choose a reason for `SKIPPED` or `SUPERSEDED`;
- accept Decisions automatically;
- run tests or collect evidence automatically;
- support multiple concurrently active Plan Items;
- add top-level Harness task states;
- project journal or proof-receipt bodies into Context or plan-status output;
- provide Gate Preview;
- create a generic event-store framework;
- provide cryptographic attestation or prevent direct operating-system file edits;
- claim that implementation work occurred between `begin` and `reconcile` beyond facts represented by accepted proof.

## 4. Effective Enablement

Task-level enforcement is active only when all conditions hold:

- persisted `plan_reconciliation.enabled` is exactly `true`;
- task profile is `STRICT`;
- persisted mode is `task_and_final`.

Behavior by profile and mode:

| Task configuration | Task-level behavior |
|---|---|
| Missing or disabled configuration | Do not read Plan artifacts |
| FAST/Q1, including ad hoc `enabled: true` | Do not read Plan artifacts |
| STANDARD/Q2 with `mode: final` | Existing v1 final-only behavior |
| STRICT/Q3 with `mode: task_and_final` | Require v2 journal and task-level enforcement |

Mutation commands invoked outside effective task-level enablement fail without opening Plan artifacts.

## 5. Authoritative Model

P1C keeps two canonical artifacts:

```text
plan.yaml
  canonical semantic Plan; execution mutations require matching fingerprint

plan-execution.yaml v2
  transitions[]  logically append-only accepted transition journal
  items{}        current projection produced by replay
  sequence       latest committed transition sequence
```

The journal and current projection live in one document so every mutation is one atomic publication. No second transition artifact or cross-artifact transaction is introduced.

`items` is not an independent source of truth. Replay of `transitions` must reproduce it exactly.

Untouched Plan Items are implicit `PENDING` and absent from `items`. P1C v2 does not persist explicit `PENDING` records.

## 6. Execution v2 Shape

Conceptual shape:

```yaml
version: 2

plan:
  path: .harness/plan.yaml
  fingerprint: sha256:...

sequence: 2

transitions:
  - sequence: 1
    item: P-001
    from: PENDING
    to: IN_PROGRESS
    action: BEGIN

  - sequence: 2
    item: P-001
    from: IN_PROGRESS
    to: COMPLETE
    action: RECONCILE
    evidence_refs:
      - unit-test-abc.json
    surface_refs:
      - src/service.py
    proof_receipt:
      head: abc123...
      workspace: sha256:...
      evidence:
        - ref: unit-test-abc.json
          sha256: sha256:...
          type: unit_test
          exit_code: 0
          commit: abc123...
          workspace_fingerprint: sha256:...

items:
  P-001:
    status: COMPLETE
    evidence_refs:
      - unit-test-abc.json
    surface_refs:
      - src/service.py
```

The final schema is closed. Every action has conditional required and forbidden fields.

### 6.1 Transition fields

Every transition requires:

- `sequence`: positive integer;
- `item`: canonical `P-*` identifier present in `plan.yaml`;
- `from`: replay state before transition;
- `to`: replay state after transition;
- `action`: one of `BEGIN`, `BLOCK`, `RESUME`, `RECONCILE`, `REFRESH_PROOF`.

No transition timestamp is stored. Sequence and accepted facts are authoritative; wall-clock order is not required for replay.

### 6.2 Proof receipt

A proof receipt is an immutable journal summary of facts validated when Harness accepted a proof mutation. It includes:

- exact Git HEAD;
- product workspace fingerprint;
- normalized evidence references;
- digest and relevant validated identity of each evidence record;
- normalized surface references when applicable.

A receipt does not embed full evidence output. It preserves enough identity to show which evidence payload and workspace Harness accepted.

Historical replay validates receipt structure and transition relationships. It does not require the old evidence file at a reference to remain byte-identical forever. Final proof validation separately validates current evidence files and requires their digests to match the latest proof receipt for each COMPLETE item.

### 6.3 Decision receipt

`SKIPPED` and `SUPERSEDED` reconciliation records include:

- `decision_id`;
- accepted Decision digest;
- current task ID;
- accepted status observed at mutation time.

Final assessment also requires the referenced Decision to remain accepted for the current task. Historical acceptance does not override current Decision authority.

## 7. Item Lifecycle

Allowed state transitions:

```text
PENDING     -> IN_PROGRESS                    BEGIN
IN_PROGRESS -> BLOCKED                       BLOCK
BLOCKED     -> IN_PROGRESS                    RESUME
IN_PROGRESS -> COMPLETE                      RECONCILE
IN_PROGRESS -> SKIPPED                       RECONCILE
IN_PROGRESS -> SUPERSEDED                    RECONCILE
COMPLETE    -> COMPLETE                      REFRESH_PROOF
```

No other transition is legal.

Rules:

- only the first nonterminal item in canonical Plan order may begin;
- the target of `BEGIN` must currently be implicit `PENDING`;
- no item may begin while another item is `IN_PROGRESS` or `BLOCKED`;
- `BLOCKED` is item-local and does not mutate top-level task state;
- `BLOCK` requires a non-empty reason;
- `RESUME` clears the current item-local block reason in the replay projection;
- terminal disposition is immutable;
- proof refresh cannot change terminal disposition, reason, Decision, or supersession relation.

`next_plan_item` remains the first absent or nonterminal item in canonical Plan order. An `IN_PROGRESS` or `BLOCKED` item remains the next item until reconciled.

## 8. CLI

P1C extends the existing `harness plan` command group.

### 8.1 Begin

```bash
harness plan begin P-001
```

Preconditions:

- top-level task state is `IMPLEMENTING`;
- task-level enforcement is active;
- execution is v2 and replay-valid;
- Plan fingerprint is fresh;
- target is canonical next item and implicit `PENDING`;
- no active item exists.

### 8.2 Block and resume

```bash
harness plan block P-001 --reason "waiting for API contract"
harness plan resume P-001
```

These commands only perform `IN_PROGRESS -> BLOCKED -> IN_PROGRESS`. They never call or replace top-level `harness resume`.

### 8.3 Complete

```bash
harness plan reconcile P-001 --complete \
  --evidence unit-test-abc \
  --surface src/service.py
```

`COMPLETE` reuses final P0 proof rules at mutation time:

- an item with test-case references requires fresh item-owned evidence covering those cases;
- an item with surfaces requires non-empty declared surface references present in the changed-path set;
- an item with both requires both proof branches;
- an item with neither has no valid COMPLETE branch;
- protected user-path rules continue to apply.

Proof insufficiency rejects the mutation and leaves the item `IN_PROGRESS`.

### 8.4 Skip

```bash
harness plan reconcile P-001 --skipped \
  --reason "requirement removed" \
  --decision DEC-031
```

`SKIPPED` requires:

- non-empty reason;
- Decision belonging to current task;
- Decision currently `ACCEPTED`.

### 8.5 Supersede

```bash
harness plan reconcile P-001 --superseded \
  --reason "split into narrower items" \
  --decision DEC-032 \
  --replacement P-004 \
  --replacement P-005
```

`SUPERSEDED` requires:

- non-empty reason;
- accepted current-task Decision;
- at least one replacement;
- every replacement present in canonical Plan;
- no self-reference or supersession cycle.

Supersession does not reorder execution. After terminal reconciliation, the next item remains the first nonterminal item in canonical Plan order.

### 8.6 Refresh final proof

```bash
harness plan refresh-proof P-001 \
  --evidence unit-test-final \
  --surface src/service.py
```

`REFRESH_PROOF`:

- only targets `COMPLETE`;
- is allowed in `IMPLEMENTING` or `VERIFYING`;
- validates proof against current HEAD/workspace;
- appends a new proof receipt;
- updates current `evidence_refs` and `surface_refs` projection;
- does not change disposition;
- preserves all earlier receipts.

If an evidence reference is overwritten with new bytes, current proof digest no longer matches the latest receipt. Final assessment remains blocked until `refresh-proof` records the new validated payload, even when the reference string is unchanged.

### 8.7 Upgrade execution

```bash
harness plan upgrade-execution
```

Upgrade is allowed only for an effectively enabled old Q3 execution where:

- execution is v1;
- Plan fingerprint is fresh;
- every existing record is `PENDING`;
- no item is `IN_PROGRESS`, `BLOCKED`, or terminal;
- task state is `SPECIFYING`, `PLANNED`, or `IMPLEMENTING`.

Upgrade publishes:

```yaml
version: 2
sequence: 0
transitions: []
items: {}
```

P1C never synthesizes journal history from progressed v1 state.

## 9. Idempotency and Concurrency

All mutation commands execute under the existing reentrant `telemetry_lock` and publish through atomic write. P1C does not introduce another process or file lock.

Exact semantic retries return exit 0 without changing bytes. Inputs are normalized before comparison:

- evidence refs are canonicalized, deduplicated, and sorted;
- surface refs are deduplicated and sorted;
- replacement IDs are deduplicated and ordered by canonical Plan order;
- reasons use persisted exact text after required non-empty validation.

A retry is exact only when action, normalized payload, current HEAD/workspace receipt, and referenced content digests equal the accepted transition. Reusing the same evidence filename after its content changes is not an exact retry; callers use `refresh-proof`.

Examples:

- retrying successful `begin` while its BEGIN remains the latest applicable state transition is a no-op;
- retrying successful `block` with the same reason while still blocked is a no-op;
- retrying `resume` after later transitions is not a no-op;
- retrying terminal reconciliation with different disposition or proof is rejected;
- retrying proof refresh with the same receipt is a no-op.

Before proof publication, the command captures HEAD/workspace, validates proof, captures HEAD/workspace again, and aborts without writing if either changed. `telemetry_lock` serializes Harness writers; the double snapshot detects concurrent product workspace mutation outside that lock.

## 10. Replay Interface

P1C introduces one pure replay boundary conceptually equivalent to:

```python
replay_plan_execution(plan, execution) -> ReplayResult
```

It performs no I/O and consumes no current Decision or evidence facts. Replay validates only journal structure, legal lifecycle transitions, canonical ordering, internally consistent receipt payloads, and equality between replay output and persisted `items`.

Current Decision acceptance, current evidence identity/freshness, latest-receipt byte matching, surface proof, and protected-path rules remain P0-layer semantics after successful replay. Callers load those facts through existing P0 seams; missing facts never instruct replay to perform I/O.

Replay validation order:

1. execution v2 structural validity;
2. Plan fingerprint equality;
3. `sequence == len(transitions)`;
4. for a non-empty journal, contiguous transition sequences starting at 1;
5. item membership in canonical Plan;
6. exact `from` match with replay state;
7. legal action/from/to combination;
8. canonical BEGIN order;
9. single-active-item invariant;
10. action-specific payload and receipt structural consistency;
11. REFRESH_PROOF lifecycle legality;
12. replayed projection equality with persisted `items`.

`sequence: 0`, `transitions: []`, and `items: {}` is a valid replay whose projection is empty. It is the required Q3 entry shape for `IMPLEMENTING`.

Replay returns:

- normalized current item projection;
- current active item, if any;
- canonical next item;
- latest proof receipt per COMPLETE item;
- typed replay issues in deterministic order.

Replay never repairs, drops, sorts, or guesses malformed journal events.

## 11. Error Model

Existing Plan errors remain authoritative where applicable:

- `PLAN_STALE`;
- `PLAN_PROOF_MISSING`;
- `PLAN_DISPOSITION_INVALID`;
- `PLAN_ITEM_UNRECONCILED`.

P1C adds two Gate blockers:

### `PLAN_TASK_LEVEL_REQUIRED`

Meaning: effective Q3 `task_and_final` task has v1 execution and cannot claim task-level history.

Category: `implementation`. Source: `null`. Recovery: `IMPLEMENTING`.

### `PLAN_SEQUENCE_INVALID`

Meaning: schema-valid v2 journal cannot be deterministically replayed, violates canonical order, or disagrees with current projection.

Category: `implementation`. Source: `null`. Recovery: `IMPLEMENTING`.

Both codes are registered in `RECOVERY_POLICY`. They never route `harness resume` to `SPECIFYING`, which is not a legal `BLOCKED` recovery transition.

CLI-only policy refusals:

- `PLAN_TASK_LEVEL_DISABLED`: mutation command invoked outside effective P1C enablement;
- `PLAN_MUTATION_NOT_ALLOWED`: command invoked in an unsupported top-level task state.

Mutation commands reuse `PLAN_SEQUENCE_INVALID`, `PLAN_PROOF_MISSING`, `PLAN_DISPOSITION_INVALID`, and `PLAN_STALE` for domain refusals.

Exit behavior:

| Condition | Exit/output |
|---|---|
| Mutation committed | 0 |
| Exact no-op retry | 0 |
| Policy/domain refusal | 1 with stable code on stderr |
| Malformed or schema-invalid Harness source | 2 with `INVALID_HARNESS_STATE:`; no stdout |
| Repository discovery failure | 1 with existing `ERROR:`; no stdout |

No failed command mutates canonical or repository bytes.

Assessment preserves existing early-return precedence:

1. either artifact missing returns only `PLAN_REQUIRED`;
2. fingerprint mismatch returns only `PLAN_STALE`;
3. a Q2/v2 mode-version mismatch returns only `PLAN_DISPOSITION_INVALID`;
4. a Q3/v1 execution returns only `PLAN_TASK_LEVEL_REQUIRED`;
5. a structurally invalid v2 replay returns only `PLAN_SEQUENCE_INVALID`;
6. only a structurally trusted replay proceeds to P0 Decision, disposition, current-proof, surface, and protected-path checks.

Task-level assessment returns at most one task-level blocker. It never appends sequence diagnostics beside missing, stale, mode/version, or P0 item blockers. Current Decision rejection remains `PLAN_DISPOSITION_INVALID`; current evidence staleness or latest-receipt byte mismatch remains `PLAN_PROOF_MISSING`.

## 12. Workflow Integration

### 12.1 Entry to implementation

For effective P1C tasks, `PLANNED -> IMPLEMENTING` requires:

- valid Plan;
- fresh execution fingerprint;
- execution v2;
- `sequence: 0`;
- empty journal;
- empty projection.

An old Q3 v1 task with only pending state may use safe upgrade before entry. A progressed v1 task cannot synthesize history; it remains in or recovers to `IMPLEMENTING`, where a fresh v2 execution must restart task-level tracking from an empty journal.

### 12.2 During implementation

The supported sequence is:

```text
begin current item
→ implement
→ optionally block/resume
→ reconcile terminal disposition
→ begin next item
```

Changing semantic Plan content makes the execution fingerprint stale. Validation returns only `PLAN_STALE`, with existing recovery to `IMPLEMENTING`, and does not evaluate task-level history or item proof. In `IMPLEMENTING`, callers must publish execution with the matching fingerprint before mutations continue; P1C does not preserve, synthesize, or remap old history.

Internal sequencing or equivalent implementation changes remain Plan-level adjustments under the existing contract. Only changes to Requirements, Acceptance Criteria, frozen Alignment inputs, declared scope, external interface, permission, persistence, or accepted Decisions use the existing explicit Realignment path to `SPECIFYING`. P1C introduces no Plan-drift state transition.

### 12.3 Entry to verification

`IMPLEMENTING -> VERIFYING` requires:

- replay-valid journal;
- no active item;
- every Plan Item terminal;
- accepted Decisions still valid;
- historical receipts structurally complete.

Current proof is allowed to be stale at this boundary because later Plan Items may have changed the workspace after earlier item reconciliation. Verification is the recovery phase for current proof; disposition and journal-structure failures recover to `IMPLEMENTING`.

### 12.4 Verification and review

Verification collects evidence against the final workspace, then uses `refresh-proof` for every COMPLETE item whose current proof is stale or whose latest receipt no longer matches current evidence bytes.

`VERIFYING -> REVIEWING`, review preflight, and Gate re-run:

- v2 replay validation;
- latest proof receipt/content digest match;
- current evidence freshness against final HEAD/workspace;
- existing P0 final disposition and proof checks.

A review fix that changes product workspace may require new final evidence and proof refresh. Control-plane-only requirement, review, Gate, or task metadata writes do not stale product proof.

## 13. P0, Context, and Status Compatibility

### 13.1 P0

Q2 final-only tasks retain v1 execution and existing P0 behavior. P1C does not require Q2 journal overhead.

Q3 Gate blocker assessment first applies required-artifact and fingerprint early returns, then validates task-level replay, then applies existing final rules to replayed current projection. A task-level structural failure returns its one blocker and does not emit P0 item blockers in the same assessment.

P0 final-state meaning remains independently available for Context/status projection. Task-level blockers are never passed to `plan_context_summary` as final blockers.

### 13.2 P1A Context

P1A continues treating `plan-execution.yaml` as one authoritative source. Existing source hash, manifest, reference, omission accounting, and integrity behavior apply to v2 bytes without adding a new source.

Compact/full Context does not expose journal, receipts, reasons, Decisions, or item bodies. Existing Plan summary shape remains unchanged.

For task-level-required or replay-invalid execution, `next_plan_item` is `null` because canonical execution position is untrustworthy. `final_status` remains the P0-only final-state result and does not consume task-level blockers.

### 13.3 P1B status

`harness plan status` loads v1 or v2 according to task mode and reuses the extended Plan assessment. Its JSON/text shape remains unchanged.

For trusted v2 execution:

- progress comes from replayed current projection;
- `next_plan_item` keeps existing semantics;
- `final_status` is derived only from the independent P0 final assessment;
- public blockers are P0 item disposition/proof blockers after task-level early returns have passed.

For task-level-required or replay-invalid execution, `progress` and `next_plan_item` are `null`, and blockers contain only `PLAN_TASK_LEVEL_REQUIRED` or `PLAN_SEQUENCE_INVALID` respectively. `final_status` still represents only P0 final state, so a report may contain `final_status: pass` together with a task-level blocker. This distinction is intentional: final disposition and task-level history are separate claims. Missing and stale artifacts remain existing P0 failures and therefore keep `final_status: blocked`.

The public blocker list follows section 11 early-return ordering. The P0 result used solely for `final_status` is computed separately over schema-valid current disposition and does not add hidden P0 blockers after a task-level early return. Journal and receipt bodies are never rendered.

## 14. Migration

Compatibility matrix:

| Task | Required execution |
|---|---|
| Missing/disabled configuration | No Plan reads |
| FAST/Q1 | No Plan reads |
| STANDARD/Q2 `final` | v1 |
| New STRICT/Q3 `task_and_final` | v2 |
| Old STRICT/Q3 v1, all pending | Controlled upgrade |
| Old STRICT/Q3 v1, progressed | Recover/remain in IMPLEMENTING; publish fresh empty v2 execution without synthesized history |

The loader supports both schema versions but effective task configuration chooses the legal version. A v2 document on a Q2/final task is `PLAN_DISPOSITION_INVALID` and does not silently opt that task into task-level enforcement. A v1 document on Q3/task_and_final returns `PLAN_TASK_LEVEL_REQUIRED`.

Q1 escalation to Q3 continues to restart normal contract flow at `SPECIFYING`; fresh v2 execution is required before implementation.

## 15. Verification Strategy

Only impact-related focused tests are run. Full repository suite remains outside Harness workflow policy.

### 15.1 Schema and replay unit tests

Cover every legal transition and reject:

- sequence gaps, duplicates, and reorder;
- wrong `from` state;
- unknown Plan Item;
- BEGIN for a non-next item;
- multiple active items;
- terminal overwrite;
- terminal re-begin;
- projection/journal mismatch;
- schema-valid receipt payload inconsistent with its transition refs;
- REFRESH_PROOF for non-COMPLETE item.

Malformed action payloads or missing schema-required receipt fields are invalid Harness state with exit 2, not `PLAN_SEQUENCE_INVALID`.

Property tests generate valid journals and verify deterministic replay. Mutating any event must either change the replay digest consistently or return a typed issue; it must never be silently ignored.

### 15.2 CLI integration tests

Cover:

- begin/block/resume/reconcile/refresh-proof happy paths;
- exact retries with byte-identical no-op behavior;
- conflicting retries with zero writes;
- unsupported state/profile/mode;
- missing, stale, malformed, and schema-invalid sources;
- workspace race before publication;
- atomic-write rollback;
- concurrent mutation where only one publication wins;
- stdout/stderr and exit contracts;
- read/write isolation for disabled, FAST, and Q2 tasks.

### 15.3 Workflow and Gate tests

Cover:

- Q3 v1 blocker and safe upgrade;
- progressed v1 refusal;
- invalid journal recovery;
- Q2/v2 returning only `PLAN_DISPOSITION_INVALID` before replay;
- empty v2 journal replaying successfully to `{}`;
- nonterminal final blocking;
- current Decision rejection remaining `PLAN_DISPOSITION_INVALID` after successful replay;
- unknown replacement, self-reference, and supersession cycle remaining `PLAN_DISPOSITION_INVALID`;
- latest-receipt/current-evidence mismatch remaining `PLAN_PROOF_MISSING` after successful replay;
- historical receipt remaining valid after later workspace change;
- current proof becoming stale after later workspace change;
- proof refresh restoring final readiness;
- review-fix evidence refresh;
- P0 blocker ordering after successful replay;
- Context/status body isolation;
- unchanged Q2 and FAST regressions.

## 16. Acceptance Criteria

P1C is complete when:

1. effective Q3 tasks require execution v2 before implementation;
2. only canonical next item can begin;
3. no more than one item can be active;
4. every legal lifecycle mutation is journaled and atomically projected;
5. illegal, stale, malformed, raced, or conflicting mutations write nothing;
6. COMPLETE requires proof fresh at reconciliation time;
7. SKIPPED and SUPERSEDED require accepted current-task Decisions;
8. historical proof survives later workspace changes through immutable receipts;
9. final proof requires current evidence matching latest receipt and final workspace;
10. exact retries are byte-identical no-ops;
11. Gate replay detects journal/projection mismatch and invalid sequence;
12. Q2 remains final-only v1;
13. FAST/Q1 never inspect adjacent Plan artifacts;
14. Context and status remain compact and body-free;
15. old progressed Q3 state is never converted into fabricated history;
16. no new top-level Harness state is introduced.

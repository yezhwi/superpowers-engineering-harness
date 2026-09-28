# Superpowers Engineering Harness v0.2.10
## Plan Execution Reconciliation — Implementation Contract

> Status: P0 implemented; P1/P2 planned
> Authority: this document resolves implementation ambiguity in
> `docs/Superpowers-Engineering-Harness-v0.2.10-Plan-Execution-Reconciliation.md`.
> Scope: deterministic control-plane support for reconciling implementation-plan items.

## 1. Goal and non-goal

Goal: for an enabled task, prevent `DONE` when any canonical implementation-plan item lacks an allowed terminal reconciliation state and required proof.

This feature closes a gap left by Requirement/Test Plan coverage. It does not prove that a plan was optimal or replace Requirement, Alignment, Test Plan, Evidence, Review, or existing Realignment.

```text
Requirement / Alignment: what is authorized
Implementation plan: intended work decomposition
Plan reconciliation: whether every intended item was dispositioned
Evidence: proof for executable verification
Gate: completion decision
```

`Requirement` remains authoritative. A plan item cannot create, weaken, or replace acceptance criteria.

## 2. Canonical artifacts

Enabled tasks use two canonical files:

```text
.harness/plan.yaml
.harness/plan-execution.yaml
```

Markdown plans are human-readable source material or projections. Gate never parses Markdown and Markdown checkboxes are never authoritative.

`plan.yaml` contains ordered, stable plan item definitions. `plan-execution.yaml` contains only execution disposition and references. Neither duplicates requirement statements, evidence payloads, or Alignment content.

### 2.1 `plan.yaml`

```yaml
version: 1
items:
  - id: P-001
    intent: Implement cache invalidation.
    requirement_refs: [REQ-001]
    invariant_refs: [INV-001]
    surfaces: [src/cache.py]
  - id: P-002
    intent: Add cache invalidation regression coverage.
    test_case_refs: [REQ-001/TC-001]
    surfaces: [tests/test_cache.py]
  - id: P-003
    intent: Update cache architecture documentation.
    surfaces: [docs/cache.md]
```

Rules:

- `version` is integer `1`.
- IDs match `P-[0-9]+`, are unique, and are ordered by their list position.
- IDs are never reused during a task. Retaining prior IDs and appending replacements is an authoring rule, not a P0 Gate guarantee; Gate validates only current artifacts.
- `intent` is required and descriptive only. Acceptance semantics belong to referenced `REQ-*`, `TC-*`, and `INV-*` records.
- `requirement_refs`, `test_case_refs`, `invariant_refs`, and `surfaces` are optional. Supplied requirement/invariant references must resolve to existing records. Test-case references are qualified `REQ-<n>/TC-<n>` or `INV-<n>/TC-<n>` and must resolve within named parent record. Surface paths must be valid repository-relative paths, contain no `..`, and remain inside repository; they need not exist before implementation.
- A plan item has no nested checklist. One item is one reconciliation unit.

### 2.2 `plan-execution.yaml`

```yaml
version: 1
plan:
  path: .harness/plan.yaml
  fingerprint: sha256:<semantic-plan-digest>
items:
  P-001:
    status: COMPLETE
    surface_refs: [src/cache.py]
  P-002:
    status: COMPLETE
    evidence_refs: [integration-test-<digest>.json]
    surface_refs: [tests/test_cache.py]
  P-003:
    status: SKIPPED
    reason: Public behavior and architecture documentation are unchanged.
```

Rules:

- Every execution key must exist in `plan.yaml`. At final reconciliation every plan item must have one execution record; initialization may contain no item records or only `PENDING` / `IN_PROGRESS` / `BLOCKED` records.
- `fingerprint` is `sha256:` plus SHA-256 64-hex digest of canonical UTF-8 JSON containing only `version` and ordered item fields (`id`, required `intent`, references, surfaces). Object keys are sorted; item-list order is preserved; omitted `requirement_refs`, `test_case_refs`, `invariant_refs`, and `surfaces` normalize to empty arrays; execution state, Markdown, and checkbox projections are excluded.
- `evidence_refs` resolve using existing `evidence_path` rules and must reference existing valid `evidence/*.json` records. For a test-case item, resolve each qualified plan reference to its named parent record's bare `TC-*` case; inspect only item-owned `evidence_refs`, never unrelated global evidence. Automated cases use existing case `tests` node coverage (`record_covers_test` and `command_covers_test`); manual cases use bare `TC-*` in `covered_test_cases`. Evidence JSON never contains qualified plan-reference strings.
- `surface_refs` must be a subset of declared item surfaces. They are mechanically checked against `changed_paths_since(task.git.base_commit)`, never `business_paths()`, Agent-authored `impact.yaml`, or `scope.owned_paths`. They are not evidence. While `protected_paths_fingerprint(risk.user_changes.paths)` equals stored `risk.user_changes.fingerprint`, every path in `risk.user_changes.paths` is removed from that set before the check. The fingerprint argument is the full stored path list, not `surface_refs`. If that aggregate fingerprint differs, P0 never treats any initial user path as plan surface proof. `PLAN_PROTECTED_PATHS_MODIFIED` applies only during final reconciliation to a `COMPLETE` item with non-empty `surfaces` when its `surfaces` or `surface_refs` intersects `risk.user_changes.paths`.
- Existing evidence files and types remain authoritative. v0.2.10 adds neither `EV-*` IDs nor `CHANGE` / `VERIFICATION` evidence types.

## 3. Item states and terminal constraints

Allowed states:

```text
PENDING | IN_PROGRESS | COMPLETE | SKIPPED | SUPERSEDED | BLOCKED
```

Final reconciliation permits only `COMPLETE`, `SKIPPED`, and `SUPERSEDED`.

Branch selection uses non-empty arrays. An omitted array and `[]` are the same; an empty array cannot pass by vacuous truth.

| State | Required fields | Constraint |
|---|---|---|
| `COMPLETE`, non-empty `test_case_refs` and empty `surfaces` | non-empty `evidence_refs` | Resolve each qualified plan ref to parent-owned bare case; item-owned fresh successful evidence covers its existing automated node bindings or manual bare `TC-*` claim. |
| `COMPLETE`, empty `test_case_refs` and non-empty `surfaces` | non-empty `surface_refs` | Every ref is declared by the item and appears in the mechanical path set from section 2.2. |
| `COMPLETE`, non-empty `test_case_refs` and non-empty `surfaces` | non-empty `evidence_refs`, non-empty `surface_refs` | Both preceding proof rules apply. |
| `COMPLETE`, both arrays empty | — | `PLAN_DISPOSITION_INVALID`. Use `SKIPPED` or `SUPERSEDED`. |
| `SKIPPED` | non-empty `reason` | No silent omission. |
| `SUPERSEDED` | non-empty `reason`, non-empty `superseded_by` | `superseded_by` is a list of `P-*` IDs. Every replacement exists in the current plan. A self-reference or longer loop is a cycle. |
| `PENDING`, `IN_PROGRESS`, `BLOCKED` | — | Final reconciliation fails. |

`SKIPPED` and `SUPERSEDED` always require explicit reason. A supplied `decision_id` must resolve to an ACCEPTED `DEC-*` for current task. Gate does not infer whether semantic scope changed from item text; skills or human workflow decide when a Decision is required. Frozen-input changes remain existing Alignment drift.

## 4. Lifecycle integration

No top-level Harness state is added.

```text
PLANNED
  └─ plan initialized for enabled STANDARD/STRICT task
       ↓
IMPLEMENTING
  └─ P1: Q3 task-level reconciliation guidance/checks where enforceable
       ↓
VERIFYING
  └─ collect normal command evidence
       ↓
final plan reconciliation
       ↓
REVIEWING → GATING → CONVERGED → DONE
```

Final reconciliation is a `quality_gate.run_gate` check. Therefore it runs both:

- as preflight for `VERIFYING → REVIEWING`; and
- in final `harness gate`.

This makes reconciliation re-evaluate after a fix, evidence freshness change, or plan artifact change. It is not a one-time assertion before verification.

Enabled STANDARD/STRICT tasks must have valid `plan.yaml` and initialized `plan-execution.yaml` before `PLANNED → IMPLEMENTING`. Initialization means both schemas pass, `plan.path` is exactly `.harness/plan.yaml`, and fingerprint matches current canonical plan. Item records may be absent or nonterminal at this entry. FAST never loads Plan Reconciliation artifacts unless a future explicit opt-in is defined.

P0 final Gate validates final state/proof only. It does not infer unrecorded temporal execution order or add state transitions. `task_and_final` is persisted configuration in P0; deterministic Q3 task-level enforcement is P1 work.

## 5. Gate blockers and recovery

Gate emits only defined, non-overlapping codes:

| Code | Meaning | Category | Recovery |
|---|---|---|---|
| `PLAN_REQUIRED` | enabled task lacks one or both plan artifacts | implementation | `IMPLEMENTING` |
| `PLAN_STALE` | stored fingerprint differs from canonical plan | implementation | `IMPLEMENTING` |
| `PLAN_ITEM_UNRECONCILED` | item missing or has nonterminal state | implementation | `IMPLEMENTING` |
| `PLAN_PROOF_MISSING` | COMPLETE lacks required valid support | verification | `VERIFYING` |
| `PLAN_PROTECTED_PATHS_MODIFIED` | final COMPLETE surface item intersects protected initial-user path after aggregate fingerprint changed | implementation | `IMPLEMENTING` |
| `PLAN_DISPOSITION_INVALID` | schema-valid skip, supersede, reference, or cycle failure | implementation | `IMPLEMENTING` |

These codes must be registered in `RECOVERY_POLICY`. Each item-derived blocker sets `GateBlocker.source` to its `P-*` ID so blocker fingerprints distinguish items. Empty paths, absolute paths, and paths containing `..` are schema-invalid and remain `InvalidHarnessState` with exit 2. `PLAN_DISPOSITION_INVALID` applies only after schema validation, including a plan ref whose named parent lacks its bare case, a `surface_ref` absent from that item's `surfaces`, an execution key absent from `plan.yaml`, a `superseded_by` value that is not a non-empty list of `P-*` IDs, and any cycle. A declared path that is absent from the mechanical change set is `PLAN_PROOF_MISSING`, not a disposition failure. For qualifying protected-path condition, emit only `PLAN_PROTECTED_PATHS_MODIFIED` for surface proof; evidence insufficiency on same COMPLETE item still emits `PLAN_PROOF_MISSING`. Nonterminal items emit only `PLAN_ITEM_UNRECONCILED`; `SKIPPED` and `SUPERSEDED` do not emit protected-path blocker. No `PLAN_DRIFT_UNRESOLVED` code is added: frozen-contract drift remains existing `CONTRACT_CHANGED` / scope-drift handling.

## 6. Plan revision and Alignment

Updating semantic plan fields produces a new fingerprint. On mismatch, reconciliation reports only `PLAN_STALE` and does not evaluate item proof/disposition until a caller writes matching fingerprint.

- Retaining prior IDs and appending replacements is required authoring practice, but P0 validates current artifacts only. Detecting deletion across independently rewritten files requires a future append-only ID registry.
- Internal sequencing or equivalent implementation approach: revise plan, map retained prior item to `SUPERSEDED`/`SKIPPED` with reason where applicable, then reconcile in `IMPLEMENTING`.
- Change to Requirements, Acceptance Criteria, frozen Alignment inputs, declared scope, external interface, permission, persistence, or accepted Decision: use existing `IMPLEMENTING → SPECIFYING` Realignment flow. Do not create parallel plan-drift workflow.

## 7. Context and status

This section is P1. P0 Context ignores Plan Reconciliation artifacts. P1 makes `plan.yaml` and `plan-execution.yaml` authoritative Context sources, extends closed Context schemas/freshness inputs, and increments projection version.

Context may project:

```yaml
plan_reconciliation:
  enabled: true
  next_plan_item: P-003
  final_status: blocked
```

`next_plan_item` is advisory: first nonterminal item in canonical plan order, or null when all items are terminal. `final_status` is only `pass` or `blocked`. Neither field authorizes work or replaces `harness resume`, which continues to route only a `BLOCKED` task from typed Gate blockers.

`harness plan status` is read-only projection. Gate preflight is existing `harness gate preflight`; no separate Gate Preview command is introduced.

## 8. Enablement and migration

Task state persists enablement at creation/classification:

```yaml
plan_reconciliation:
  enabled: true
  mode: final # final | task_and_final
```

| Profile | New task default |
|---|---|
| FAST / Q1 | `{enabled: false}`; `mode` omitted |
| STANDARD / Q2 | `{enabled: true, mode: final}` |
| STRICT / Q3 | `{enabled: true, mode: task_and_final}` |

Compatibility:

- Existing tasks lacking `plan_reconciliation`: disabled.
- When `plan_reconciliation.enabled` is absent or `false`, both `PLANNED → IMPLEMENTING` and Gate skip all plan artifact reads and validation. Disabled tasks may pass even when adjacent plan files are absent or malformed.
- `harness task escalate` from Q1 to Q2/Q3 enables the feature (`final` for Q2; `task_and_final` for Q3). Existing FAST escalation restarts task at `SPECIFYING`; missing plan blocks next `PLANNED → IMPLEMENTING`, not escalation itself.
- Enabling feature with absent/invalid plan artifacts fails closed.

## 9. P0 acceptance tests

P0 must add deterministic fixture tests for:

1. enabled Q2 plan may enter `IMPLEMENTING` with valid empty or nonterminal execution records;
2. enabled Q2 complete plan with valid references passes preflight and final Gate;
3. missing plan artifact returns `PLAN_REQUIRED` at `PLANNED → IMPLEMENTING`;
4. changed semantic plan returns only `PLAN_STALE`;
5. canonical fingerprint ignores checkbox-only Markdown changes;
6. pending/missing final item returns `PLAN_ITEM_UNRECONCILED`;
7. COMPLETE test item without fresh evidence covering every `TC-*` returns `PLAN_PROOF_MISSING`;
8. surfaces-only COMPLETE accepts a changed `docs/` or `tests/` path from `changed_paths_since(task.git.base_commit)`; a declared path that is unchanged or still covered by an unchanged `risk.user_changes` fingerprint returns `PLAN_PROOF_MISSING`;
9. changed aggregate protected-path fingerprint plus a final `COMPLETE` surface item intersecting protected path returns only `PLAN_PROTECTED_PATHS_MODIFIED` for surface proof; `PENDING` remains `PLAN_ITEM_UNRECONCILED`, and `SKIPPED`/`SUPERSEDED` ignore protected surfaces;
10. qualified `REQ-*/TC-*` and `INV-*/TC-*` references resolve to bare case within named parent; missing parent case returns `PLAN_DISPOSITION_INVALID`; automated and manual cases apply existing bare-case/node evidence semantics only to item-owned `evidence_refs`;
11. test-case plus surface item requires both evidence coverage and surface-path proof; evidence insufficiency remains `PLAN_PROOF_MISSING` even when protected surface proof returns `PLAN_PROTECTED_PATHS_MODIFIED`;
12. empty, absolute, or `..` paths fail schema validation with exit 2; a schema-valid `surface_ref` outside that item's `surfaces`, or an execution key absent from `plan.yaml`, returns `PLAN_DISPOSITION_INVALID`;
13. invalid skip/supersede, unknown or non-ACCEPTED Decision, unknown evidence reference, a `superseded_by` value that is not a non-empty `P-*` list, and a replacement cycle, including a self-reference, return `PLAN_DISPOSITION_INVALID`;
14. each `PLAN_*` blocker routes through `harness resume` only after `harness gate` has persisted `BLOCKED`; assert one blocker per recovery test;
15. old task, Q1 FAST task, and any disabled task with malformed adjacent plan artifacts remain valid without plan reads;
16. Q1 escalation to Q2/Q3 persists correct enablement/mode, restarts normal contract flow, and defers missing-plan failure to `PLANNED → IMPLEMENTING`;
17. frozen-contract change still follows existing Realignment path.

Tests are control-plane fixtures. They do not claim that Harness observed an Agent's context compression, token use, or unrecorded tool calls.

## 10. Delivery slices

### P0

- schemas and canonical artifact loaders;
- task enablement/migration;
- semantic fingerprint;
- final Gate/preflight validation;
- typed blockers and recovery policy;
- deterministic acceptance tests.

### P1

- evidence/surface reference refinement;
- `harness plan status`;
- Context projection;
- Q3 task-level persistence guidance and checks where deterministically enforceable.

### P2

- Markdown checkbox projection;
- automatic mechanical reconciliation assistance;
- richer reports.

## 11. Explicit exclusions

v0.2.10 does not:

- parse arbitrary Markdown as Gate truth;
- infer semantic validity of an implementation plan;
- automatically decide why an item is skipped or superseded;
- create new top-level state machine states;
- replace Alignment drift handling;
- introduce new generic evidence namespaces/types;
- attest Agent context recovery, token cost, or unseen actions.

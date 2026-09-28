# v0.2.10 Plan Task Reconciliation P1C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic Q3/STRICT task-level Plan Item reconciliation with replayable execution v2, proof/Decision receipts, locked mutation commands, lifecycle enforcement, and compact Context/status projection.

**Architecture:** Add one pure `plan_execution` domain module for v2 replay and transition projection. Keep repository reads, current proof/Decision validation, workspace race detection, locking, and atomic publication in `plan_reconciliation`. Extend reconciliation assessment so one loaded artifact pair yields both public early-return blockers and independent P0 final blockers. Keep CLI handlers thin and preserve v1 Q2 plus FAST/Q1 isolation.

**Tech Stack:** Python 3.11+, argparse, dataclasses, hashlib/json, PyYAML, jsonschema, pytest, existing `telemetry_lock`, `transaction.atomic_write`, workspace/evidence/Decision seams

**Spec:** `docs/superpowers/specs/2026-09-28-v0210-plan-task-reconciliation-p1c-design.md`

**Contract:** `docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md`

## Global Constraints

- Implement P1C only. Do not implement Markdown synchronization, automatic reconciliation, richer reports, or Gate Preview.
- Task-level enforcement applies only to persisted `enabled: true`, profile `STRICT`, mode `task_and_final`.
- Disabled and FAST/Q1 paths return before opening Plan artifacts. Q2/final remains v1 final-only.
- Preserve assessment precedence exactly: `PLAN_REQUIRED`, `PLAN_STALE`, Q2/v2 `PLAN_DISPOSITION_INVALID`, Q3/v1 `PLAN_TASK_LEVEL_REQUIRED`, invalid v2 replay `PLAN_SEQUENCE_INVALID`, then P0 checks.
- Missing artifacts are blocker data. Malformed present artifacts are invalid Harness state.
- Replay is pure: no filesystem, Git, evidence, Decision, clock, sorting repair, or guessed history.
- Execution v2 journal and `items` projection publish as one atomically replaced YAML document.
- All execution mutations reuse existing reentrant `telemetry_lock`; add no lock.
- Exact semantic retries leave `plan-execution.yaml` byte-identical.
- Never synthesize events from progressed v1 state.
- `final_status` remains independent P0 truth. Task-level blockers alone never make it blocked.
- Do not expose journal, receipt, reason, Decision, evidence-reference, surface-reference, or item bodies through Context/status.
- Run focused section 15 tests only. Never run full repository suite.
- Observe RED before each production change.
- Every commit requires explicit user authorization. Never stage unrelated or untracked user files.

## Planned Internal Interfaces

`src/harness/plan_execution.py` owns pure state mechanics:

```python
@dataclass(frozen=True)
class ReplayIssue:
    code: str
    message: str

@dataclass(frozen=True)
class ReplayResult:
    items: dict[str, dict]
    active_item: str | None
    next_item: str | None
    latest_proof_receipts: dict[str, dict]
    issues: tuple[ReplayIssue, ...]


def replay_plan_execution(plan: dict, execution: dict) -> ReplayResult: ...

def append_plan_transition(
    plan: dict,
    execution: dict,
    transition: dict,
) -> dict: ...
```

`replay_plan_execution` validates structural relationships not expressible in JSON Schema. `append_plan_transition` appends one already-authorized normalized transition, derives `items` only through replay, and returns a new document without mutating inputs.

`src/harness/plan_reconciliation.py` owns loaded/current facts:

```python
@dataclass(frozen=True)
class PlanAssessment:
    blockers: tuple[GateBlocker, ...]
    final_blockers: tuple[GateBlocker, ...]
    projection: dict[str, dict] | None
    replay: ReplayResult | None

@dataclass(frozen=True)
class PlanMutationRequest:
    action: str
    item_id: str | None = None
    disposition: str | None = None
    reason: str | None = None
    evidence_refs: tuple[str, ...] = ()
    surface_refs: tuple[str, ...] = ()
    decision_id: str | None = None
    replacements: tuple[str, ...] = ()


def assess_plan_reconciliation_documents(...) -> PlanAssessment: ...

def mutate_plan_execution(
    harness_dir: Path,
    task: dict,
    request: PlanMutationRequest,
) -> bool: ...  # True committed, False exact byte-preserving retry
```

Mutation function owns policy validation, lock acquisition, artifact reload, current proof/Decision receipts, double workspace snapshot, exact retry detection, and atomic publication. Domain refusals raise stable `PlanMutationError(code)`; malformed present source raises `PlanArtifactError`/existing source errors.

---

### Task 0: Harness contract, plan, and legal implementation entry

**Files:**
- Commit after authorization: `docs/superpowers/plans/2026-09-28-v0210-plan-task-reconciliation-p1c.md`
- Modify through Harness workflow only: `.harness/current-task.yaml`, `.harness/requirements.yaml`, `.harness/invariants.yaml`, `.harness/alignment.yaml`, `.harness/impact.yaml`, `.harness/plan.yaml`, `.harness/plan-execution.yaml`
- Create: `.superpowers/sdd/2026-09-28-v0210-plan-task-reconciliation-p1c/progress.md`

**Interfaces:**
- Consumes approved P1C design/contract and this implementation plan
- Produces frozen Task Contract, Minimal Implementation Decision, canonical Plan, and new task state `IMPLEMENTING`

- [ ] **Step 1: Review plan against approved design**

Verify every design section 15 case maps to Tasks 1-6 below. Confirm no P2 behavior, no new top-level state, no new lock, and no full-suite command appears.

- [ ] **Step 2: Request authorization and commit only implementation plan**

After explicit authorization:

```bash
git add docs/superpowers/plans/2026-09-28-v0210-plan-task-reconciliation-p1c.md
git commit -m "docs: plan Q3 task-level reconciliation"
```

- [ ] **Step 3: Create and classify new Harness task**

Use supported Harness commands to create next task ID, classify it Q3/STRICT, and persist P1C acceptance criteria. Do not edit task state directly.

Task Contract must cover:

- v2 replay and projection equality;
- task-level lifecycle/order/single-active invariants;
- proof and Decision receipt acceptance;
- exact idempotency, workspace race detection, lock serialization, atomic write;
- assessment precedence and recovery;
- workflow entry/verification/review/Gate behavior;
- Context/status isolation and independent `final_status`;
- Q2 and FAST/Q1 regressions;
- no synthetic v1 history.

- [ ] **Step 4: Freeze Alignment and persist minimal implementation decision**

Use Task Contract and Minimal Implementation skills. Record reuse of existing artifact loader, P0 proof checks, Decision loader, `workspace.snapshot`, `telemetry_lock`, and `transaction.atomic_write`. Record new pure module as only new production seam. Add no dependency or persistence artifact.

- [ ] **Step 5: Persist canonical implementation Plan**

Create Plan Items matching Tasks 1-6. Because current runtime is pre-P1C, initialize this task with schema-valid execution format accepted by current workflow; do not fabricate P1C history while implementing P1C itself. Record bootstrap choice in task progress.

- [ ] **Step 6: Enter `IMPLEMENTING` legally**

Advance through supported transitions only. Confirm Minimal Implementation, test-plan, Alignment, and current Plan initialization checks pass.

---

### Task 1: Closed execution v2 schema and pure deterministic replay

**Files:**
- Modify: `src/harness/schemas/plan-execution.schema.json`
- Create: `src/harness/plan_execution.py`
- Create: `tests/test_plan_execution.py`
- Modify: `tests/test_schema_resources.py`
- Verify: `tests/test_task_contract.py`

**Interfaces:**
- Produces `ReplayIssue`, `ReplayResult`, `replay_plan_execution(...)`, and `append_plan_transition(...)`
- Preserves execution v1 schema for Q2
- Guarantees no I/O from pure replay/append module

- [ ] **Step 1: Write failing schema tests for v1/v2 closed union**

Add focused schema cases asserting:

- existing v1 documents remain valid;
- empty v2 `{sequence: 0, transitions: [], items: {}}` is valid;
- top-level, transition, proof receipt, Decision receipt, and projected item objects reject unknown fields;
- malformed action payloads fail schema: missing required fields, forbidden fields present, invalid paths/IDs/digests, empty reasons/replacements;
- each action enforces its required `from`, `to`, and payload family;
- `BEGIN`, `BLOCK`, `RESUME`, `RECONCILE`, and `REFRESH_PROOF` are only actions;
- receipt evidence identity includes normalized ref, raw-byte digest, evidence type/result, commit, and workspace fingerprint;
- Decision receipt includes ID, raw-byte digest, current task ID, and accepted status.

Use schema-level failures for malformed payloads; do not expect `PLAN_SEQUENCE_INVALID` for them.

- [ ] **Step 2: Run schema tests and verify RED**

```bash
pytest tests/test_schema_resources.py tests/test_plan_execution.py -k 'schema or empty_v2 or action_payload' -q
```

Expected: FAIL because schema accepts only v1 and module does not exist.

- [ ] **Step 3: Extend schema as closed `oneOf` v1/v2**

Keep v1 branch behavior byte-for-byte compatible. Define reusable closed definitions for fingerprint/path, projected item, transition, evidence receipt entry, proof receipt, and Decision receipt. Encode action-local required/forbidden fields with closed branches rather than permissive optional fields.

Do not encode replay-only sequence/order/projection equality in schema.

- [ ] **Step 4: Write failing legal replay tests**

Cover full legal lifecycle:

```text
BEGIN
BEGIN -> BLOCK -> RESUME -> RECONCILE COMPLETE
BEGIN -> RECONCILE SKIPPED
BEGIN -> RECONCILE SUPERSEDED
COMPLETE -> REFRESH_PROOF
```

Assert:

- implicit untouched items remain absent from projection;
- active and next item match canonical Plan order;
- latest proof receipt changes only on COMPLETE reconciliation/refresh;
- historical receipts remain in transitions;
- input dictionaries remain unchanged;
- repeated replay returns equal values.

- [ ] **Step 5: Run legal replay tests and verify RED**

```bash
pytest tests/test_plan_execution.py -k 'legal or replay or refresh' -q
```

Expected: FAIL because replay interface does not exist.

- [ ] **Step 6: Implement minimal pure replay**

Replay validation order exactly:

1. v2 structural assumptions;
2. Plan fingerprint equality;
3. top-level sequence equals transition count;
4. contiguous event sequences from 1 for non-empty journal;
5. canonical item membership;
6. exact `from` state;
7. legal action/from/to combination;
8. canonical BEGIN order;
9. one active item maximum;
10. action payload/receipt consistency;
11. REFRESH_PROOF only for COMPLETE;
12. replayed projection exact equality with persisted `items`.

Return first deterministic typed issue where ordering requires one outcome. Never mutate, sort, drop, or repair journal data. Derive projection fields only from accepted events.

- [ ] **Step 7: Write failing adversarial and property replay tests**

Reject sequence gap/duplicate/reorder, wrong `from`, unknown item, non-next BEGIN, concurrent active item, terminal overwrite/re-begin, receipt/ref mismatch, illegal refresh, supersession projection mismatch, and any journal/projection mismatch.

Deterministic generated-case tests build valid journals then mutate one event. Assert mutated journal either produces changed replay digest/projection consistently or a typed issue; never unchanged silent acceptance.

- [ ] **Step 8: Implement `append_plan_transition(...)` and finish replay**

Append to copied transitions, assign next contiguous sequence, replay candidate, and persist replay-derived projection. Raise domain error if supplied transition cannot replay. Empty v2 remains legal.

- [ ] **Step 9: Run focused Task 1 tests**

```bash
pytest tests/test_schema_resources.py tests/test_plan_execution.py tests/test_task_contract.py -k 'plan_execution or plan_schema or replay or plan_reconciliation' -q
```

Expected: PASS. Existing v1 tests remain green.

- [ ] **Step 10: Request authorization, then commit Task 1 only**

```bash
git add src/harness/schemas/plan-execution.schema.json src/harness/plan_execution.py tests/test_plan_execution.py tests/test_schema_resources.py
git commit -m "feat: add replayable plan execution v2"
```

---

### Task 2: Layered assessment, early returns, and blocker recovery

**Files:**
- Modify: `src/harness/plan_reconciliation.py`
- Modify: `src/harness/blockers.py`
- Modify: `tests/test_task_contract.py`
- Modify: `tests/test_quality_gate.py`

**Interfaces:**
- Produces `PlanAssessment`
- Produces `assess_plan_reconciliation_documents(...) -> PlanAssessment`
- Preserves `validate_plan_reconciliation_documents(...) -> list[GateBlocker]`
- Extends initialization validation with effective task mode/profile

- [ ] **Step 1: Write failing precedence and recovery tests**

Add table-driven direct-document tests for exact one-blocker outcomes:

1. missing artifact → `PLAN_REQUIRED`;
2. stale fingerprint → `PLAN_STALE`;
3. Q2/final + v2 → `PLAN_DISPOSITION_INVALID` without replay;
4. Q3/task_and_final + v1 → `PLAN_TASK_LEVEL_REQUIRED`;
5. Q3/task_and_final + invalid v2 replay → `PLAN_SEQUENCE_INVALID`;
6. valid replay → existing P0 blockers in existing order.

Assert both new blockers have category `implementation`, `source is None`, `recover_to == "IMPLEMENTING"`, and `RECOVERY_POLICY` routes to `IMPLEMENTING`.

- [ ] **Step 2: Run precedence tests and verify RED**

```bash
pytest tests/test_task_contract.py tests/test_quality_gate.py -k 'task_level or sequence_invalid or mode_version or recovery_policy' -q
```

Expected: FAIL because assessment and blocker codes do not exist.

- [ ] **Step 3: Extract independent P0 final projection assessment**

Refactor existing P0 loop into one internal helper consuming an explicit current `items` projection. Preserve all existing P0 messages, source IDs, order, proof checks, and exception behavior.

Build `PlanAssessment` so:

- `blockers` follows public early-return precedence;
- `final_blockers` independently evaluates schema-valid current disposition for Context/status `final_status` where possible;
- `projection` is replay-derived only for trusted v2, v1 `items` for legal Q2, otherwise `None` for public progress;
- replay-invalid/task-level-required public assessment never appends hidden P0 blockers;
- current rejected Decision remains `PLAN_DISPOSITION_INVALID` after trusted replay;
- current stale evidence or latest receipt/content digest mismatch remains `PLAN_PROOF_MISSING`.

For v2 COMPLETE items, require current evidence raw bytes to match latest receipt before normal freshness/coverage checks. Replay checks receipt structure only.

- [ ] **Step 4: Register blockers and delegate existing validators**

Add `PLAN_TASK_LEVEL_REQUIRED` and `PLAN_SEQUENCE_INVALID` to `RECOVERY_POLICY`. Keep Gate wrapper signatures stable: wrappers load once, call assessment, and return `assessment.blockers`.

Change initialization validation to consume task configuration and require Q3 empty v2 entry shape while preserving Q2 v1 entry behavior. Effective enablement, not ad hoc raw setting, gates Plan reads.

- [ ] **Step 5: Write failing P0-on-v2 compatibility tests**

Use replay-valid v2 projections to pin:

- nonterminal item → `PLAN_ITEM_UNRECONCILED`;
- current Decision rejection → `PLAN_DISPOSITION_INVALID`;
- replacement absence/self/cycle → `PLAN_DISPOSITION_INVALID`;
- latest receipt digest mismatch/current evidence staleness → `PLAN_PROOF_MISSING`;
- protected path handling unchanged;
- task-level blocker can coexist with `final_blockers == ()` but not appear inside `final_blockers`.

- [ ] **Step 6: Complete assessment integration and run focused tests**

```bash
pytest tests/test_task_contract.py tests/test_quality_gate.py -k 'plan or recovery' -q
```

Expected: PASS, including unchanged Q2 P0 tests.

- [ ] **Step 7: Request authorization, then commit Task 2 only**

```bash
git add src/harness/plan_reconciliation.py src/harness/blockers.py tests/test_task_contract.py tests/test_quality_gate.py
git commit -m "feat: enforce Q3 plan execution assessment"
```

---

### Task 3: Locked mutation engine, receipts, idempotency, and migration

**Files:**
- Modify: `src/harness/plan_reconciliation.py`
- Modify: `tests/test_task_contract.py`
- Create: `tests/test_plan_mutation.py`

**Interfaces:**
- Produces `PlanMutationError`
- Produces `PlanMutationRequest`
- Produces `mutate_plan_execution(...) -> bool`
- Reuses `telemetry_lock`, `workspace.snapshot`, `decision.load_decision`, `evidence_path`, `project_evidence`, and `transaction.atomic_write`

- [ ] **Step 1: Write failing policy/isolation mutation tests**

Call mutation seam directly and assert:

- disabled, FAST/Q1, and Q2/final fail `PLAN_TASK_LEVEL_DISABLED` before Plan file reads;
- unsupported top-level states fail `PLAN_MUTATION_NOT_ALLOWED`;
- missing/stale/malformed/schema-invalid artifacts preserve blocker/error distinction;
- begin/block/resume/reconcile require `IMPLEMENTING`;
- refresh accepts `IMPLEMENTING` or `VERIFYING` only;
- upgrade accepts `SPECIFYING`, `PLANNED`, or `IMPLEMENTING` only;
- every refusal leaves all repository bytes unchanged.

- [ ] **Step 2: Run policy tests and verify RED**

```bash
pytest tests/test_plan_mutation.py -k 'policy or disabled or state or malformed' -q
```

Expected: FAIL because mutation seam does not exist.

- [ ] **Step 3: Implement locked load/normalize/publish skeleton**

Inside one `telemetry_lock(harness_dir)` scope:

1. validate effective task-level enablement/state before Plan reads;
2. load current Plan/execution fresh under lock;
3. require fresh Plan fingerprint and replay-valid v2, except upgrade path;
4. normalize evidence refs, surfaces, replacements, and reason;
5. detect exact latest-applicable retry before append;
6. build candidate via pure append/replay;
7. use `transaction.atomic_write` for complete YAML bytes.

Use deterministic `yaml.safe_dump(..., sort_keys=False)` for committed bytes. A no-op returns `False` without write.

- [ ] **Step 4: Write failing lifecycle mutation tests**

Cover successful and refused:

- begin canonical next item only;
- no begin while any item is active/blocked;
- block requires exact non-empty reason and active target;
- resume only blocked target and clears projected block reason;
- complete/skip/supersede only active target;
- terminal item cannot change disposition;
- refresh only COMPLETE and does not alter disposition/reason/Decision/replacements;
- supersede replacement normalization follows canonical Plan order;
- unknown replacement, self-reference, and cycle reject with zero writes.

Assert each successful write has contiguous sequence and projection exactly equals replay.

- [ ] **Step 5: Implement lifecycle authorization**

Map requests to exact actions/transitions. Keep `BLOCKED` item-local; never call state machine or top-level `harness resume`. Use replay result as sole current lifecycle source.

- [ ] **Step 6: Write failing proof and Decision receipt tests**

For COMPLETE:

- test-case branch requires fresh item-owned evidence and coverage;
- surface branch requires declared changed surfaces;
- both branches require both;
- no branch is invalid;
- protected user-path rules remain enforced;
- receipt stores normalized refs plus raw evidence byte digests and validated identity.

For SKIPPED/SUPERSEDED:

- require reason plus accepted current-task Decision;
- reject proposed/rejected/cross-task Decision;
- receipt digest uses exact Decision file bytes.

For REFRESH_PROOF:

- changed evidence bytes under same ref are not an exact retry;
- refresh appends receipt and updates projection refs;
- exact same current receipt is no-op.

- [ ] **Step 7: Implement receipt creation with workspace race check**

For proof mutations:

1. capture `before = workspace.snapshot()`;
2. validate current proof/Decision and read exact source bytes;
3. build immutable receipts;
4. capture `after = workspace.snapshot()`;
5. abort `PLAN_PROOF_MISSING` without write unless HEAD and fingerprint equal `before`;
6. append and atomically publish under same telemetry lock.

Do not require historical evidence bytes during replay. Final P0 compares current bytes only to latest receipt.

- [ ] **Step 8: Write failing exact retry, race, rollback, and concurrency tests**

Pin:

- begin/block/resume/reconcile/refresh exact retries preserve `read_bytes()` exactly;
- same command after later incompatible transition is refusal, not retry;
- changed payload is refusal with no write;
- monkeypatched second snapshot race writes nothing;
- monkeypatched atomic-write failure leaves canonical bytes intact;
- two concurrent mutations serialize and only one commits; loser returns no-op or deterministic domain refusal;
- lock used is existing telemetry lock path, with no new lock file family.

- [ ] **Step 9: Write failing v1 upgrade tests**

Assert all-pending Q3 v1 upgrades to exactly fresh v2 empty journal/projection with matching fingerprint. Empty/missing item records and explicit `PENDING` are accepted. Any `IN_PROGRESS`, `BLOCKED`, terminal, stale, Q2, or unsupported-state case refuses without writes. Retry on already-empty v2 is byte-identical no-op. No events are synthesized.

- [ ] **Step 10: Implement upgrade and run focused mutation tests**

```bash
pytest tests/test_plan_execution.py tests/test_plan_mutation.py tests/test_task_contract.py -k 'plan or mutation or upgrade or replay' -q
```

Expected: PASS.

- [ ] **Step 11: Request authorization, then commit Task 3 only**

```bash
git add src/harness/plan_reconciliation.py tests/test_task_contract.py tests/test_plan_mutation.py
git commit -m "feat: add locked plan reconciliation mutations"
```

---

### Task 4: `harness plan` mutation CLI

**Files:**
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Create: `tests/test_plan_mutation_cli.py`
- Verify: `tests/test_plan_status_cli.py`

**Interfaces:**
- Produces commands:
  - `harness plan begin P-001`
  - `harness plan block P-001 --reason ...`
  - `harness plan resume P-001`
  - `harness plan reconcile P-001 (--complete | --skipped | --superseded) ...`
  - `harness plan refresh-proof P-001 ...`
  - `harness plan upgrade-execution`
- Delegates one normalized `PlanMutationRequest` to mutation engine

- [ ] **Step 1: Write failing parser tests**

Pin required positional arguments and mutual exclusion:

- reconcile requires exactly one disposition flag;
- complete accepts repeated `--evidence` and `--surface`, rejects reason/Decision/replacement-only options;
- skipped requires `--reason` and `--decision`, rejects replacements/proof options;
- superseded requires reason, Decision, and at least one replacement;
- begin/resume/upgrade reject unrelated flags;
- block requires reason;
- refresh accepts repeated evidence/surface only.

- [ ] **Step 2: Run parser tests and verify RED**

```bash
pytest tests/test_plan_mutation_cli.py -k 'parser or arguments' -q
```

Expected: FAIL because subcommands do not exist.

- [ ] **Step 3: Add argparse surface and thin dispatch**

Build request values without reading Plan files in parser/dispatcher. Route all mutations through one control-plane handler that loads/schema-validates current task, delegates to mutation seam, and maps errors:

- commit or exact retry → exit 0;
- `PlanMutationError` → exit 1 with stable code on stderr;
- malformed/schema-invalid Harness source → exit 2 with `INVALID_HARNESS_STATE:` and empty stdout;
- repository discovery remains existing exit 1 `ERROR:` behavior.

Do not alter read-only `plan status` rendering.

- [ ] **Step 4: Write failing subprocess happy-path and refusal tests**

Exercise complete begin/block/resume/reconcile/refresh sequence from CLI. Assert persisted transitions/projection, exit contracts, stderr codes, no stdout on invalid state, and zero writes on refusal.

Add read-isolation spies/snapshots for disabled, FAST, and Q2 invocations. Add malformed source and stale fingerprint cases. Keep command success output minimal and do not render journal/receipt bodies.

- [ ] **Step 5: Finish CLI error mapping and run focused CLI tests**

```bash
pytest tests/test_plan_mutation_cli.py tests/test_plan_status_cli.py -q
```

Expected: PASS; status remains byte-for-byte read-only.

- [ ] **Step 6: Request authorization, then commit Task 4 only**

```bash
git add src/harness/cli.py src/harness/controlplane.py tests/test_plan_mutation_cli.py
git commit -m "feat: add plan reconciliation commands"
```

---

### Task 5: Workflow entry, verification boundary, review, and Gate

**Files:**
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/quality_gate.py` only if assessment delegation requires it
- Modify: `tests/test_test_plan_transition.py`
- Modify: `tests/test_quality_gate.py`
- Modify: `tests/test_plan_mutation.py`

**Interfaces:**
- Q3 entry requires fresh empty replay-valid v2
- `IMPLEMENTING -> VERIFYING` uses task-level readiness without final proof freshness
- `VERIFYING -> REVIEWING` and Gate use full extended assessment

- [ ] **Step 1: Write failing Q3 implementation-entry tests**

Pin:

- fresh empty v2 enters IMPLEMENTING;
- Q3 v1 returns `PLAN_TASK_LEVEL_REQUIRED`;
- non-empty v2 journal/projection at entry rejects;
- replay-invalid v2 rejects `PLAN_SEQUENCE_INVALID`;
- Q2 v1 entry remains accepted;
- Q2 v2 returns only `PLAN_DISPOSITION_INVALID`;
- FAST ad hoc enablement beside malformed artifacts remains unread.

- [ ] **Step 2: Run entry tests and verify RED**

```bash
pytest tests/test_test_plan_transition.py -k 'plan and (q3 or strict or v2 or fast)' -q
```

Expected: FAIL because transition entry still uses v1-only initialization rules.

- [ ] **Step 3: Integrate task-aware initialization**

Call effective plan initialization only for STANDARD/STRICT enabled tasks. Preserve all preceding Alignment/test-plan checks and existing exit formatting. Q3 entry accepts only sequence zero, empty journal, empty projection.

- [ ] **Step 4: Write failing verification-boundary tests**

For `IMPLEMENTING -> VERIFYING`, assert:

- replay-valid all-terminal journal and no active item passes even when earlier COMPLETE current proof is stale after later workspace changes;
- active/nonterminal item rejects and task remains IMPLEMENTING;
- invalid replay rejects;
- currently rejected SKIPPED/SUPERSEDED Decision rejects;
- historical receipt structural validity is enough at this boundary;
- no full P0 current-proof requirement is applied yet.

- [ ] **Step 5: Add dedicated verification-entry assessment**

Reuse replay and current Decision checks. Require every item terminal and no active item. Do not call full Gate/P0 proof freshness here. Return implementation recovery codes for journal/disposition failures.

- [ ] **Step 6: Write failing review/Gate tests**

Pin:

- trusted replay then current evidence stale → `PLAN_PROOF_MISSING`;
- latest receipt/current bytes mismatch → `PLAN_PROOF_MISSING`;
- refresh against final workspace restores readiness;
- review fix changing product workspace requires new evidence plus refresh;
- control-plane-only writes do not stale product proof;
- P0 blocker ordering remains unchanged after replay;
- Gate returns one task-level early blocker, never mixed sequence/P0 blockers;
- historical receipt remains replay-valid after later workspace change.

- [ ] **Step 7: Complete Gate/preflight integration**

Keep `quality_gate` calling reconciliation once per Gate assessment. Ensure wrapper returns public blockers only while independent final blockers remain available to Context/status consumers. Preserve malformed-source `InvalidHarnessState` behavior.

- [ ] **Step 8: Run focused workflow/Gate tests**

```bash
pytest tests/test_test_plan_transition.py tests/test_quality_gate.py tests/test_plan_mutation.py -k 'plan or transition or proof_receipt' -q
```

Expected: PASS.

- [ ] **Step 9: Request authorization, then commit Task 5 only**

```bash
git add src/harness/controlplane.py src/harness/quality_gate.py tests/test_test_plan_transition.py tests/test_quality_gate.py tests/test_plan_mutation.py
git commit -m "feat: enforce plan journal across workflow"
```

Stage `src/harness/quality_gate.py` only if changed.

---

### Task 6: Context/status trust projection and focused acceptance verification

**Files:**
- Modify: `src/harness/plan_reconciliation.py`
- Modify: `src/harness/context/model.py`
- Modify: `src/harness/context/source.py`
- Modify: `src/harness/context/builder.py`
- Modify: `tests/test_task_contract.py`
- Modify: `tests/test_plan_status_cli.py`
- Modify: `tests/test_context_builder.py`
- Modify: `tests/test_context_lifecycle_integration.py`
- Verify: `tests/test_context_integrity.py`, `tests/test_context_dependency_closure.py`, `tests/test_context_protected_freshness.py`

**Interfaces:**
- Status consumes one `PlanAssessment`
- Authoritative Context retains independent Plan assessment facts without projecting bodies
- Existing public Context/status shapes remain unchanged

- [ ] **Step 1: Write failing status tests for task-level trust**

Assert:

- trusted v2 progress comes from replayed projection;
- Q3/v1 has only `PLAN_TASK_LEVEL_REQUIRED`, with `progress` and `next_plan_item` null;
- replay-invalid v2 has only `PLAN_SEQUENCE_INVALID`, with `progress` and `next_plan_item` null;
- `final_status` uses `assessment.final_blockers` only;
- terminal schema-valid projection plus task-level blocker may report `final_status: pass`;
- missing/stale remain P0 failures with blocked final status;
- Q2 output remains unchanged;
- serialized output omits transition/action/sequence/receipt/reason/Decision/reference bodies.

- [ ] **Step 2: Run status tests and verify RED**

```bash
pytest tests/test_task_contract.py tests/test_plan_status_cli.py -k 'task_level or sequence_invalid or final_status or v2' -q
```

Expected: FAIL because report still trusts fingerprints/items alone and uses public blockers for final status.

- [ ] **Step 3: Make status consume layered assessment**

Change orchestration/report seam so already-loaded documents and one assessment drive public blockers, replayed progress, next item, and independent P0 final status. Preserve exact JSON/text keys and order. Do not render execution internals.

- [ ] **Step 4: Write failing Context tests**

Pin same trusted/untrusted next-item and independent final-status behavior in compact/full Context. Assert:

- v2 remains one authoritative `plan-execution.yaml` source/hash/reference;
- no journal/receipt projection enters Control Core or Working Set;
- omission/integrity behavior remains unchanged;
- FAST/Q1 malformed adjacent artifacts remain unread;
- Context source failures remain `CONTEXT_SCHEMA_INVALID` where existing P1A contract requires it.

- [ ] **Step 5: Carry PlanAssessment through authoritative source**

Add internal `plan_assessment` field to `AuthoritativeContext` or equivalent typed loaded fact. Compute it from already-loaded Plan documents and current workspace. Pass it to `plan_context_summary`; do not derive final status by filtering public Gate blockers. Preserve source reference and manifest behavior.

- [ ] **Step 6: Run focused Context/status regressions**

```bash
pytest \
  tests/test_task_contract.py \
  tests/test_plan_status_cli.py \
  tests/test_context_builder.py \
  tests/test_context_lifecycle_integration.py \
  tests/test_context_integrity.py \
  tests/test_context_dependency_closure.py \
  tests/test_context_protected_freshness.py \
  -k 'plan or context' -q
```

Expected: PASS.

- [ ] **Step 7: Run complete section 15 focused acceptance set**

Run only impact-related files:

```bash
pytest \
  tests/test_schema_resources.py \
  tests/test_plan_execution.py \
  tests/test_plan_mutation.py \
  tests/test_plan_mutation_cli.py \
  tests/test_task_contract.py \
  tests/test_plan_status_cli.py \
  tests/test_test_plan_transition.py \
  tests/test_quality_gate.py \
  tests/test_context_builder.py \
  tests/test_context_lifecycle_integration.py \
  tests/test_context_integrity.py \
  tests/test_context_dependency_closure.py \
  tests/test_context_protected_freshness.py \
  -q
```

Do not run `pytest` without explicit files. Record exact counts/output in progress artifact.

- [ ] **Step 8: Run package verification**

Build wheel and run only package/import/CLI smoke checks needed to prove schema resource inclusion and new commands:

```bash
python -m build --wheel
```

Install wheel into isolated temp environment, then run `harness plan --help`, `harness plan status --help`, and one mutation parser smoke check. Do not run full suite.

- [ ] **Step 9: Request authorization, then commit Task 6 only**

```bash
git add \
  src/harness/plan_reconciliation.py \
  src/harness/context/model.py \
  src/harness/context/source.py \
  src/harness/context/builder.py \
  tests/test_task_contract.py \
  tests/test_plan_status_cli.py \
  tests/test_context_builder.py \
  tests/test_context_lifecycle_integration.py
git commit -m "feat: project trusted plan journal status"
```

Stage only files actually changed.

---

### Task 7: Harness verification, reviews, Gate, and closeout

**Files:**
- Modify through Harness workflow only: `.harness/**`
- Modify: `.superpowers/sdd/2026-09-28-v0210-plan-task-reconciliation-p1c/progress.md`
- Optional only if required by release policy: `CHANGELOG.md`, `README.md`, `pyproject.toml`

- [ ] **Step 1: Reconcile canonical Plan Items through supported P1C commands**

Once commands exist, use `harness plan begin/reconcile` for remaining implementation items. Do not hand-edit execution v2 journal. Attach item-owned focused evidence and declared surfaces per Plan.

For implementation work completed before commands existed, do not synthesize history. Use approved bootstrap/migration rule from Task 0 and document limitation; if canonical task cannot honestly establish P1C history, start a fresh Harness verification task rather than fabricate events.

- [ ] **Step 2: Collect fresh focused evidence**

Use `collect-evidence` skill for exact focused test commands and package build. Collect final-workspace evidence, then run `harness plan refresh-proof` for every COMPLETE item whose latest receipt does not match final evidence/workspace.

- [ ] **Step 3: Run complexity and diagnosability reviews**

Use Harness review skills. Scope complexity review to verified diff. Review diagnosability only if task classification requires it. Persist structured outputs through supported commands.

- [ ] **Step 4: Request code review**

Review against approved design, implementation contract, and this plan. Explicit review focus:

- FAST/Q1 read isolation;
- Q2 v1 compatibility;
- replay purity and projection equality;
- assessment precedence;
- current versus historical proof separation;
- retry byte identity;
- lock/race/atomic guarantees;
- no fabricated migration history;
- Context/status body isolation.

Address only confirmed findings through safe-fix/TDD workflow, with fresh focused evidence after each fix.

- [ ] **Step 5: Enter review/Gate legally**

Ensure all Plan Items terminal, refresh final proof, transition through VERIFYING and REVIEWING, persist review outcome, then run Gate. Use `quality-gate` and `convergence` skills. Follow printed `DECISION:`; do not infer pass manually.

- [ ] **Step 6: Request authorization for any final docs/release commit**

Do not bump package version or rewrite release README/CHANGELOG unless user explicitly expands scope. If docs are required, stage only named files and request commit authorization.

- [ ] **Step 7: Finish branch choice**

Use finishing-development-branch workflow after Gate convergence. User already selected direct `main`; do not create worktree or push without explicit request.

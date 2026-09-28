# v0.2.10 Plan Reconciliation P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make enabled Q2/Q3 tasks fail closed when canonical implementation-plan items lack valid final reconciliation.

**Architecture:** Add one `plan_reconciliation` validator module owning artifact schemas, normalized plan digest, execution disposition, and Gate issues. Extend task state/classification/escalation only for persisted enablement; reuse existing transition, quality-Gate, blocker, evidence, workspace, and schema seams. Keep Context/status/Q3 temporal enforcement out of P0.

**Tech Stack:** Python 3.11, PyYAML, jsonschema, pytest.

**Spec:** `docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md`

**Completion:** Implemented and gated in TASK-058; contract mismatches closed in TASK-059. Focused Harness evidence passed and both tasks reached `DONE`.

## Global Constraints

- `Requirement`, Alignment, Test Plan, Evidence, and existing drift rules remain authoritative.
- Disabled/FAST tasks do not read plan artifacts.
- No Markdown parsing, new evidence type, EV namespace, Context projection, status CLI, or top-level state.
- Fingerprint is canonical UTF-8 JSON SHA-256, keys sorted, list order retained, omitted refs normalized to `[]`.
- Full suite forbidden; run focused related tests only.

## Review Focus

- Disabled task beside malformed plan files must pass without reading them.
- `PLAN_STALE` must short-circuit item proof/disposition blockers.
- Fresh item evidence must be item-owned; no global proof leakage.
- Protected initial-user paths must never become surface proof after aggregate fingerprint changes.
- `PLAN_*` recovery targets and blocker `source` must remain deterministic.

---

### Task 1: Canonical artifact schemas and validator

**Files:**
- Create: `src/harness/schemas/plan.schema.json`
- Create: `src/harness/schemas/plan-execution.schema.json`
- Create: `src/harness/plan_reconciliation.py`
- Modify: `src/harness/schema_resources.py`
- Modify: `tests/test_task_contract.py`

**Interfaces:**
- Produces: `validate_plan_reconciliation(harness_dir, task, *, head, workspace) -> list[GateBlocker]` and `validate_plan_initialization(harness_dir) -> list[PlanIssue]`.
- Consumes: canonical `.harness/plan.yaml`, `.harness/plan-execution.yaml`, existing evidence/test-plan/workspace helpers.

- [x] Write schema/fingerprint/item-state tests first; run them red.
- [x] Add schemas, package registry entries, normalized semantic digest, safe loaders, qualified test-case resolver, disposition/cycle validation, surface/evidence proof checks.
- [x] Run focused schema tests green.

### Task 2: Persist enablement and guard implementation entry

**Files:**
- Modify: `src/harness/schemas/task.schema.json`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/cli.py`
- Modify: `tests/test_test_plan_transition.py`
- Modify: `tests/test_risk.py`

**Interfaces:**
- Consumes: `plan_reconciliation.enabled/mode` task state and `validate_plan_initialization`.
- Produces: Q2 `{enabled: true, mode: final}`, Q3 `{enabled: true, mode: task_and_final}`, Q1 disabled; `PLANNED → IMPLEMENTING` blocks enabled missing/stale artifacts.

- [x] Write entry/migration/escalation tests red, including malformed plan artifact ignored while disabled.
- [x] Add task schema and classification/escalation persistence; invoke initialization validation only for enabled STANDARD/STRICT entry.
- [x] Run focused transition/risk tests green.

### Task 3: Gate blockers and recovery integration

**Files:**
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/blockers.py`
- Modify: `tests/test_quality_gate.py`
- Modify: `tests/test_blocker_recovery.py`

**Interfaces:**
- Consumes: validator issues from Task 1.
- Produces: `PLAN_REQUIRED`, `PLAN_STALE`, `PLAN_ITEM_UNRECONCILED`, `PLAN_PROOF_MISSING`, `PLAN_PROTECTED_PATHS_MODIFIED`, `PLAN_DISPOSITION_INVALID` with specified categories/recovery/source.

- [x] Write final Gate/preflight and one-blocker recovery tests red.
- [x] Run validator after FAST early return; emit stale only before item checks; register recovery policy.
- [x] Run focused Gate/recovery tests green.

### Task 4: Focused integration proof

**Files:**
- Modify: affected P0 test files only.

- [x] Run all affected focused test files through `harness evidence run --scope related` with canonical covered tests/cases.
- [x] Bind REQ-058..060 and INV-058..059 evidence; run complexity review, review outcome, and Gate.

# Harness Task Bootstrap Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Q2/Q3 task bootstrap reach IMPLEMENTING through supported Harness boundaries without inherited plan history or manual control-plane edits.

**Architecture:** Preserve `task new`/`recover` replacement cleanup, extending its archive set with plan artifacts. Defer profile-specific empty plan/execution creation to classification. Add audited alignment revision with schema support and exclude audit metadata from contract hash. Enforce contract completeness at `SPECIFYING -> PLANNED` before implementation.

**Tech Stack:** Python 3.11, pytest, YAML, JSON Schema.

**Spec:** `docs/superpowers/specs/2026-10-10-harness-task-bootstrap-repair-design.md`

## Global Constraints

- Q1 writes no plan artifacts; Q2 initializes empty v1 final execution; Q3 initializes empty v2 task-and-final execution.
- `task new` and `task recover` retain existing cleanup/reset behavior and archive old plan artifacts under `.harness/history/<task-id>-<timestamp>/`.
- `align revise` requires a frozen nonterminal task and non-empty reason; revision metadata must not change alignment contract hash.
- `align freeze` validates draft completeness and creates seal; `align check` validates frozen seal.
- Existing `ALIGNMENT_ALREADY_FROZEN`, `REQ_WITHOUT_AC`, and `CRITICAL_REQ_WITHOUT_SURFACE` behavior remains stable.
- New binding diagnostics use `<subject>: TEST_BINDING_REQUIRED`; manual cases remain exempt.
- Selector existence stays at existing `PLANNED -> IMPLEMENTING` target check.

## Review Focus

- v1/v2 plan initialization fingerprint must equal `plan_fingerprint` exactly.
- Failure in any archive/reset/write path must publish no partial replacement workspace.
- Revision audit append must not permit frozen contract overwrite without `align revise`.
- New binding admission must not reject manual cases or test selectors for files not yet implemented.
- Q1 classification must not leave stale plan artifacts behind.
- v2 protected snapshot must not read undeclared protected path content during compact Context construction.

---

### Task 1: Alignment revision command and schema

**Files:**
- Modify: `src/harness/schemas/alignment.schema.json`
- Modify: `src/harness/alignment.py`
- Modify: `src/harness/controlplane.py:584-680`
- Modify: `src/harness/cli.py` alignment parser/dispatch
- Test: `tests/test_alignment.py`
- Test: `tests/test_control_plane.py`

**Interfaces:**
- Produces: `harness align revise --reason <reason>`.
- Produces: optional `alignment.revisions[]` entries `{reason, timestamp, previous_contract_hash}`.
- Consumes: existing alignment freeze/seal persistence.

- [ ] **Step 1: Write failing revise CLI tests**

Cover frozen valid alignment: revise succeeds, records audit entry, clears freeze fields, removes seal, leaves task state unchanged. Cover empty reason, terminal task, and unfrozen alignment refusals with no writes.

- [ ] **Step 2: Run revise tests to verify RED**

Run: `PYTHONPATH=src pytest tests/test_alignment.py tests/test_control_plane.py -q`

Expected: FAIL because no `revise` parser/command exists.

- [ ] **Step 3: Add optional revision schema and hash exclusion**

Add optional `revisions` item schema. Make `alignment.contract_hash` omit revision audit metadata while preserving all contract-body hash inputs. Add unit test proving append-only revision audit leaves computed contract hash unchanged.

- [ ] **Step 4: Implement atomic `align revise`**

Add parser/dispatch and control-plane command. Validate task/state/reason/frozen preconditions. Stage updated alignment plus seal deletion as one publish operation; audit prior hash and UTC timestamp. Preserve existing freeze refusal semantics.

- [ ] **Step 5: Run Task 1 tests to verify GREEN**

Run: `PYTHONPATH=src pytest tests/test_alignment.py tests/test_control_plane.py -q`

Expected: PASS.

### Task 2: Task replacement archive and profile-specific plan initialization

**Files:**
- Modify: `src/harness/controlplane.py:2299-2370, 2512-2700`
- Modify: `src/harness/plan_reconciliation.py` only if reusable empty-artifact initializer belongs there
- Test: `tests/test_cli_task_recovery.py`
- Test: `tests/test_test_plan_transition.py`
- Test: `tests/test_risk.py`
- Test: `tests/test_context_builder.py`

**Interfaces:**
- Produces: archived `plan.yaml` and `plan-execution.yaml` for `task new` and `task recover`.
- Produces: classification-created empty plan artifacts for Q2/Q3 only.

- [ ] **Step 1: Write failing replacement archive tests**

Create old plan/execution containing items and receipts. Assert `task new` and active-task `task recover` archive both files under existing history timestamp directory and publish replacement with neither file present.

- [ ] **Step 2: Run replacement tests to verify RED**

Run: `PYTHONPATH=src pytest tests/test_cli_task_recovery.py -q`

Expected: FAIL because old plan artifacts survive replacement and are absent from archive.

- [ ] **Step 3: Implement plan artifact archive/removal**

Extend existing replacement archive list and cleanup list with `plan.yaml` and `plan-execution.yaml`; retain all existing template reset, alignment deletion, evidence/finding clearing, atomic replacement, and architecture preservation behavior.

- [ ] **Step 4: Write failing classification initialization tests**

Cover clean Q1/Q2/Q3 classifications: Q1 has no plan files; Q2 gets empty plan + v1 `final` execution; Q3 gets empty plan + v2 task-level execution. Assert stored fingerprint equals `plan_fingerprint(plan)`.

- [ ] **Step 5: Run classification tests to verify RED**

Run: `PYTHONPATH=src pytest tests/test_test_plan_transition.py tests/test_risk.py -q`

Expected: FAIL because classify currently writes no profile-specific plan artifacts.

- [ ] **Step 6: Write failing Context-safe v2 snapshot test**

Classify Q3 with an untracked protected path, then run `harness context --compact`. Assert success and no `CONTEXT_REFERENCE_BROKEN`.

- [ ] **Step 7: Run Context test to verify RED**

Run: `PYTHONPATH=src pytest tests/test_context_builder.py -q`

Expected: FAIL because v2 fingerprint calculation calls `source_access.is_file` for an undeclared protected path.

- [ ] **Step 8: Implement profile-specific initializer and Context-safe snapshot**

After profile determination and before task publish, create Q2/Q3 empty plan plus correct execution version/fingerprint. Remove plan artifacts for Q1. Reuse canonical fingerprint function; do not use `upgrade-execution`. Make v2 snapshot calculation use Context-safe Git facts or explicitly declared source paths; preserve fingerprint semantics.

- [ ] **Step 9: Run Task 2 tests to verify GREEN**

Run: `PYTHONPATH=src pytest tests/test_cli_task_recovery.py tests/test_test_plan_transition.py tests/test_risk.py tests/test_context_builder.py -q`

Expected: PASS.

### Task 3: SPECIFYING contract admission and complete alignment writing

**Files:**
- Modify: `src/harness/controlplane.py:936-1190` transition admission
- Modify: `src/harness/alignment.py:251-330`
- Modify: `skills/task-contract/SKILL.md`
- Test: `tests/test_test_plan_transition.py`
- Test: `tests/test_alignment.py`
- Test: `tests/test_task_contract.py`

**Interfaces:**
- Produces: `SPECIFYING -> PLANNED` contract admission diagnostics.
- Produces: Task Contract skill complete unfrozen `alignment.yaml` body.

- [ ] **Step 1: Write failing transition admission tests**

Create `SPECIFYING` task with complete schema-valid documents. Assert missing AC prints `REQ-001: REQ_WITHOUT_AC`; missing must surface prints `REQ-001: CRITICAL_REQ_WITHOUT_SURFACE`; empty automated REQ/INV selector prints `<subject>: TEST_BINDING_REQUIRED`; each failure leaves task bytes unchanged. Assert manual cases and nonempty not-yet-existing selectors pass this admission.

- [ ] **Step 2: Run admission tests to verify RED**

Run: `PYTHONPATH=src pytest tests/test_test_plan_transition.py tests/test_alignment.py -q`

Expected: FAIL because transition currently lacks SPECIFYING admission/binding checks.

- [ ] **Step 3: Implement shared admission validator**

Reuse alignment completeness checks for requirement AC/surface issues. Add deterministic REQ/INV test-case traversal that checks only nonempty automated `tests`; format diagnostics subject-first. Invoke only on legal `SPECIFYING -> PLANNED`, before state write.

- [ ] **Step 4: Update Task Contract skill contract output**

Require complete valid unfrozen alignment document with current task identity, all required envelope fields, AC/surfaces/verification, and empty optional references/lists as needed. State explicitly that `align init` cannot update existing alignment.

- [ ] **Step 5: Run Task 3 tests to verify GREEN**

Run: `PYTHONPATH=src pytest tests/test_test_plan_transition.py tests/test_alignment.py tests/test_task_contract.py -q`

Expected: PASS.

### Task 4: Bootstrap lifecycle integration verification

**Files:**
- Test: `tests/test_cli_task_recovery.py`
- Test: `tests/test_test_plan_transition.py`
- Test: `tests/test_control_plane.py`

- [ ] **Step 1: Write failing end-to-end Q2/Q3 lifecycle tests**

For each profile: new/recover replacement, classify, transition SPECIFYING, persist complete skill-shaped contract, align check/freeze, transition PLANNED, minimal decision, transition IMPLEMENTING. Assert no direct `.harness` state edit after fixture setup and no inherited plan receipt/item.

- [ ] **Step 2: Run lifecycle tests to verify RED**

Run: `PYTHONPATH=src pytest tests/test_cli_task_recovery.py tests/test_test_plan_transition.py tests/test_control_plane.py -q`

Expected: FAIL until Tasks 1–3 behavior is complete.

- [ ] **Step 3: Implement only integration gaps revealed by test**

Use existing CLI/service seams; do not add a parallel lifecycle API. Preserve atomic failure semantics.

- [ ] **Step 4: Run focused bootstrap regression suite**

Run: `PYTHONPATH=src pytest tests/test_alignment.py tests/test_cli_task_recovery.py tests/test_test_plan_transition.py tests/test_task_contract.py tests/test_control_plane.py tests/test_risk.py -q`

Expected: PASS.

- [ ] **Step 5: Inspect final diff**

Run: `git diff --check && git diff -- src/harness tests skills docs/superpowers/specs docs/superpowers/plans`

Expected: no whitespace errors; only scoped lifecycle, schema, test, skill, spec, and plan changes.

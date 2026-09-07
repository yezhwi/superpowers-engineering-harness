# Decision and Interface Correctness Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close TASK-009 ownership, supersession, reference-integrity, and identifier-containment fail-open paths.

**Architecture:** Reuse `paths.py` canonical-containment pattern for exact persisted identifiers. Keep ownership resolution in Decision/Interface domain loaders and make Gate consume only current-Task objects or explicit reuse references. Make replacement acceptance staged publication of both records; proposal creation is non-mutating.

**Tech Stack:** Python 3.11, PyYAML, jsonschema, pytest.

**Spec:** `.harness/requirements.yaml`, `.harness/invariants.yaml`, `.harness/decisions/DEC-019.yaml`

## Global Constraints

- Preserve historical artifacts; never delete accepted Decisions during Task replacement.
- Fail closed with stable blocker/error codes for unresolved, invalid, or unauthorized references.
- No new dependency or broad persisted-object redesign.
- Test each behavioral slice RED before production change.

---

### Task 1: Canonical Decision and Interface identifiers

**Files:**
- Modify: `src/harness/paths.py`, `src/harness/decision.py`, `src/harness/interface_contract.py`
- Test: `tests/test_decision.py`, `tests/test_interface_contract.py`

**Interfaces:**
- Produces exact ID-to-artifact path helpers which reject non-`DEC-[0-9]+` / non-`INT-[0-9]+` input before I/O and require resolved parent directory equality.

- [ ] Write traversal and noncanonical-ID failing tests.
- [ ] Run focused tests; expect current `startswith` implementation to permit malformed values.
- [ ] Add minimal exact-pattern plus canonical-containment helper and route both domain `_path` functions through it.
- [ ] Run focused tests; expect PASS.

### Task 2: Task ownership and explicit reuse

**Files:**
- Modify: `src/harness/controlplane.py`, `src/harness/decision.py`, `src/harness/interface_contract.py`, `src/harness/quality_gate.py`, relevant schemas
- Test: `tests/test_task_new.py`, `tests/test_decision_gate.py`, `tests/test_interface_gate.py`

**Interfaces:**
- Produces current-task filters and explicit `decision_refs` / contract-reuse policy; historical accepted artifacts remain readable but non-applicable by default.

- [ ] Write failing Gate tests for old proposed Decision, implicit old Interface Contract, explicit valid reuse, and current proposed Decision.
- [ ] Run focused tests; expect old objects to affect new Task or be silently selected.
- [ ] Archive ownership-relevant artifacts on replacement without deleting canonical history; add explicit reuse fields and Gate task-match checks.
- [ ] Run focused tests; expect PASS.

### Task 3: Decision supersession acceptance

**Files:**
- Modify: `src/harness/decision.py`, `src/harness/controlplane.py`
- Test: `tests/test_decision.py`, `tests/test_cli_decision.py`

**Interfaces:**
- `supersede()` creates only PROPOSED replacement. `accept()` stages replacement ACCEPTED and original SUPERSEDED with reciprocal references.

- [ ] Write failing tests for proposal/rejection preservation, accepted replacement links, publish failure rollback, exclusive active topic.
- [ ] Run focused tests; expect proposal to supersede original prematurely.
- [ ] Move original mutation into replacement acceptance and publish both records atomically.
- [ ] Run focused tests; expect PASS.

### Task 4: Decision reference resolution and breaking approval

**Files:**
- Modify: `src/harness/interface_contract.py`, `src/harness/quality_gate.py`, `src/harness/schemas/interface-contract.schema.json`
- Test: `tests/test_interface_gate.py`

**Interfaces:**
- Gate emits deterministic `DECISION_REFERENCE_*` blockers for malformed, missing, invalid, non-accepted, or unauthorized references. Breaking approval uses accepted Decision reference.

- [ ] Write failing missing/schema/status/cross-task/breaking-approval tests.
- [ ] Run focused tests; expect format-only validation or free-text approval acceptance.
- [ ] Add one resolver path used by Interface validation and Gate; require accepted approval Decision for breaking contract.
- [ ] Run focused tests; expect PASS.

### Task 5: Integration verification

**Files:**
- Modify: `.harness/impact.yaml`, `.harness/requirements.yaml`, `.harness/invariants.yaml`
- Test: changed test modules

- [ ] Run focused changed-module tests and `python -m compileall -q src` through Harness evidence commands.
- [ ] Record impact files, dependents, risks, and related tests before transition to VERIFYING.
- [ ] Run Q3 complexity and diagnosability review, review outcome, then Gate.

# Finding Evidence Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Preserve finding RED/GREEN/FULL evidence in deterministic separate files.

**Architecture:** Centralize filename selection in collector; pass explicit phase from CLI; retain existing finding refs and gate validation.

**Spec:** `docs/superpowers/specs/2026-08-26-finding-evidence-identity-design.md`

## Task 1: Filename API and collector CLI

**Files:** `src/harness/collect_evidence.py`, `src/harness/cli.py`, `src/harness/controlplane.py`, `tests/test_evidence.py`

- [ ] Write RED tests for `evidence_filename("unit_test")`, red/green/full finding names, and invalid finding/phase CLI combinations.
- [ ] Run `python -m pytest tests/test_evidence.py -q`; verify RED.
- [ ] Implement `evidence_filename`; add phase parser/validation; pass phase through control plane; write via centralized filename API.
- [ ] Run focused tests GREEN.
- [ ] Commit `feat: preserve finding evidence by phase`.

## Task 2: Real CLI lifecycle proof

**Files:** `tests/test_finding_transition.py`, `tests/test_finding_lifecycle.py`

- [ ] Write RED integration test: collect FND RED through CLI, transition CONFIRMED, collect GREEN through CLI, assert both phase files and distinct evidence refs remain.
- [ ] Run test RED.
- [ ] Update test fixture/helper only as needed to use phase-specific references; do not alter lifecycle policy.
- [ ] Run finding tests GREEN.
- [ ] Commit `test: cover separate finding red and green evidence`.

## Task 3: Compatibility and full verification

**Files:** `tests/test_wheel_isolation.py`, `scripts/collect_evidence.py`

- [ ] Assert installed `harness evidence --help` exposes `--phase`; verify root wrapper accepts it.
- [ ] Run focused wheel/wrapper tests.
- [ ] Run `python -m pytest tests/ -q`.
- [ ] Commit `test: verify finding evidence phase compatibility`.

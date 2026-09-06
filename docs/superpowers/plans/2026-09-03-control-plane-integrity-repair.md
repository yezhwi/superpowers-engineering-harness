# Control-plane Integrity Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task.

**Goal:** Repair confirmed task-classification and artifact-publication integrity defects.

**Architecture:** Reuse `save_task` for task YAML, `transaction.publish` for multi-artifact decisions, and narrow atomic replacement for standalone JSON/YAML artifacts. No policy/style refactor.

**Spec:** `TASK-043` requirements and `DEC-001`.

## Tasks

### Task 1: Classification bypass

- [ ] Write RED test: `CREATED → SPECIFYING` returns classification-required error.
- [ ] Run `pytest tests/test_control_plane.py -q`; confirm RED.
- [ ] Reject every `CREATED` target except `CLASSIFIED` in `cmd_transition`.
- [ ] Run target tests GREEN.

### Task 2: Atomic artifact publication

- [ ] Write RED tests for evidence attach, Gate write-back, and impact writes using injected write failure / replacement seam.
- [ ] Run `pytest tests/test_control_plane.py tests/test_quality_gate.py tests/test_impact_control_plane.py -q`; confirm RED.
- [ ] Reuse atomic temp-replace helper for one-file artifacts; route Gate write-back through atomic task persistence.
- [ ] Run target tests GREEN.

### Task 3: Atomic Decision supersession and Finding load

- [ ] Write RED test: injected Decision transaction publication failure leaves accepted original unchanged and no replacement.
- [ ] Write RED test: malformed Finding during resume guard returns controlled Harness error.
- [ ] Run `pytest tests/test_decision.py tests/test_finding_lifecycle.py tests/test_finding_transition.py -q`; confirm RED.
- [ ] Publish original/replacement Decision pair with `transaction.stage/publish`; load Findings once via `_findings` and map parse errors.
- [ ] Run target tests GREEN.

### Task 4: Regression and Harness verification

- [ ] Record changed paths/tests through `harness impact add-*`.
- [ ] Run all Task 1–3 focused tests and wheel build.
- [ ] Collect fresh related evidence; verify REQ-001..004 and INV-001..003.
- [ ] Persist complexity/diagnosability review, Gate, then transition only after `DECISION: CONVERGED`.

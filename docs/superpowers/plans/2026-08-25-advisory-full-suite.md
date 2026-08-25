# Advisory Full-Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make full-suite advisory; require per-finding approval for critical related closure.

**Architecture:** Simplify impact transition enforcement, extend finding transition metadata, and invert shared closure validator policy. Gate continues to use shared validator.

**Tech Stack:** Python 3.11, argparse, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-advisory-full-suite-design.md`

## Constraints

- No new dependency.
- Full-suite execution still needs authorization.
- Related evidence requires nonempty complete impact coverage.
- Critical related closure requires persisted user approval.

### Task 1: Make impact full-suite advisory

**Files:** `src/harness/controlplane.py`, `tests/test_control_plane.py`, `SKILL.md`

- [ ] Add failing test: impact `full_suite.recommended: true` does not reject `IMPLEMENTING -> VERIFYING`.
- [ ] Run `python -m pytest tests/test_control_plane.py -q`; verify RED.
- [ ] Remove only transition-time `FULL_SUITE_AUTHORIZATION_REQUIRED` rejection; retain CLI `--scope full_suite` authorization guard.
- [ ] Document advisory scheduling: focused tests first, optional full suite before review.
- [ ] Run focused tests GREEN.
- [ ] Commit `feat: make full-suite impact advisory`.

### Task 2: Critical related-closure approval

**Files:** `src/harness/cli.py`, `src/harness/controlplane.py`, `src/harness/evidence_validator.py`, `src/harness/quality_gate.py`, `tests/test_finding_transition.py`, `tests/test_evidence_validator.py`, `tests/test_finding_lifecycle.py`

- [ ] Add RED tests: critical related proof rejects without approval; accepts `--critical-related-approved`; empty impact tests rejects; Gate rejects manual missing approval.
- [ ] Run finding/validator tests RED.
- [ ] Add `--critical-related-approved` to finding transition parser. On critical related VERIFIED, persist `closure.mode`, approval boolean, UTC timestamp, and `source: user`.
- [ ] Change shared validator: do not reject impact full-suite recommendation; require nonempty coverage for related scope; require valid persisted critical approval for critical related scope.
- [ ] Keep full-suite scope valid for critical without approval. Gate calls same validator.
- [ ] Run `python -m pytest tests/test_finding_transition.py tests/test_finding_lifecycle.py tests/test_evidence_validator.py tests/test_quality_gate.py -q`; verify GREEN.
- [ ] Commit `feat: permit approved critical related closure`.

### Task 3: Docs and regression verification

**Files:** `skills/reproduce-finding/SKILL.md`, `SKILL.md`, `tests/test_readme_docs.py`, `tests/test_wheel_isolation.py`

- [ ] Add RED docs assertions for advisory full suite and per-finding critical approval.
- [ ] Update workflow and lifecycle policy text; add installed CLI help assertion for approval flag.
- [ ] Run docs/wheel tests GREEN.
- [ ] Run `python -m pytest tests/ -q`.
- [ ] Commit `docs: describe advisory full-suite policy`.

# v0.2.7 Remaining Report Repairs Implementation Plan

**Goal:** Close remaining report findings without widening behavior.

**Spec:** `.harness/requirements.yaml`; DEC-017.

### Task 1: Typed review and evidence input failures
- Test first: add `tests/test_review_outcome.py` assertion for open-Finding PASS error; add `tests/test_evidence.py` assertions rejecting `--covered-test` for build/lint/custom.
- Run focused tests RED.
- Implement typed open-Finding preflight error in `controlplane.py`; reject non-test covered test metadata in `collect_evidence.py`.
- Run focused tests GREEN.

### Task 2: Single Gate entrypoint
- Test first: direct `quality_gate.main` returns typed deprecation error and does not persist task state.
- Run RED.
- Replace standalone evaluation/write path in `quality_gate.py` with typed deprecation exit.
- Run Gate tests GREEN.

### Task 3: Skill contract audit
- Update `SKILL.md`, `skills/convergence/SKILL.md`, `skills/quality-gate/SKILL.md` to current `evidence run/attach`, `gate preflight`, `finding resume-review`, and `impact scope` commands.
- Verify with `rg`; no deprecated `harness evidence --type` dispatch remains.

### Task 4: Verification
- Run changed focused tests and `python -m compileall -q src`.
- Record related impact and Harness evidence; complexity review; Gate.

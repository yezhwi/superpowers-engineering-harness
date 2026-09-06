# Remove Generic Finding Schema Implementation Plan

**Goal:** Remove obsolete aggregate Finding schema.

**Spec:** `.harness/requirements.yaml`, DEC-018.

### Task 1: Test and remove artifact
- Add failing test asserting `finding.schema.json` is absent and category-specific schemas validate Findings.
- Run RED.
- Delete `src/harness/schemas/finding.schema.json`.
- Update `tests/test_finding_schema.py` docs/reference.
- Run GREEN.

### Task 2: Update user-facing schema reference
- Replace adversarial-review Skill references with `adversarial-finding.schema.json`.
- Run `rg` to prove no live generic schema dispatch reference remains.

### Task 3: Package verification
- Run focused finding tests and package/wheel test.
- Run build, evidence, complexity review, Gate.

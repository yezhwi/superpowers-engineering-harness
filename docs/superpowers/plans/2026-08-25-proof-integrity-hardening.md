# Proof Integrity Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make DONE require current Gate PASS, make all evidence freshness checks shared and fail-closed, and bind finding RED/GREEN proofs to one regression test identity.

**Architecture:** A small `evidence_validator` module validates schema, HEAD, workspace fingerprints, exit result, and optional structured regression identity. Existing CLI commands gain optional evidence metadata only; existing state machine and finding lifecycle remain intact.

**Tech Stack:** Python 3.11+, PyYAML, jsonschema, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-proof-integrity-hardening-design.md`

## Global Constraints

- Scope CR-001, CR-002, CR-003 only; do not start CR-004.
- No new state, workflow, review type, reporting feature, UI, or standalone CLI command.
- Existing non-regression evidence remains schema-valid.
- All freshness decisions use `scripts/evidence_validator.py`.
- Full-suite authorization remains explicit human decision.

---

### Task 1: Shared evidence validator

**Files:**
- Create: `scripts/evidence_validator.py`
- Modify: `schemas/evidence.schema.json`
- Create: `tests/test_evidence_validator.py`

**Interfaces:**
- Produces `validate_evidence(record, *, current_head, current_workspace, expected_success=None, finding_id=None, test_id=None) -> None`.
- Raises `EvidenceValidationError` whose message begins deterministic code: `EVIDENCE_HEAD_MISMATCH`, `EVIDENCE_WORKSPACE_STALE`, `EVIDENCE_RESULT_MISMATCH`, `FINDING_SUBJECT_MISMATCH`, `REGRESSION_TEST_MISMATCH`.

- [ ] **Step 1: Write RED tests for valid, stale, and identity evidence**

```python
def test_rejects_workspace_stale_evidence():
    with pytest.raises(EvidenceValidationError, match="EVIDENCE_WORKSPACE_STALE"):
        validate_evidence(record("sha256:old"), current_head=HEAD, current_workspace="sha256:new")


def test_rejects_wrong_finding_subject():
    with pytest.raises(EvidenceValidationError, match="FINDING_SUBJECT_MISMATCH"):
        validate_evidence(regression_record("FND-002", TEST), current_head=HEAD, current_workspace=FP, finding_id="FND-001", test_id=TEST)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_evidence_validator.py -q`

Expected: FAIL because validator does not exist.

- [ ] **Step 3: Implement schema and validator**

Add optional all-or-none fields:

```json
"subject": {"kind": "finding", "id": "FND-001"},
"test": {"node_id": "tests/test_x.py::test_x"}
```

Validator first invokes `jsonschema.validate`, then checks exact head, before/after fingerprints, expected success, and optional identity. Do not read filesystem or mutate state.

- [ ] **Step 4: Add counterexamples**

Test missing fingerprint, before/after mismatch, unrelated `false`, test-A/test-B mismatch, and successful same-test record.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m pytest tests/test_evidence_validator.py -q`

```bash
git add scripts/evidence_validator.py schemas/evidence.schema.json tests/test_evidence_validator.py
git commit -m "feat: add shared evidence validator"
```

### Task 2: Structured evidence collection and record verification

**Files:**
- Modify: `scripts/collect_evidence.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `tests/test_evidence.py`
- Modify: `tests/test_finding_transition.py`

**Interfaces:**
- `harness evidence --type <type> --command <cmd> [--finding FND-NNN --test node-id]`.
- Both identity flags required together.

- [ ] **Step 1: Write RED tests**

```python
def test_evidence_writes_structured_finding_test_identity(repo):
    result = cli(repo, "evidence", "--type", "custom", "--command", "false", "--finding", "FND-001", "--test", TEST)
    assert json.loads(evidence_path.read_text())["subject"]["id"] == "FND-001"


def test_confirmed_rejects_unrelated_failed_evidence(tmp_path):
    result = cli(tmp_path, "finding", "transition", "FND-001", "CONFIRMED", "--test", TEST, "--evidence", "red.json")
    assert result.returncode == 2
    assert "FINDING_SUBJECT_MISMATCH" in result.stderr
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_evidence.py tests/test_finding_transition.py -q`

Expected: FAIL because CLI does not accept/write identity and lifecycle does not require it.

- [ ] **Step 3: Implement minimal collection wiring**

Parse both optional CLI flags. Reject one without other with exit 2. Pass metadata to `collect`; persist subject/test. In `_verify_record`, replace ad-hoc freshness condition with shared validator.

- [ ] **Step 4: Implement finding proof wiring**

Replace local `proof` with shared validator. CONFIRMED requires matching FND/test failed record. FIXED requires matching stored FND/path successful record. VERIFIED requires fresh successful evidence only.

- [ ] **Step 5: Add stale RED/GREEN/full and test mismatch counterexamples**

Run separate tests for workspace mutation after each proof; test A RED/test B GREEN rejection; same test green acceptance.

- [ ] **Step 6: Run GREEN and commit**

Run: `python -m pytest tests/test_evidence.py tests/test_finding_transition.py tests/test_finding_lifecycle.py -q`

```bash
git add scripts/collect_evidence.py src/harness/cli.py src/harness/controlplane.py tests/test_evidence.py tests/test_finding_transition.py tests/test_finding_lifecycle.py
git commit -m "feat: bind finding proofs to fresh regression evidence"
```

### Task 3: Gate integration and current DONE enforcement

**Files:**
- Modify: `scripts/quality_gate.py`
- Modify: `src/harness/controlplane.py`
- Modify: `tests/test_quality_gate.py`
- Modify: `tests/test_control_plane.py`

**Interfaces:**
- `run_gate` delegates all evidence checks to `validate_evidence`.
- `harness transition DONE` reruns Gate only from CONVERGED.

- [ ] **Step 1: Write RED tests**

```python
def test_done_rejected_when_workspace_changes_after_convergence(repo):
    converge_to_pass(repo)
    (repo / "business.py").write_text("changed")
    result = cli(repo, "transition", "DONE")
    assert result.returncode == 1
    assert "CURRENT_GATE_PASS_REQUIRED" in result.stderr
    assert task_state(repo) == "CONVERGED"


def test_done_allowed_when_current_gate_passes(repo):
    converge_to_pass(repo)
    assert cli(repo, "transition", "DONE").returncode == 0
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_control_plane.py tests/test_quality_gate.py -q`

Expected: FAIL because direct transition does not rerun Gate.

- [ ] **Step 3: Replace Gate freshness copies**

Use validator for requirements, invariants, verification, complexity review, and finding red/green/full proof. Translate validator errors to existing blockers or fail-closed invalid harness state; retain policy decisions in gate.

- [ ] **Step 4: Add new-open-finding and stale-evidence DONE tests**

Test major finding created after convergence and stale required evidence both reject DONE without changing state.

- [ ] **Step 5: Implement DONE guard**

Before state mutation in `cmd_transition`, for exactly `CONVERGED -> DONE`, call `quality_gate.run_gate`. PASS proceeds; BLOCKED prints `CURRENT_GATE_PASS_REQUIRED` and returns 1; invalid prints deterministic error and returns 2.

- [ ] **Step 6: Run GREEN and commit**

Run: `python -m pytest tests/test_control_plane.py tests/test_quality_gate.py tests/test_finding_lifecycle.py -q`

```bash
git add scripts/quality_gate.py src/harness/controlplane.py tests/test_quality_gate.py tests/test_control_plane.py tests/test_finding_lifecycle.py
git commit -m "fix: require current gate pass before done"
```

### Task 4: Regression verification and focused re-review

**Files:**
- Modify only for defects exposed by verification.

- [ ] **Step 1: Run adversarial cases**

```bash
python -m pytest tests/test_evidence_validator.py tests/test_finding_transition.py tests/test_control_plane.py tests/test_quality_gate.py -q
```

Expected: all CR-001 through CR-003 tests PASS.

- [ ] **Step 2: Run full suite**

Run: `python -m pytest tests/ -q`

Expected: PASS.

- [ ] **Step 3: Re-review added code only**

Review validator callers for any remaining direct `commit`/fingerprint checks. Search:

```bash
rg 'workspace_fingerprint|\.get\("commit"\)' scripts src/harness
```

Every freshness decision must delegate to validator; documented evidence creation is excluded.

- [ ] **Step 4: Commit verification-only corrections**

```bash
git add scripts src/harness schemas tests
git commit -m "fix: harden evidence proof integrity"
```

## Plan self-review

- CR-001: Task 3 current DONE gate test/guard.
- CR-002: Tasks 1–3 shared validator and stale proof tests.
- CR-003: Tasks 1–2 structured regression identity and mismatch tests.
- CR-004 excluded by explicit scope.

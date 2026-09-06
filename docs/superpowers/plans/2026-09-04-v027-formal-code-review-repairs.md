# v0.2.7 Formal Code Review Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all blocking and important findings from formal v0.2.7 review without expanding Harness public surface.

**Architecture:** Reuse existing command handlers, canonical artifact/path helpers, workspace scope projection, and Gate validators. Make privileged state writes and proof claims fail closed; bind every proof to current task and canonical current scope.

**Tech Stack:** Python 3.11, PyYAML, jsonschema, pytest, Harness CLI.

**Spec:** `docs/Superpowers-Engineering-Harness-v0.2.7-正式CodeReview报告.md`; `.harness/requirements.yaml`; `.harness/invariants.yaml`.

## Global Constraints

- Reuse existing helpers; no module split, dependency, or new public API.
- Preserve accepted DEC-004 trusted-local shell boundary and DEC-008 CLI-only execution.
- Keep CLI errors deterministic and fail closed.
- Write each regression test first; run it red before production edit.
- Do not run full suite without explicit authorization.

---

### Task 1: Gate-owned state transitions and Gate entry contract

**Files:**
- Modify: `src/harness/controlplane.py`, `src/harness/quality_gate.py`, `SKILL.md`, `skills/convergence/SKILL.md`, `skills/quality-gate/SKILL.md`
- Test: `tests/test_convergence_cli.py`, `tests/test_convergence.py`

**Interfaces:**
- Consumes: `cmd_transition(target)`, `_cmd_gate_convergence()`.
- Produces: generic transition rejects Gate-owned terminal edges; `harness gate` remains sole convergence writer.

- [ ] **Step 1: Write failing CLI regression tests**

```python
assert run_cli(repo, "transition", "CONVERGED").returncode == 1
assert "GATE_DECISION_REQUIRED" in result.stderr
assert run_cli(repo, "transition", "BLOCKED").returncode == 1
```

- [ ] **Step 2: Run RED test**

Run: `pytest tests/test_convergence_cli.py -q`
Expected: failure because generic transition accepts one or both Gate-owned edges.

- [ ] **Step 3: Implement smallest command guard**

```python
if current == "GATING" and target in {"CONVERGED", "BLOCKED"}:
    print("GATE_DECISION_REQUIRED: use harness gate", file=sys.stderr)
    return 1
```

Map invalid Gate state in `_cmd_gate_convergence` to exit `2`; remove product-command equivalence from Skills.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_convergence_cli.py tests/test_convergence.py -q`
Expected: PASS.

### Task 2: Test-plan proof binding

**Files:**
- Modify: `src/harness/test_plan.py`
- Test: `tests/test_test_plan_gate.py`, `tests/test_test_plan_lifecycle.py`

**Interfaces:**
- Consumes: evidence record `type`, `command`, `covered_tests`; `pytest_selectors(command)`.
- Produces: `validate_test_coverage()` accepts only selected unit/integration/contract test evidence.

- [ ] **Step 1: Write failing coverage-bypass tests**

```python
record["type"] = "lint"
record["command"] = "true"
record["covered_tests"] = [NODE]
assert "TEST_EVIDENCE_MISSING" in blocker_codes(harness_dir)
```

Also test `pytest` without a selector and selector for another node.

- [ ] **Step 2: Run RED test**

Run: `pytest tests/test_test_plan_gate.py tests/test_test_plan_lifecycle.py -q`
Expected: bypass case incorrectly reaches covered state.

- [ ] **Step 3: Implement typed selector predicate**

```python
return (
    record.get("type") in TEST_EVIDENCE_TYPES
    and node_id in record.get("covered_tests", [])
    and evidence_is_fresh(record)
    and _selector_covers(record.get("command") or "", node_id)
)
```

`_selector_covers` returns false for missing/non-pytest selectors.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_test_plan_gate.py tests/test_test_plan_lifecycle.py -q`
Expected: PASS.

### Task 3: Canonical evidence output and attach binding

**Files:**
- Modify: `src/harness/paths.py`, `src/harness/collect_evidence.py`, `src/harness/controlplane.py`, `src/harness/cli.py`, `src/harness/schemas/evidence.schema.json`
- Test: `tests/test_collect_evidence.py`, `tests/test_evidence_validator.py`, `tests/test_cli_evidence_reuse.py`

**Interfaces:**
- Consumes: `evidence_output_path(harness_dir, filename)`, `VALID_TYPES`, current task identity.
- Produces: all evidence writes stay under canonical evidence directory; attach records bind current task and accepted provenance.

- [ ] **Step 1: Write traversal and foreign-attach RED tests**

```python
assert main(["--finding", "../outside", ...]) == 2
assert not (repo / ".harness" / "outside-red-unit_test.json").exists()
record["task"] = "TASK-OTHER"
assert cmd_evidence_attach("unit_test", "pytest x", "related", source) == 2
```

Cover absolute finding IDs, invalid type, unsigned/incoherent attach fields per DEC-010.

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_collect_evidence.py tests/test_evidence_validator.py tests/test_cli_evidence_reuse.py -q`
Expected: escaping or foreign/unsigned record accepted.

- [ ] **Step 3: Reuse canonical validators**

Validate finding ID before filename generation; use `evidence_output_path` for run and attach; restrict CLI type to `VALID_TYPES`. Validate task ID, provenance, exit/result coherence, schema, freshness, then atomically write.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_collect_evidence.py tests/test_evidence_validator.py tests/test_cli_evidence_reuse.py -q`
Expected: PASS.

### Task 4: Canonical scope and review freshness

**Files:**
- Modify: `src/harness/workspace.py`, `src/harness/controlplane.py`, `src/harness/quality_gate.py`, `src/harness/interface_review.py`, `src/harness/complexity.py`
- Test: `tests/test_impact_control_plane.py`, `tests/test_cli_complexity.py`, `tests/test_complexity_review.py`, `tests/test_interface_gate.py`, `tests/test_interface_review.py`

**Interfaces:**
- Consumes: `project_task_scope(task, impact, inspected_paths=...)` and review `review_scope`.
- Produces: owned/contract scope cannot be protected away; required review evidence must exactly cover current scope and contracts.

- [ ] **Step 1: Write RED scope tests**

```python
assert project_task_scope(task, {"contracts": ["src/api.py"]}) == ("src/api.py",)
assert ignore_owned.returncode == 1
assert "COMPLEXITY_REVIEW_STALE" in blocker_codes(harness_dir)
```

Add interface proof stale after `impact add-contract` and missing required contract ID.

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_impact_control_plane.py tests/test_cli_complexity.py tests/test_complexity_review.py tests/test_interface_gate.py tests/test_interface_review.py -q`
Expected: stale scope or protected owned/contract path accepted.

- [ ] **Step 3: Implement scope reuse**

Build effective scope from owned, contracts, dependents, and inspected paths without protected subtraction. Reject `ignore-user-path` for owned/contract path. Persist complexity/interface `review_scope`; Gate recomputes expected files and verifies all required complexity checks and interface contract IDs.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_impact_control_plane.py tests/test_cli_complexity.py tests/test_complexity_review.py tests/test_interface_gate.py tests/test_interface_review.py -q`
Expected: PASS.

### Task 5: Finding lifecycle schema and fail-closed loaders

**Files:**
- Modify: `src/harness/controlplane.py`, `src/harness/schemas/interface-finding.schema.json`
- Test: `tests/test_finding_lifecycle.py`, `tests/test_finding_transition.py`, `tests/test_finding_schema.py`, `tests/test_interface_review.py`

**Interfaces:**
- Consumes: canonical finding lifecycle and `_findings(harness_dir)`.
- Produces: interface findings can persist closure proof; malformed YAML cannot resume or transition lifecycle.

- [ ] **Step 1: Write RED lifecycle tests**

```python
bad.write_text("- not-a-finding")
assert run_cli(repo, "finding", "resume-review", "FND-001").returncode == 2
finding["status"] = "CONFIRMED"
finding["regression_test"] = {"path": "tests/test_x.py"}
validate_interface_finding(finding)
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_finding_lifecycle.py tests/test_finding_transition.py tests/test_finding_schema.py tests/test_interface_review.py -q`
Expected: traceback/schema rejection.

- [ ] **Step 3: Implement canonical loading and closure fields**

Route resume through `_findings`; reject YAML parse and non-mapping artifacts with typed exit `2`. Add canonical regression/evidence/timestamp/closure fields to interface finding schema.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_finding_lifecycle.py tests/test_finding_transition.py tests/test_finding_schema.py tests/test_interface_review.py -q`
Expected: PASS.

### Task 6: Git baseline, impact/status projection, attach reason codes

**Files:**
- Modify: `src/harness/workspace.py`, `src/harness/controlplane.py`, `src/harness/harness_status.py`
- Test: `tests/test_cli_task_recovery.py`, `tests/test_impact_control_plane.py`, `tests/test_status_projection.py`

**Interfaces:**
- Consumes: `git_baseline(head)`, observability inspected paths, canonical live Gate/finding loaders.
- Produces: full immutable Git identity; impact/status read live canonical state.

- [ ] **Step 1: Write RED tests**

```python
assert set(task["git"]) == {"base_ref", "base_commit", "head_at_start", "head"}
assert "src/inspected.py" in impact_scope(repo)
assert "Major      1" in run_status(repo)
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_cli_task_recovery.py tests/test_impact_control_plane.py tests/test_status_projection.py -q`
Expected: incomplete Git identity, missing inspected path, or cached status.

- [ ] **Step 3: Implement projection helpers**

Use `git_baseline` in classify/new/recover. Include required observability inspected paths in impact and review scope. Read canonical findings and assessment in status without persistence mutation. Preserve typed attach error causes rather than collapsing them.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_cli_task_recovery.py tests/test_impact_control_plane.py tests/test_status_projection.py -q`
Expected: PASS.

### Task 7: Integrate current patch and focused verification

**Files:**
- Modify: affected production/test files only from Tasks 1–6
- Test: `tests/test_v027_review_fixes.py` plus all Task 1–6 tests

**Interfaces:**
- Consumes: all repaired public CLI and Gate seams.
- Produces: review report requirements covered by focused regression evidence.

- [ ] **Step 1: Write missing report-level RED tests**

Add one public-seam test per uncovered report requirement; avoid test-only implementation branches.

- [ ] **Step 2: Run RED test**

Run: `pytest tests/test_v027_review_fixes.py -q`
Expected: each new regression fails before corresponding production repair.

- [ ] **Step 3: Make smallest remaining repairs**

Use existing helpers only; remove superseded compatibility paths that permit bypasses.

- [ ] **Step 4: Run focused GREEN suite and static check**

Run: `pytest -q tests/test_v027_review_fixes.py tests/test_convergence_cli.py tests/test_test_plan_gate.py tests/test_test_plan_lifecycle.py tests/test_collect_evidence.py tests/test_impact_control_plane.py tests/test_cli_complexity.py tests/test_complexity_review.py tests/test_interface_gate.py tests/test_interface_review.py tests/test_finding_lifecycle.py tests/test_finding_transition.py tests/test_cli_task_recovery.py tests/test_status_projection.py && ruff check src tests`
Expected: PASS.

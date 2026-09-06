# v0.2.7 Review Report Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair valid v0.2.7 review findings while preserving DEC-012 Finding-only evidence-scope contract.

**Architecture:** Finding `category` becomes required universal discriminator. Schema resolver selects only explicit categories; legacy artifacts lacking category fail with `MIGRATION_REQUIRED`. Existing evidence scope branch stays unchanged. Root Skill documents current existing subcommands.

**Tech Stack:** Python 3.11, pytest, PyYAML, jsonschema, Markdown.

**Spec:** `.harness/requirements.yaml`, `.harness/invariants.yaml`, `.harness/decisions/DEC-012.yaml`, `.harness/decisions/DEC-013.yaml`, `.harness/decisions/DEC-014.yaml`

## Global Constraints

- Preserve DEC-012: persist `scope` only for Finding evidence.
- Require `category: adversarial` for all new adversarial Findings.
- Category-less persisted Finding fails `MIGRATION_REQUIRED` before schema validation.
- No dependencies or abstractions.
- Preserve unrelated user workspace changes.

---

### Task 1: Make Finding category explicit

**Files:**
- Modify: `src/harness/schemas/adversarial-finding.schema.json`
- Modify: `src/harness/quality_gate.py: finding_schema_name`
- Modify: all test Finding fixtures/literals found by `rg -l 'kind:|"kind"' tests`
- Test: `tests/test_finding_schema.py`, `tests/test_quality_gate.py`

**Interfaces:**
- Consumes: persisted Finding mapping.
- Produces: `finding_schema_name(finding: dict) -> str`; only explicit `adversarial`, `diagnosability`, `complexity`, and `interface` categories select schemas.

- [ ] **Step 1: Write resolver RED tests**

```python
assert finding_schema_name({**BASE, "category": "adversarial"}) == "adversarial-finding.schema.json"
with pytest.raises(InvalidHarnessState, match="MIGRATION_REQUIRED"):
    finding_schema_name(BASE)
```

- [ ] **Step 2: Run RED test**

Run: `pytest tests/test_finding_schema.py::test_canonical_finding_schema_resolver_selects_one_schema_per_category -q`
Expected: FAIL because category-less `BASE` currently resolves adversarial schema.

- [ ] **Step 3: Require adversarial category in schema**

```json
"required": ["id", "category", "kind", "target", "scenario", "severity", "status"],
"category": {"const": "adversarial"}
```

- [ ] **Step 4: Remove kind fallback**

```python
if category == "adversarial":
    return "adversarial-finding.schema.json"
if category is None:
    raise InvalidHarnessState("MIGRATION_REQUIRED")
raise InvalidHarnessState("FINDING_SCHEMA_UNKNOWN")
```

- [ ] **Step 5: Migrate current producers and fixtures**

For every adversarial test mapping or YAML fixture identified by:

```bash
rg -l 'kind: (failure_scenario|requirement_violation|invariant_violation)|"kind": "(failure_scenario|requirement_violation|invariant_violation)"' tests
```

add `category: adversarial` beside `kind`. Do not add it to complexity, diagnosability, or interface documents.

- [ ] **Step 6: Run GREEN tests**

Run: `pytest tests/test_finding_schema.py tests/test_quality_gate.py -q`
Expected: PASS.

### Task 2: Preserve Finding-only evidence scope contract

**Files:**
- Modify: `tests/test_evidence.py: test_collect_related_scope_records_covered_tests`
- Test: `tests/test_evidence.py: test_collect_integration_related_scope_records_scope`

**Interfaces:**
- Consumes: `collect_evidence._collect(..., finding_id=None, scope="related")`.
- Produces: task-level evidence omits `scope`; Finding evidence includes caller-selected scope.

- [ ] **Step 1: Change stale expectation**

```python
evidence = json.loads((tmp_path / "evidence" / "unit-test.json").read_text())
assert "scope" not in evidence
assert evidence["covered_tests"] == ["tests/test_x.py::test_x"]
```

- [ ] **Step 2: Run focused evidence tests**

Run: `pytest tests/test_evidence.py::test_collect_related_scope_records_covered_tests tests/test_evidence.py::test_collect_integration_related_scope_records_scope -q`
Expected: PASS.

### Task 3: Update workflow Skill contract

**Files:**
- Modify: `SKILL.md: Phase Dispatch Table, deterministic commands, evidence examples`

- [ ] **Step 1: Replace deprecated evidence examples**

```bash
harness evidence run --type unit_test --scope related --command "pytest tests/test_file.py -q"
```

- [ ] **Step 2: Add required current command routes**

Document `harness impact scope --format yaml`, `harness finding resume-review FND-001`, `harness evidence attach`, and `harness gate preflight` at their dispatch points.

- [ ] **Step 3: Verify documentation contract**

Run: `rg -n -- "evidence run|evidence attach|gate preflight|finding resume-review|impact scope" SKILL.md && ! rg -n -- "harness evidence --type" SKILL.md`
Expected: exit 0.

### Task 4: Focused regression verification

**Files:**
- Test: Finding-producing test modules identified in Task 1
- Test: `tests/test_finding_schema.py`, `tests/test_quality_gate.py`, `tests/test_evidence.py`

- [ ] **Step 1: Run changed Finding test modules plus focused tests**

Run: `pytest tests/test_finding_schema.py tests/test_quality_gate.py tests/test_evidence.py -q`
Expected: PASS. Add every Task 1 modified test module to this command.

- [ ] **Step 2: Run build check**

Run: `python -m compileall -q src`
Expected: PASS.

- [ ] **Step 3: Collect Harness evidence**

Run: `harness evidence run --type unit_test --scope related --covered-test tests/test_finding_schema.py --covered-test tests/test_quality_gate.py --covered-test tests/test_evidence.py --command "pytest tests/test_finding_schema.py tests/test_quality_gate.py tests/test_evidence.py -q"`
Expected: fresh successful evidence.

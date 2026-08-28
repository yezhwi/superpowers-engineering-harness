# v0.2.4 Test Plan Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fail-closed Test Plan and Test Case-to-Evidence traceability for STANDARD/STRICT Harness tasks.

**Architecture:** Keep test design separate from proof. Add optional `test_plan` to Requirement and Invariant records while retaining existing `Requirement.evidence` and `Invariant.verification` Evidence-reference fields. Put validation and coverage projection in a dedicated `harness.test_plan` module; control plane calls plan validation before `PLANNED → IMPLEMENTING`, while quality gate calls final coverage validation and emits typed blockers.

**Tech Stack:** Python 3.11, PyYAML, jsonschema, pytest.

**Spec:** `docs/Superpowers-Engineering-Harness-v0.2.4TestPlanGate实施需求文档.md`

## Global Constraints

- Release version is `0.2.4` in Python package, npm package, README, CHANGELOG, and version-consistency test.
- Do not add a state-machine state; STANDARD/STRICT plan check is `PLANNED → IMPLEMENTING`.
- Q1/FAST retains `CLASSIFIED → IMPLEMENTING` and existing Light Gate behavior.
- `test_plan` is optional in schemas for old documents; STANDARD/STRICT transition rejects incomplete new-task plans.
- `test_plan` describes intent; `Requirement.evidence` and `Invariant.verification` remain Evidence references.
- No AI test generation, coverage percentage gate, mutation/property testing framework, SaaS, LLM judge, or auto-repair.
- Automated case bindings require successful Evidence fresh for current HEAD and workspace. `manual` cases require Evidence but no executable binding.
- Preserve typed blocker recovery: incomplete plan/binding → `IMPLEMENTING`; missing Evidence → `VERIFYING`.

---

### Task 1: Test-plan schemas and pure validator

**Files:**
- Create: `src/harness/test_plan.py`
- Modify: `src/harness/schemas/requirement.schema.json`
- Modify: `src/harness/schemas/invariant.schema.json`
- Modify: `tests/test_task_contract.py`
- Create: `tests/test_test_plan.py`

**Interfaces:**
- Produces `TestPlanIssue(code: str, message: str, requirement_id: str | None, invariant_id: str | None, test_case_id: str | None)`.
- Produces `validate_test_plan(requirements: dict, invariants: dict) -> list[TestPlanIssue]`.
- Produces constants `AUTOMATED_STRATEGIES` and `VALID_STRATEGIES` shared by final-coverage code.

- [ ] **Step 1: Write failing schema tests**

```python
def test_requirement_schema_accepts_optional_test_plan_and_old_record():
    validate({"requirements": [{"id": "REQ-001", "statement": "old", "priority": "must", "status": "pending"}]}, schema)
    validate({"requirements": [{"id": "REQ-002", "statement": "new", "priority": "must", "status": "pending", "type": "feature", "test_plan": {"strategies": ["unit"], "cases": [{"id": "TC-001", "type": "happy_path", "strategy": "unit", "description": "works"}]}}]}, schema)

def test_invariant_schema_keeps_evidence_verification_separate_from_test_plan():
    validate({"invariants": [{"id": "INV-001", "statement": "safe", "category": "correctness", "severity": "critical", "status": "pending", "verification": [], "test_plan": {"strategies": ["integration"], "cases": [{"id": "TC-002", "type": "invariant", "strategy": "integration", "description": "holds"}]}}]}, schema)
```

- [ ] **Step 2: Run schema tests and verify RED**

Run: `python -m pytest tests/test_task_contract.py tests/test_test_plan.py -q`

Expected: FAIL because `test_plan`, `type`, and Case fields are not schema properties and `harness.test_plan` does not exist.

- [ ] **Step 3: Write failing validator tests**

```python
def test_rejects_requirement_without_test_plan_strategy():
    assert issue_codes(requirements={"requirements": [requirement(test_plan={"strategies": [], "cases": []})]}) == {"TEST_PLAN_REQUIREMENT_STRATEGY_MISSING"}

def test_rejects_critical_invariant_without_case():
    assert issue_codes(invariants={"invariants": [invariant(severity="critical", test_plan={"strategies": ["integration"], "cases": []})]}) == {"TEST_PLAN_CRITICAL_INVARIANT_UNCOVERED"}

def test_rejects_bugfix_without_regression_case():
    assert issue_codes(requirements={"requirements": [requirement(type="bugfix", test_plan=plan("unit", case("happy_path", "unit")))]}) == {"TEST_PLAN_REGRESSION_REQUIRED"}

def test_rejects_task_wide_duplicate_case_id_and_case_strategy_not_in_parent_plan():
    issues = validate_test_plan(requirements_with_case("TC-001", "unit"), invariants_with_case("TC-001", "integration"))
    assert {issue.code for issue in issues} == {"TEST_PLAN_CASE_DUPLICATE"}
```

- [ ] **Step 4: Implement minimal schema and validator**

Add optional `type` enum (`feature`, `bugfix`, `refactor`, `nonfunctional`) and optional `test_plan` object to both schemas. `test_plan` requires nonempty `strategies` enum values and `cases`; each Case requires `id`, `type`, `strategy`, and `description`, with optional string-array `tests`. Do not make `test_plan` schema-required.

Implement validator only for cross-field policy schema cannot express: Requirement strategy missing, critical invariant uncovered, bugfix regression case missing, global TC duplicate, and Case strategy absent from parent strategies. Treat omitted Requirement `type` as `feature`.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_task_contract.py tests/test_test_plan.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/test_plan.py src/harness/schemas/requirement.schema.json src/harness/schemas/invariant.schema.json tests/test_task_contract.py tests/test_test_plan.py
git commit -m "feat: add structured test plan validation"
```

### Task 2: Plan Gate at STANDARD/STRICT implementation entry

**Files:**
- Modify: `src/harness/controlplane.py`
- Create: `tests/test_test_plan_transition.py`

**Interfaces:**
- Consumes `validate_test_plan()` from `harness.test_plan`.
- Produces stderr headed by `TEST_PLAN_BLOCKED` and one deterministic issue per line.
- Does not change Q1/FAST entry behavior.

- [ ] **Step 1: Write failing transition tests**

```python
def test_standard_planned_to_implementing_rejects_invalid_test_plan(tmp_path):
    repo = standard_repo_in_state(tmp_path, "PLANNED")
    write_minimal_decision(repo, "TASK-004")
    write_requirement_plan(repo, strategies=[], cases=[])
    result = cli(repo, "transition", "IMPLEMENTING")
    assert result.returncode == 1
    assert "TEST_PLAN_BLOCKED" in result.stderr
    assert task_state(repo) == "PLANNED"

def test_standard_planned_to_implementing_accepts_valid_test_plan(tmp_path):
    repo = standard_repo_in_state(tmp_path, "PLANNED")
    write_minimal_decision(repo, "TASK-004")
    write_valid_requirement_and_critical_invariant_plans(repo)
    assert cli(repo, "transition", "IMPLEMENTING").returncode == 0

def test_fast_classified_to_implementing_does_not_load_test_plan(tmp_path):
    repo = fast_repo_in_state(tmp_path, "CLASSIFIED")
    assert cli(repo, "transition", "IMPLEMENTING").returncode == 0
```

- [ ] **Step 2: Run transition tests and verify RED**

Run: `python -m pytest tests/test_test_plan_transition.py -q`

Expected: FAIL because `cmd_transition()` checks only minimal-implementation evidence.

- [ ] **Step 3: Implement minimal control-plane seam**

In `cmd_transition`, after minimal-decision validation and before `require_legal`, load and schema-validate `.harness/requirements.yaml` and `.harness/invariants.yaml`, call `validate_test_plan`, print `TEST_PLAN_BLOCKED` and rendered IDs/codes to stderr, and return `1` without saving task when issues exist. Run this only for `current == "PLANNED" and target == "IMPLEMENTING"`; FAST never reaches this edge.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_cli_complexity.py tests/test_risk.py tests/test_test_plan_transition.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/controlplane.py tests/test_test_plan_transition.py
git commit -m "feat: gate implementation on test plan"
```

### Task 3: Evidence coverage and typed Gate recovery

**Files:**
- Modify: `src/harness/collect_evidence.py`
- Modify: `src/harness/schemas/evidence.schema.json`
- Modify: `src/harness/test_plan.py`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/blockers.py`
- Modify: `tests/evidence_factory.py`
- Create: `tests/test_test_plan_gate.py`
- Modify: `tests/test_blocker_recovery.py`
- Modify: `tests/test_evidence.py`

**Interfaces:**
- Produces `validate_test_coverage(requirements, invariants, evidence_records, head, workspace) -> list[TestPlanIssue]`.
- Coverage issue codes: `TEST_BINDING_MISSING`, `TEST_EVIDENCE_MISSING`.
- New blocker codes use existing categories: binding `implementation`, evidence `verification`.

- [ ] **Step 1: Write failing evidence and Gate tests**

```python
def test_collect_evidence_records_covered_tests_for_integration_test():
    record = collect("integration_test", "true", covered_tests=("tests/test_api.py::test_create",))
    assert record["covered_tests"] == ["tests/test_api.py::test_create"]

def test_gate_blocks_automated_case_without_binding(tmp_path):
    h = passing_harness_with_plan(tmp_path, case(strategy="integration", tests=[]))
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert blocker_codes(blockers) == {"TEST_BINDING_MISSING"}

def test_gate_blocks_binding_without_fresh_covered_evidence(tmp_path):
    h = passing_harness_with_plan(tmp_path, case(strategy="integration", tests=[NODE]))
    write_evidence(REPO, h, "integration_test", covered_tests=[])
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert blocker_codes(blockers) == {"TEST_EVIDENCE_MISSING"}

def test_two_same_type_evidence_records_cover_two_cases(tmp_path):
    h = passing_harness_with_two_cases(tmp_path)
    write_evidence(REPO, h, "unit_test", name="case-a.json", covered_tests=[NODE_A])
    write_evidence(REPO, h, "unit_test", name="case-b.json", covered_tests=[NODE_B])
    assert run_gate(h)[0] == "PASS"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_evidence.py tests/test_blocker_recovery.py tests/test_test_plan_gate.py -q`

Expected: FAIL because non-unit Evidence drops `covered_tests`, `load_evidence()` overwrites same-type files, and Gate has no Test Plan coverage check.

- [ ] **Step 3: Implement minimal coverage model**

Permit `covered_tests` for every Evidence type; keep `scope` policy only where existing full-suite authorization requires it. Make `load_evidence()` return every validated record with its filename rather than a `{type: record}` map; update existing required-verification lookup to select a matching record by type. In `validate_test_coverage`, ignore no-plan legacy records, require bindings for automatic cases, require one successful fresh Evidence record covering each binding, and require at least one successful fresh Evidence record for manual cases.

Insert coverage blockers in STANDARD/STRICT `run_gate` after Evidence loading. Add recovery entries exactly: `TEST_PLAN_INCOMPLETE` and `TEST_BINDING_MISSING` to `IMPLEMENTING`; `TEST_EVIDENCE_MISSING` to `VERIFYING`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_evidence.py tests/test_quality_gate.py tests/test_blocker_recovery.py tests/test_test_plan_gate.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/collect_evidence.py src/harness/schemas/evidence.schema.json src/harness/test_plan.py src/harness/quality_gate.py src/harness/blockers.py tests/evidence_factory.py tests/test_evidence.py tests/test_quality_gate.py tests/test_blocker_recovery.py tests/test_test_plan_gate.py
git commit -m "feat: trace test case evidence in quality gate"
```

### Task 4: Templates, status projection, lifecycle coverage, and release docs

**Files:**
- Modify: `src/harness/templates/requirements.yaml`
- Modify: `src/harness/templates/invariants.yaml`
- Modify: `src/harness/harness_status.py`
- Modify: `tests/test_init.py`
- Modify: `tests/test_status_projection.py`
- Create: `tests/test_test_plan_lifecycle.py`
- Modify: `pyproject.toml`
- Modify: `package.json`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_version_consistency.py`

**Interfaces:**
- Status displays planned Requirement and critical Invariant counts plus binding/Evidence coverage counts when documents contain `test_plan`.
- Lifecycle test uses public CLI transitions and `harness gate`; it does not call private validator internals to claim workflow behavior.

- [ ] **Step 1: Write failing template/status/lifecycle/version tests**

```python
def test_init_templates_document_structured_test_plan_without_creating_fake_requirements():
    text = resources.files("harness").joinpath("templates", "requirements.yaml").read_text()
    assert "requirements: []" in text
    assert "test_plan:" in text
    assert "strategy: unit" in text

def test_status_projects_test_plan_counts_without_mutation(tmp_path):
    repo = standard_repo_with_plan(tmp_path)
    before = task_path(repo).read_bytes()
    result = cli(repo, "status")
    assert "Executable Bindings:" in result.stdout
    assert task_path(repo).read_bytes() == before

def test_full_lifecycle_requires_case_binding_and_evidence_before_done(tmp_path):
    repo = standard_repo(tmp_path)
    plan_task_to_implementing(repo)
    bind_cases(repo)
    record_current_evidence(repo)
    transition_through_review_and_gate(repo)
    assert task_state(repo) == "DONE"

def test_v024_release_metadata_is_publishable():
    assert project_version() == "0.2.4"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_init.py tests/test_status_projection.py tests/test_test_plan_lifecycle.py tests/test_version_consistency.py -q`

Expected: FAIL because templates/status/lifecycle/release metadata are still v0.2.3 behavior.

- [ ] **Step 3: Implement minimal presentation and release changes**

Keep `requirements: []` and `invariants: []` so `harness init` never creates fake gate-blocking work. Add complete commented `test_plan` examples below each empty list, including `statement`, `strategy`, and an executable binding. Extend status using the pure traceability projection from `test_plan.py`; no status mutation. Update both READMEs and CHANGELOG with actual CLI behavior, then change all package/docs release strings and rename the version-specific test to v0.2.4.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_init.py tests/test_status_projection.py tests/test_test_plan_lifecycle.py tests/test_version_consistency.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/templates src/harness/harness_status.py tests/test_init.py tests/test_status_projection.py tests/test_test_plan_lifecycle.py pyproject.toml package.json README.md README.zh-CN.md CHANGELOG.md tests/test_version_consistency.py
git commit -m "feat: release test plan gate v0.2.4"
```

### Task 5: Full regression, contract evidence, review, and Gate

**Files:**
- Modify: `.harness/impact.yaml`
- Modify: `.harness/evidence/*.json`
- Modify: `.harness/current-task.yaml` through Harness commands only

**Interfaces:**
- Consumes implemented CLI and all new tests.
- Produces fresh, HEAD-bound build/unit-test Evidence, complexity review, review outcome, and deterministic Gate result.

- [ ] **Step 1: Record changed paths, dependents, contracts, risks, and related tests**

```bash
harness impact add-change src/harness/test_plan.py
harness impact add-change src/harness/controlplane.py
harness impact add-change src/harness/quality_gate.py
harness impact add-dependent src/harness/cli.py
harness impact add-contract REQ-001
harness impact add-risk "Test Plan fields must not collide with invariant evidence references"
harness impact add-test "python -m pytest tests/test_test_plan.py tests/test_test_plan_transition.py tests/test_test_plan_gate.py tests/test_test_plan_lifecycle.py -q"
```

- [ ] **Step 2: Run focused feature regression and build Evidence**

```bash
harness evidence --type unit_test --covered-test tests/test_test_plan.py --covered-test tests/test_test_plan_transition.py --covered-test tests/test_test_plan_gate.py --covered-test tests/test_test_plan_lifecycle.py --command "python -m pytest tests/test_test_plan.py tests/test_test_plan_transition.py tests/test_test_plan_gate.py tests/test_test_plan_lifecycle.py -q"
harness evidence --type build --command "python -m pip wheel . --no-deps --wheel-dir /tmp/harness-v024-wheels"
```

Expected: both commands write successful fresh Evidence.

- [ ] **Step 3: Request full-suite authorization before full regression**

Ask user for authorization. Do not run full suite until user grants it with `harness authorize full-suite`.

- [ ] **Step 4: Run authorized full suite, package checks, and diff check**

```bash
harness evidence --type unit_test --scope full_suite --command "python -m pytest tests/ -q"
python -m pip wheel . --no-deps --wheel-dir /tmp/harness-v024-wheels
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 5: Record complexity review and review outcome**

```bash
harness review complexity --file complexity-review.yaml
harness review outcome PASS --reason-code REVIEW_CLEAN
```

Expected: `REVIEWING → GATING` only after fresh complexity Evidence and clean review.

- [ ] **Step 6: Run deterministic Gate and finish only on PASS**

```bash
harness gate
harness transition DONE
```

Expected: Gate exit 0, state `CONVERGED`, then `DONE`.

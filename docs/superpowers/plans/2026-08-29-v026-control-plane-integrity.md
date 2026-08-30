# v0.2.6 Control-Plane Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make diagnosability Contract/review/Finding/Gate artifacts fail-closed, transactionally persisted, and E2E-tested.

**Architecture:** `diagnosability.py` owns semantic validation; new `transaction.py` owns staging/publish only. CLI and Gate call validators and never duplicate review semantics. Test-only fixture builder creates complete lifecycle baselines.

**Tech Stack:** Python 3.11, PyYAML, jsonschema, pytest, existing workspace/evidence APIs.

**Spec:** `docs/superpowers/specs/2026-08-29-v026-control-plane-integrity-design.md`

## Global Constraints

- No logger SDK, OTel/APM, automatic log insertion, universal scanner, or new logging capability.
- Existing `v0.2.5` tag remains immutable.
- Semantic validation fails closed.
- Ordinary Finding RED/GREEN lifecycle remains unchanged.
- Run related tests by default; full suite only with explicit authorization.
- Every new defensive branch gets an error/counterexample test.

---

### Task 1: Task type and Contract propagation

**Files:**
- Modify: `src/harness/schemas/task.schema.json`
- Modify: `src/harness/templates/current-task.yaml`
- Modify: `src/harness/diagnosability.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_task_new.py`
- Test: `tests/test_diagnosability.py`

**Interfaces:**

```python
def load_contract(harness_dir: Path, *, task_type: str | None = None) -> dict: ...
```

- [ ] Write RED tests: default task `type == "feature"`; bugfix Contract containing `bug_fix.observability_gap=false` loads through CLI/Gate path.
- [ ] Run:
  ```bash
  pytest tests/test_task_new.py tests/test_diagnosability.py -q
  ```
  Expect failure before propagation implementation.
- [ ] Add task type enum/default; pass persisted task type through review and Gate Contract loaders. Old missing type defaults to feature.
- [ ] Run same tests; expect PASS.
- [ ] Commit:
  ```bash
  git add src/harness/schemas/task.schema.json src/harness/templates/current-task.yaml src/harness/diagnosability.py src/harness/controlplane.py tests/test_task_new.py tests/test_diagnosability.py
  git commit -m "fix: propagate task type to diagnosability contract"
  ```

### Task 2: Separate review readiness validation

**Files:**
- Modify: `src/harness/diagnosability.py`
- Modify: `src/harness/quality_gate.py`
- Test: `tests/test_diagnosability.py`
- Test: `tests/test_diagnosability_gate.py`

**Interfaces:**

```python
def validate_review_readiness(
    contract: dict, review: DiagnosabilityReview | dict,
    findings: list[dict], *, scope_files: tuple[str, ...],
    current_head: str, current_workspace: str,
) -> None: ...
```

- [ ] Write RED counterexamples: contract-required mismatch; failed check without linked DIAG Finding; Finding outside scope; required Contract dimension marked `not_applicable`; stale review evidence.
- [ ] Run:
  ```bash
  pytest tests/test_diagnosability.py tests/test_diagnosability_gate.py -q
  ```
- [ ] Implement readiness validator. It rejects semantic mismatch and treats `fail` review as DEFECT evidence, never Gate-ready evidence. Keep `validate_compliance_closure()` limited to terminal DIAG Finding proof.
- [ ] Route Gate through readiness validator only.
- [ ] Run same tests; expect PASS.
- [ ] Commit:
  ```bash
  git add src/harness/diagnosability.py src/harness/quality_gate.py tests/test_diagnosability.py tests/test_diagnosability_gate.py
  git commit -m "fix: enforce diagnosability review readiness"
  ```

### Task 3: Transactional review/Finding persistence

**Files:**
- Create: `src/harness/transaction.py`
- Modify: `src/harness/diagnosability.py`
- Modify: `src/harness/workspace.py`
- Modify: `src/harness/schemas/diagnosability-review.schema.json`
- Test: `tests/test_cli_diagnosability.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class StagedArtifact:
    relative_path: str
    content: bytes

def stage(harness_dir: Path, operation_id: str, artifacts: list[StagedArtifact]) -> Path: ...
def publish(harness_dir: Path, stage_dir: Path) -> None: ...
def cleanup_stale_staging(harness_dir: Path) -> None: ...
```

- [ ] Write RED tests: valid failed review atomically creates proposed DIAG Finding plus evidence; invalid Finding creates neither; injected publish failure creates no incomplete canonical review/Finding set; staging is excluded from workspace scope.
- [ ] Run:
  ```bash
  pytest tests/test_cli_diagnosability.py tests/test_workspace.py -q
  ```
- [ ] Validate every artifact before staging. Stage all Finding YAML and canonical evidence under `.harness/.staging/<operation-id>`. Publish with temp-file replace; reject existing Finding IDs; preserve staging for publish diagnostics.
- [ ] Run same tests; expect PASS.
- [ ] Commit:
  ```bash
  git add src/harness/transaction.py src/harness/diagnosability.py src/harness/workspace.py src/harness/schemas/diagnosability-review.schema.json tests/test_cli_diagnosability.py tests/test_workspace.py
  git commit -m "feat: stage diagnosability review artifacts atomically"
  ```

### Task 4: Shared complete Harness fixture builder

**Files:**
- Create: `tests/fixtures/harness.py`
- Create: `tests/test_harness_fixture.py`
- Modify: `tests/test_control_plane.py`
- Modify: `tests/test_convergence_cli.py`
- Modify: `tests/test_finding_lifecycle.py`

**Interfaces:**

```python
def make_harness(
    tmp_path: Path, *, state: str = "GATING", risk: str = "Q2",
    task_type: str = "feature", observability: str = "required",
    test_plan: str = "complete",
) -> Path: ...
```

- [ ] Write RED tests proving builder emits schema-valid task/Contract, complete test plans, fresh evidence, and requested risk/observability mode.
- [ ] Run:
  ```bash
  pytest tests/test_harness_fixture.py -q
  ```
- [ ] Implement builder with no business-test behavior. Migrate only duplicated complete-lifecycle helpers; keep custom scenario setup local.
- [ ] Run:
  ```bash
  pytest tests/test_harness_fixture.py tests/test_control_plane.py tests/test_convergence_cli.py tests/test_finding_lifecycle.py -q
  ```
- [ ] Commit:
  ```bash
  git add tests/fixtures/harness.py tests/test_harness_fixture.py tests/test_control_plane.py tests/test_convergence_cli.py tests/test_finding_lifecycle.py
  git commit -m "test: share complete harness lifecycle fixture"
  ```

### Task 5: Cross-layer E2E matrix and skills

**Files:**
- Modify: `SKILL.md`
- Modify: `skills/engineering-harness/SKILL.md`
- Modify: `skills/task-contract/SKILL.md`
- Modify: `skills/diagnosability-review/SKILL.md`
- Create: `tests/test_diagnosability_e2e.py`
- Modify: `tests/test_readme_docs.py`

- [ ] Write RED E2E tests for twelve spec matrix cases: Q2 false, Q3 unassessed, bugfix gap false, unlinked fail, linked fail/DEFECT route, mismatch, invalid N/A, out-of-scope Finding, stale review, DIAG closure, ordinary closure, publish failure.
- [ ] Run:
  ```bash
  pytest tests/test_diagnosability_e2e.py tests/test_readme_docs.py -q
  ```
- [ ] Update skills to emit inputs satisfying readiness/transaction rules. Do not add new workflow states or logger behavior.
- [ ] Run same tests; expect PASS.
- [ ] Commit:
  ```bash
  git add SKILL.md skills/ tests/test_diagnosability_e2e.py tests/test_readme_docs.py
  git commit -m "test: cover diagnosability control-plane lifecycle"
  ```

### Task 6: Verification and v0.2.6 release readiness

**Files:**
- Modify only regression defects found by commands below.

- [ ] Run focused suite:
  ```bash
  pytest tests/test_diagnosability.py tests/test_cli_diagnosability.py tests/test_diagnosability_gate.py tests/test_diagnosability_lifecycle.py tests/test_diagnosability_e2e.py tests/test_harness_fixture.py tests/test_workspace.py -q
  ```
- [ ] Run package checks:
  ```bash
  pytest tests/test_init.py tests/test_package_resources.py tests/test_wheel_isolation.py tests/test_npm_package.py -q
  python -m pip wheel . --no-deps
  npm pack --dry-run
  ```
- [ ] Request explicit full-suite authorization before:
  ```bash
  pytest tests/ -q
  ```
- [ ] Run `git diff --check`; inspect only new code for fail-open branches, staging cleanup behavior, consumer handling, and sensitive artifact leakage.
- [ ] Commit only regression repairs; do not create empty commit.

## Plan self-review

- Task 1 covers bugfix Contract source-of-truth.
- Task 2 covers P0 Gate false-pass and semantic linkage.
- Task 3 covers transactional persistence and staging scope.
- Task 4 removes fixture-policy drift.
- Task 5 proves skill/CLI/Gate lifecycle matrix.
- Task 6 proves focused/package/full regression under explicit authorization.

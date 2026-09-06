# v0.2.7 Correctness Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close remaining v0.2.7 schema-separation, Gate-assessment, and task-scope projection gaps without relaxing fail-closed behavior.

**Architecture:** Add a canonical finding-schema resolver in `quality_gate`, preserving `validate_schema` as primitive. Introduce immutable `GateAssessment` from one side-effect-free evaluator and make persistence explicit. Centralize task-owned scope projection in `workspace`; review commands consume it while workspace snapshots remain only freshness facts.

**Tech Stack:** Python 3.11, PyYAML, jsonschema, pytest.

**Spec:** `docs/Superpowers-Engineering-Harness-v0.2.7-实施规格.md`

## Global Constraints

- Preserve fail-closed schema validation, evidence freshness, Git binding, and Finding lifecycle.
- Do not include protected user workspace paths in task review scope without explicit adoption.
- Do not add dependencies or modify business-project code.
- Keep `harness gate preflight` side-effect free.
- Run focused tests only; full suite requires explicit authorization.

---

### Task 1: Canonical Finding Schema Resolver

**Files:**
- Create: `src/harness/schemas/adversarial-finding.schema.json`
- Create: `src/harness/schemas/complexity-finding.schema.json`
- Modify: `src/harness/schemas/diagnosability-finding.schema.json`
- Modify: `src/harness/quality_gate.py:validate_schema,load_findings`
- Modify: `tests/test_finding_schema.py`
- Modify: `tests/test_quality_gate.py`

**Interfaces:**
- Produces: `finding_schema_name(finding: dict) -> str` in `harness.quality_gate`.
- Consumes: `validate_schema(document: object, schema_name: str, source: Path)`.
- Contract: returns one of `adversarial-finding.schema.json`, `complexity-finding.schema.json`, or `diagnosability-finding.schema.json`; unknown/malformed discriminator raises `InvalidHarnessState` before Gate accepts finding.

- [ ] **Step 1: Write failing resolver tests**

```python
def test_load_findings_uses_schema_selected_by_category(tmp_path):
    finding = {"id": "FND-001", "kind": "failure_scenario", "target": "REQ-001", "scenario": "x", "severity": "major", "status": "PROPOSED"}
    (tmp_path / "FND-001.yaml").write_text(yaml.safe_dump(finding))
    assert load_findings(tmp_path) == [finding]


def test_load_findings_rejects_unknown_category(tmp_path):
    finding = {"id": "FND-001", "kind": "failure_scenario", "target": "REQ-001", "scenario": "x", "severity": "major", "status": "PROPOSED", "category": "unknown"}
    (tmp_path / "FND-001.yaml").write_text(yaml.safe_dump(finding))
    with pytest.raises(InvalidHarnessState, match="FINDING_SCHEMA_UNKNOWN"):
        load_findings(tmp_path)
```

- [ ] **Step 2: Run failing tests**

Run: `pytest tests/test_finding_schema.py tests/test_quality_gate.py -q`

Expected: FAIL because canonical schemas/resolver do not exist.

- [ ] **Step 3: Create discriminated schemas and resolver**

```python
def finding_schema_name(finding: dict) -> str:
    if finding.get("category") == "diagnosability":
        return "diagnosability-finding.schema.json"
    if finding.get("kind") in {"failure_scenario", "requirement_violation", "invariant_violation"}:
        return "adversarial-finding.schema.json"
    if finding.get("category") == "complexity":
        return "complexity-finding.schema.json"
    raise InvalidHarnessState("FINDING_SCHEMA_UNKNOWN")


def load_findings(findings_dir: Path) -> list[dict]:
    findings = []
    for path in sorted(findings_dir.glob("*.yaml")):
        finding = yaml.safe_load(path.read_text())
        if not isinstance(finding, dict):
            raise InvalidHarnessState(f"{path} is not a mapping")
        validate_schema(finding, finding_schema_name(finding), path)
        findings.append(finding)
    return findings
```

Move each existing umbrella branch into exactly one schema. Do not validate canonical persisted findings with `finding.schema.json`.

- [ ] **Step 4: Run focused schema tests**

Run: `pytest tests/test_finding_schema.py tests/test_quality_gate.py -q`

Expected: PASS.

### Task 2: Shared Task-owned Scope Projection

**Files:**
- Modify: `src/harness/workspace.py:ReviewScope,review_scope`
- Modify: `src/harness/controlplane.py:cmd_impact,cmd_review_complexity`
- Modify: `src/harness/diagnosability.py:write_review`
- Modify: `tests/test_impact_control_plane.py`
- Modify: `tests/test_cli_complexity.py`
- Modify: `tests/test_cli_diagnosability.py`

**Interfaces:**
- Produces: `project_task_scope(task: dict, impact: dict, inspected_paths: Iterable[str] = (), direct_dependencies: Iterable[str] = ()) -> tuple[str, ...]` in `harness.workspace`.
- Consumes: `task["scope"]["owned_paths"]`, `task["scope"]["protected_user_paths"]`, `impact["contracts"]`, `impact["direct_dependents"]`.
- Contract: effective scope equals owned paths plus contracts, declared dependencies, inspected paths, minus protected paths; `adopt-path` adds ownership and removes protection; `ignore-user-path` removes ownership and adds protection.

- [ ] **Step 1: Write failing scope tests**

```python
def test_ignore_user_path_removes_owned_path(tmp_path):
    setup(tmp_path)
    assert cli(tmp_path, "impact", "add-change", "src/x.py").returncode == 0
    assert cli(tmp_path, "impact", "ignore-user-path", "src/x.py").returncode == 0
    scope = yaml.safe_load(cli(tmp_path, "impact", "scope", "--format", "yaml").stdout)
    assert "src/x.py" not in scope["owned_paths"]
    assert "src/x.py" not in scope["effective_scope"]


def test_scope_includes_inspected_paths_and_excludes_protected_paths():
    assert project_task_scope(task, impact, inspected_paths=["src/contract.py"]) == ("src/contract.py", "src/owned.py")
```

- [ ] **Step 2: Run failing scope tests**

Run: `pytest tests/test_impact_control_plane.py tests/test_cli_complexity.py tests/test_cli_diagnosability.py -q`

Expected: FAIL because no shared projection exists and ignore does not revoke ownership.

- [ ] **Step 3: Implement projection and route all consumers through it**

```python
def project_task_scope(task, impact, *, inspected_paths=(), direct_dependencies=()):
    scope = task.get("scope", {})
    included = set(scope.get("owned_paths", ()))
    included.update(impact.get("contracts", ()))
    included.update(impact.get("direct_dependents", ()))
    included.update(inspected_paths)
    included.update(direct_dependencies)
    return tuple(sorted(included - set(scope.get("protected_user_paths", ()))))
```

Use this function for `harness impact scope`, complexity review claimed-scope validation, and diagnosability review evidence. Keep `snapshot()` and legacy workspace-diff helper for fingerprint/freshness only.

- [ ] **Step 4: Run focused scope tests**

Run: `pytest tests/test_impact_control_plane.py tests/test_cli_complexity.py tests/test_cli_diagnosability.py -q`

Expected: PASS.

### Task 3: Single Gate Assessment and Current MR Description

**Files:**
- Modify: `src/harness/quality_gate.py:run_gate,write_back`
- Modify: `src/harness/controlplane.py:cmd_transition,cmd_review_outcome,cmd_gate_preflight,cmd_mr_describe,_cmd_gate_convergence`
- Modify: `tests/test_control_plane.py`
- Modify: `tests/test_cli_init.py`
- Modify: `tests/test_quality_gate.py`

**Interfaces:**
- Produces: `GateAssessment(status: str, blockers: list[GateBlocker], quality: dict, release_readiness: dict)` in `harness.quality_gate`.
- Produces: `assess_gate(harness_dir: Path, *, head: str | None = None, allow_preflight: bool = False, allow_converged: bool = False) -> GateAssessment`.
- Compatibility: `run_gate(...) -> tuple[str, list[GateBlocker]]` delegates to `assess_gate`.
- Contract: assessment has no persistence side effect; `write_back(harness_dir, assessment)` is only persistence operation; preflight, GATING admission, gate, and MR description use fresh assessment from same evaluator.

- [ ] **Step 1: Write failing Gate consistency tests**

```python
def test_preflight_does_not_mutate_and_matches_gating_blockers(tmp_path):
    h = make_repo(tmp_path, state="VERIFYING")
    before = (h / "current-task.yaml").read_bytes()
    preflight = run_cli(tmp_path, "gate", "preflight")
    assert preflight.returncode == 1
    assert (h / "current-task.yaml").read_bytes() == before
    gating = run_cli(tmp_path, "transition", "GATING")
    assert blocker_codes(preflight.stdout) == blocker_codes(gating.stderr)


def test_mr_describe_uses_fresh_assessment_not_stale_gate(tmp_path):
    h = make_repo(tmp_path, state="GATING")
    stale = yaml.safe_load((h / "current-task.yaml").read_text())
    stale["gate"] = {"status": "PASS", "quality": {"status": "PASS"}, "release_readiness": {"status": "READY", "reasons": []}}
    (h / "current-task.yaml").write_text(yaml.safe_dump(stale))
    assert "Quality Gate: BLOCKED" in run_cli(tmp_path, "mr", "describe").stdout
```

- [ ] **Step 2: Run failing Gate tests**

Run: `pytest tests/test_control_plane.py tests/test_cli_init.py tests/test_quality_gate.py -q`

Expected: FAIL because MR description reads stored Gate data and entry points do not expose one assessment object.

- [ ] **Step 3: Implement immutable assessment and explicit persistence**

```python
@dataclass(frozen=True)
class GateAssessment:
    status: str
    blockers: tuple[GateBlocker, ...]
    quality: dict[str, object]
    release_readiness: dict[str, object]


def assess_gate(harness_dir: Path, **options) -> GateAssessment:
    status, blockers = _evaluate_gate_requirements(harness_dir, **options)
    readiness = _release_readiness(harness_dir, status)
    return GateAssessment(status, tuple(blockers), {"status": "PASS" if status == "PASS" else "BLOCKED"}, readiness)
```

Move existing `run_gate` evaluation body into `_evaluate_gate_requirements`. Make all CLI entry points render this object. Keep state transitions and convergence rules unchanged; only `write_back` may store assessment fields.

- [ ] **Step 4: Run focused Gate tests**

Run: `pytest tests/test_control_plane.py tests/test_cli_init.py tests/test_quality_gate.py -q`

Expected: PASS.

### Task 4: Cross-feature Regression and Documentation

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `CHANGELOG.md`
- Test: `tests/test_finding_schema.py`
- Test: `tests/test_impact_control_plane.py`
- Test: `tests/test_control_plane.py`
- Test: `tests/test_cli_init.py`
- Test: `tests/test_quality_gate.py`
- Test: `tests/test_cli_complexity.py`
- Test: `tests/test_cli_diagnosability.py`

**Interfaces:**
- Consumes: canonical schema resolver, task scope projection, and Gate assessment APIs from Tasks 1–3.
- Produces: documented CLI contracts and focused release regression proof.

- [ ] **Step 1: Write documentation assertions before copy changes**

```python
def test_readme_documents_task_owned_scope_and_preflight():
    text = (REPO / "README.md").read_text()
    assert "task-owned" in text
    assert "harness gate preflight" in text
```

- [ ] **Step 2: Run documentation assertion**

Run: `pytest tests/test_readme_docs.py -q`

Expected: FAIL if public contracts are not documented.

- [ ] **Step 3: Update docs with exact contracts**

Document canonical finding schema selection, `ignore-user-path` ownership revocation, and that preflight/MR report fresh assessment without writing task state. Add matching Chinese documentation and changelog entry; do not alter release version.

- [ ] **Step 4: Run focused regression set**

Run: `pytest tests/test_finding_schema.py tests/test_impact_control_plane.py tests/test_control_plane.py tests/test_cli_init.py tests/test_quality_gate.py tests/test_cli_complexity.py tests/test_cli_diagnosability.py tests/test_readme_docs.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness tests README.md README.zh-CN.md CHANGELOG.md
git commit -m "fix: close v0.2.7 control plane gaps"
```

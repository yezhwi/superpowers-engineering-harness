# Control-plane integrity repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Harness review, ownership, Gate, and evidence artifacts lifecycle-safe, scope-correct, and fail-closed.

**Architecture:** Reuse canonical `transaction.stage`/`publish`, schema validation, and `workspace.project_task_scope`. Normalize state at control-plane mutation boundaries; recompute Gate admission from canonical artifacts rather than task projection. Preserve existing public CLI success behavior while returning controlled invalid-state failures.

**Tech Stack:** Python 3.11, PyYAML, jsonschema, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-04-control-plane-integrity-repair-design.md`

## Global Constraints

- Follow accepted `DEC-009`: targeted reuse; no module split or dependency.
- Preserve DEC-004/DEC-008 trusted-local shell boundary and CLI-only execution.
- New external CLI-contract behavior needs declared Interface Contract before source implementation.
- Do not modify protected untracked user documents.
- Do not commit without persisted Harness commit authorization.

---

### Task 1: Declare CLI contract and add impact ownership

**Files:**
- Create: `.harness/interface-contracts/INT-002.yaml`
- Modify: `.harness/impact.yaml`
- Test: `tests/test_cli_interface.py`

**Interfaces:**
- Consumes: accepted `DEC-009`, `.harness/observability.yaml`.
- Produces: external CLI contract `INT-002`, classified as compatible, referenced by later review/evidence work.

- [ ] **Step 1: Declare failing/required public CLI contract before code changes**

Create declaration input with contract semantics:

```yaml
name: control-plane-validation-cli
kind: cli
visibility: external
consumers: [local-harness-operator, automation]
inputs:
  description: Persisted Harness artifacts and existing CLI command arguments.
outputs:
  description: Existing successful command output; invalid persisted state returns controlled exit code 2.
errors:
  description: Invalid artifact and preflight states use stable invalid-state output, never traceback.
compatibility:
  classification: compatible
  rationale: Success commands and flags remain unchanged; only malformed-state behavior becomes deterministic.
  migration: null
versioning: {required: false, strategy: null}
observability: {contract: .harness/observability.yaml}
decision_refs: [DEC-009]
verification: []
```

- [ ] **Step 2: Run declaration and classify impact**

Run:

```bash
harness interface declare --name control-plane-validation-cli --kind cli --consumer local-harness-operator --consumer automation --input 'Persisted Harness artifacts and existing CLI command arguments.' --output 'Existing success output; invalid state returns controlled exit code 2.' --error 'Invalid artifact and preflight state use stable invalid-state output, never traceback.' --compatibility compatible --rationale 'Success commands and flags remain unchanged; malformed-state behavior becomes deterministic.' --decision-ref DEC-009
harness impact add-interface HARNESS-CLI-VALIDATION --kind cli --visibility external --consumer local-harness-operator --consumer automation --compatibility compatible --contract-id INT-002
```

Expected: `INT-002` is `DECLARED`; impact lists compatible external CLI contract.

- [ ] **Step 3: Add contract declaration regression test**

Add test asserting interface declaration remains external/compatible and is accepted by Gate contract loading.

```python
assert contract["kind"] == "cli"
assert contract["visibility"] == "external"
assert contract["compatibility"]["classification"] == "compatible"
```

- [ ] **Step 4: Run focused test**

Run: `pytest tests/test_cli_interface.py -q`
Expected: PASS.

### Task 2: Repair Interface Finding lifecycle and atomic review publication

**Files:**
- Modify: `src/harness/schemas/interface-finding.schema.json`
- Modify: `src/harness/interface_review.py`
- Test: `tests/test_interface_review.py`
- Test: `tests/test_finding_transition.py`

**Interfaces:**
- Consumes: `transaction.StagedArtifact`, `stage`, `publish`; canonical Finding states.
- Produces: `write_review()` atomically emits deduplicated `interface` findings and `evidence/interface-review.json`.

- [ ] **Step 1: Write failing lifecycle and retry tests**

Add tests covering closed Interface Finding validation, duplicate proposal reuse, and injected `publish` failure.

```python
finding["status"] = "CLOSED"
validate_schema(finding, "interface-finding.schema.json", path)
assert list((harness / "findings").glob("FND-*.yaml")) == []
assert not (harness / "evidence" / "interface-review.json").exists()
```

- [ ] **Step 2: Run tests red**

Run: `pytest tests/test_interface_review.py tests/test_finding_transition.py -q`
Expected: FAIL because Interface schema only permits `PROPOSED` and review writes targets directly.

- [ ] **Step 3: Implement minimum canonical publication**

Change schema status to canonical lifecycle enum. In `write_review`, load/validate existing Findings, compare interface category plus target/scenario/severity/location, allocate IDs only for unmatched proposals, construct `StagedArtifact` records, then publish Findings and replacement review evidence together.

```python
artifacts = [StagedArtifact(f"findings/{item['id']}.yaml", yaml.safe_dump(item, sort_keys=False).encode()) for item in generated]
artifacts.append(StagedArtifact("evidence/interface-review.json", json.dumps(record, indent=2).encode(), replace=True))
publish(harness_dir, stage(harness_dir, artifacts), replace_paths=frozenset({"evidence/interface-review.json"}))
```

- [ ] **Step 4: Run focused tests green**

Run: `pytest tests/test_interface_review.py tests/test_finding_transition.py -q`
Expected: PASS.

### Task 3: Make ownership monotonic and scope-safe

**Files:**
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/workspace.py`
- Test: `tests/test_impact_control_plane.py`
- Test: `tests/test_workspace.py`

**Interfaces:**
- Consumes: `scope.owned_paths`, `scope.protected_user_paths`, `impact` fields.
- Produces: owned paths cannot disappear through ignore command; effective task scope includes owned and contract paths.

- [ ] **Step 1: Write failing sequence tests**

```python
cli(tmp_path, "impact", "add-change", "src/x.py")
assert "src/x.py" not in task["scope"]["protected_user_paths"]
cli(tmp_path, "impact", "ignore-user-path", "src/x.py")
assert "src/x.py" in task["scope"]["owned_paths"]
assert "src/x.py" in project_task_scope(task, impact)
```

- [ ] **Step 2: Run red**

Run: `pytest tests/test_impact_control_plane.py tests/test_workspace.py -q`
Expected: FAIL on add-change/protected overlap and ownership removal.

- [ ] **Step 3: Implement set normalization**

`add-change` and `adopt-path` append ownership then remove protected membership. `ignore-user-path` adds protection only when path is not owned. Make `project_task_scope` subtract protected paths only from non-owned auxiliary additions.

```python
owned = set(scope.get("owned_paths") or ())
auxiliary = contracts | dependents | inspected | direct_dependencies
return tuple(sorted(owned | (auxiliary - protected)))
```

- [ ] **Step 4: Run green**

Run: `pytest tests/test_impact_control_plane.py tests/test_workspace.py -q`
Expected: PASS.

### Task 4: Fail-close malformed artifacts and stale scope-bound reviews

**Files:**
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/diagnosability.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_quality_gate.py`
- Test: `tests/test_diagnosability_gate.py`
- Test: `tests/test_review_outcome.py`

**Interfaces:**
- Consumes: canonical Finding YAML, current `project_task_scope`, review evidence.
- Produces: `InvalidHarnessState` / documented CLI exit 2; stale scope review blocks Gate.

- [ ] **Step 1: Add red tests for malformed YAML, non-mapping Finding, changed scope, and review preflight**

```python
(finding_dir / "FND-001.yaml").write_text("[not-a-mapping]")
with pytest.raises(InvalidHarnessState, match="not a mapping"):
    load_findings(finding_dir)
assert cli(repo, "review", "outcome", "PASS", "--reason-code", "REVIEW_CLEAN").returncode == 2
```

- [ ] **Step 2: Run red**

Run: `pytest tests/test_quality_gate.py tests/test_diagnosability_gate.py tests/test_review_outcome.py -q`
Expected: FAIL with parser traceback or stale review accepted.

- [ ] **Step 3: Implement controlled validation and current-scope comparison**

Wrap Finding YAML loads in `yaml.YAMLError -> InvalidHarnessState`. In diagnosability Gate blockers, load impact and recompute `project_task_scope` using contract inspected paths/direct dependencies; reject recorded `review_scope.files` mismatch. Catch `quality_gate.InvalidHarnessState` in `cmd_review_outcome` and emit documented preflight failure exit.

- [ ] **Step 4: Run green**

Run: `pytest tests/test_quality_gate.py tests/test_diagnosability_gate.py tests/test_review_outcome.py -q`
Expected: PASS.

### Task 5: Recompute canonical Gate/status and preserve dual-axis output

**Files:**
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/harness_status.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_quality_gate.py`
- Test: `tests/test_status_projection.py`
- Test: `tests/test_control_plane.py`

**Interfaces:**
- Consumes: canonical findings/evidence and `GateAssessment`.
- Produces: no stale cached PASS acceptance; `quality` and `release_readiness` survive BLOCKED; `READY: yes` requires READY readiness.

- [ ] **Step 1: Add red tests**

```python
(harness / "findings" / "FND-001.yaml").write_text(yaml.safe_dump(interface_finding))
task["gate"] = {"status": "PASS"}
assert status_main(["--harness-dir", str(harness)]) == 2
assert "READY: yes" not in preflight_output_for_draft_only
assert blocked_task["gate"]["quality"]["status"] == "BLOCKED"
```

- [ ] **Step 2: Run red**

Run: `pytest tests/test_quality_gate.py tests/test_status_projection.py tests/test_control_plane.py -q`
Expected: FAIL because cached projection is accepted, Ready output ignores readiness, or blocked transition replaces axes.

- [ ] **Step 3: Implement projection repair**

Have status load canonical Findings and assess current Gate before validating DONE. Use `quality_gate.write_back`-equivalent dual-axis shape in convergence BLOCKED/ESCALATED transitions. In preflight print affirmative readiness only when both quality PASS and readiness READY.

```python
ready = status == "PASS" and assessment.release_readiness["status"] == "READY"
print("READY: yes" if ready else "READY: no")
```

- [ ] **Step 4: Run green**

Run: `pytest tests/test_quality_gate.py tests/test_status_projection.py tests/test_control_plane.py -q`
Expected: PASS.

### Task 6: Validate attach provenance and freeze/resolve identities

**Files:**
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/paths.py`
- Modify: `src/harness/schemas/task.schema.json`
- Test: `tests/test_cli_evidence_reuse.py`
- Test: `tests/test_paths.py`
- Test: `tests/test_task_new.py`

**Interfaces:**
- Consumes: external evidence result JSON, Git facts, evidence references.
- Produces: attach only persists schema-valid current-head evidence; task has immutable Git identity; consumers use resolver.

- [ ] **Step 1: Add red tests**

```python
result["exit_code"] = 0
result["command"] = "false"
assert cli(repo, "evidence", "attach", ...).returncode == 2
assert task["git"]["base_ref"] == "main"
assert task["git"]["head_at_start"] == task["git"]["head"]
```

- [ ] **Step 2: Run red**

Run: `pytest tests/test_cli_evidence_reuse.py tests/test_paths.py tests/test_task_new.py -q`
Expected: FAIL because attach accepts inconsistent provenance or task omits frozen identity.

- [ ] **Step 3: Implement minimum validation**

Validate normalized attach record against `evidence.schema.json` and `validate_evidence` using current head/workspace before `atomic_write`; reject result identity/exit inconsistencies. Persist `base_ref` and `head_at_start` at classification, update task schema, and route consumers accepting evidence references through `evidence_path`.

- [ ] **Step 4: Run green**

Run: `pytest tests/test_cli_evidence_reuse.py tests/test_paths.py tests/test_task_new.py -q`
Expected: PASS.

### Task 7: Verify interface contract and run integration regression

**Files:**
- Modify: `.harness/interface-contracts/INT-002.yaml`
- Test: all tests touched above

**Interfaces:**
- Consumes: fresh focused test evidence.
- Produces: `INT-002.verification` references fresh interface/CLI contract evidence.

- [ ] **Step 1: Format changed Python files**

Run: `ruff format src/harness tests`
Expected: formatter modifies only tracked source/tests.

- [ ] **Step 2: Run focused regression groups**

Run:

```bash
pytest tests/test_interface_review.py tests/test_finding_transition.py tests/test_impact_control_plane.py tests/test_workspace.py tests/test_quality_gate.py tests/test_diagnosability_gate.py tests/test_review_outcome.py tests/test_status_projection.py tests/test_control_plane.py tests/test_cli_evidence_reuse.py tests/test_paths.py tests/test_task_new.py -q
```

Expected: PASS.

- [ ] **Step 3: Persist contract verification reference**

Use `harness evidence` for focused test command, then:

```bash
harness interface verify INT-002 --evidence unit-test
```

Expected: contract contains canonical verification reference.

- [ ] **Step 4: Do not commit**

Commit authorization is absent. Leave changes uncommitted and report exact verification output.

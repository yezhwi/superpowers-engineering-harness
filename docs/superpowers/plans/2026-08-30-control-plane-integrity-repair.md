# Control-Plane Integrity Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Harness Gate, CLI, artifact lifecycle, risk matching, Skills, and docs agree on one fail-closed control-plane contract.

**Architecture:** Add focused helpers for Harness-root and artifact-reference validation, then split command ownership from `controlplane.py` by lifecycle concern. Gate owns category-specific proof policy and validated risk/config admission. Artifact writers stage complete sets before publishing; CLI only parses, resolves root, and delegates.

**Tech Stack:** Python 3.11+, pytest, PyYAML, jsonschema, pathlib, packaged JSON schemas.

**Spec:** `docs/superpowers/specs/2026-08-30-control-plane-integrity-repair-design.md`

## Global Constraints

- Preserve existing public CLI command names except documented decision-contract corrections.
- Python 3.11 supports recursive path policy through project helper, not `PurePosixPath.match("**")`.
- All new production behavior begins with focused RED test.
- No evidence reference may leave `<harness>/evidence`.
- No direct `.harness` CWD dependency outside centralized root resolver.

---

### Task 1: Canonical Harness paths and artifact references

**Files:**
- Create: `src/harness/paths.py`
- Modify: `src/harness/cli.py`, `src/harness/controlplane.py`, `src/harness/quality_gate.py`
- Test: `tests/test_paths.py`, `tests/test_control_plane.py`

**Interfaces:**
- Produces `resolve_harness_dir(value: str | Path = ".harness") -> Path` and `evidence_path(harness_dir: Path, reference: str) -> Path`.
- `evidence_path` accepts only a nonempty filename ending in `.json` or normalizes an extensionless filename; rejects absolute, `..`, and separator-containing references with `ValueError("EVIDENCE_REFERENCE_INVALID")`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("reference", ["/tmp/proof.json", "../history/x.json", "nested/x.json"])
def test_evidence_path_rejects_references_outside_canonical_directory(reference):
    with pytest.raises(ValueError, match="EVIDENCE_REFERENCE_INVALID"):
        evidence_path(tmp_path / ".harness", reference)

def test_status_uses_explicit_harness_directory(repo):
    result = run_cli(repo, "status", "--harness-dir", str(repo / ".harness"))
    assert result.returncode == 0
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_paths.py tests/test_control_plane.py -q`

Expected: FAIL because helpers and CLI path propagation do not exist.

- [ ] **Step 3: Implement minimal helpers and inject resolved root**

```python
def evidence_path(harness_dir: Path, reference: str) -> Path:
    candidate = Path(reference)
    if candidate.is_absolute() or len(candidate.parts) != 1 or candidate.name in {"", ".", ".."}:
        raise ValueError("EVIDENCE_REFERENCE_INVALID")
    return harness_dir / "evidence" / candidate.with_suffix(".json")
```

Pass one resolved root from CLI into all command handlers; remove command-local `Path(".harness")` construction.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_paths.py tests/test_control_plane.py tests/test_cli_task_recovery.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/paths.py src/harness/cli.py src/harness/controlplane.py src/harness/quality_gate.py tests/test_paths.py tests/test_control_plane.py
git commit -m "fix: constrain harness artifact paths"
```

### Task 2: Gate category, risk, and configuration integrity

**Files:**
- Create: `src/harness/schemas/gate.schema.json`
- Modify: `src/harness/quality_gate.py`, `src/harness/schemas/task.schema.json`, `src/harness/templates/gate.yaml`
- Test: `tests/test_quality_gate.py`, `tests/test_diagnosability_gate.py`, `tests/test_finding_lifecycle.py`

**Interfaces:**
- `run_gate` validates gate schema and risk pair before policy selection.
- Ordinary Finding proof policy remains unchanged. DIAG policy uses `validate_compliance_closure` only for `VERIFIED`/`CLOSED` and never requires `regression_test`.

- [ ] **Step 1: Write failing tests**

```python
def test_confirmed_diagnosability_finding_blocks_without_key_error(harness):
    finding = diagnosability_finding(status="CONFIRMED")
    write_finding(harness, finding)
    status, blockers = run_gate(harness)
    assert status == "BLOCKED"
    assert any(item.code == "FINDING_OPEN" for item in blockers)

def test_gate_rejects_q3_fast_risk_pair(harness):
    set_risk(harness, level="Q3", profile="FAST")
    with pytest.raises(InvalidHarnessState, match="RISK_PROFILE_INVALID"):
        run_gate(harness)

def test_gate_rejects_unknown_configuration_key(harness):
    write_gate(harness, {"gate": {"findings": {"critical_allowed": 999}}})
    with pytest.raises(InvalidHarnessState):
        run_gate(harness)
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_quality_gate.py tests/test_diagnosability_gate.py tests/test_finding_lifecycle.py -q`

Expected: DIAG raises `KeyError`; incompatible risk and unconstrained gate config are accepted.

- [ ] **Step 3: Implement category and config dispatch**

Validate `gate.yaml` against packaged schema. Require `{Q1: FAST, Q2: STANDARD, Q3: STRICT}`. Before generic proof loop, branch DIAG findings; call `validate_compliance_closure` only terminal DIAG states. Exclude DIAG from ordinary confirmed-test debt. Thread `must_match_head` into evidence validation rather than computing it unused.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_quality_gate.py tests/test_diagnosability_gate.py tests/test_finding_lifecycle.py tests/test_finding_schema.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/quality_gate.py src/harness/schemas/gate.schema.json src/harness/schemas/task.schema.json src/harness/templates/gate.yaml tests/test_quality_gate.py tests/test_diagnosability_gate.py tests/test_finding_lifecycle.py
git commit -m "fix: enforce gate proof and risk integrity"
```

### Task 3: FAST boundary matching

**Files:**
- Modify: `src/harness/risk_boundaries.py`
- Test: `tests/test_risk_boundaries.py`

**Interfaces:**
- Produces `matches_boundary(path: str, pattern: str) -> bool`, anchored to repository-relative path.
- `**` matches zero or more full path segments; no right-side-only matching.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("path", ["src/api.py", "src/a/b.py", "src/a/b/c.py"])
def test_recursive_boundary_matches_all_nested_source_paths(path):
    assert matches_boundary(path, "src/**")

def test_boundary_does_not_right_match_unrelated_prefix():
    assert not matches_boundary("src/auth/login.py", "auth/**")
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_risk_boundaries.py -q`

Expected: nested and anchored cases fail with `PurePosixPath.match`.

- [ ] **Step 3: Implement segment matcher**

Split normalized POSIX paths/patterns on `/`; recursively consume `**`, and use `fnmatchcase` only per non-`**` segment. Reject absolute or parent-traversal policy entries in `load_boundaries`.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_risk_boundaries.py tests/test_quality_gate.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/risk_boundaries.py tests/test_risk_boundaries.py
git commit -m "fix: recursively match fast risk boundaries"
```

### Task 4: Lifecycle routing and atomic artifact replacement

**Files:**
- Create: `src/harness/task_commands.py`, `src/harness/finding_commands.py`, `src/harness/impact_commands.py`
- Modify: `src/harness/controlplane.py`, `src/harness/transaction.py`, `src/harness/complexity.py`
- Test: `tests/test_cli_task_recovery.py`, `tests/test_task_new.py`, `tests/test_complexity_review.py`, `tests/test_finding_transition.py`

**Interfaces:**
- Generic transition rejects every `BLOCKED -> *` target with `RESUME_REQUIRED`.
- `replace_task` archives and resets `impact.yaml`, requirements, invariants, gate, observability, findings, and evidence in one published transaction.
- `write_complexity_review` stages all `CPLX-*` files plus review evidence before publication.

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize("target", ["IMPLEMENTING", "VERIFYING", "REPRODUCING", "ESCALATED"])
def test_generic_transition_cannot_leave_blocked(repo, target):
    set_task_state(repo, "BLOCKED")
    assert run_cli(repo, "transition", target).returncode == 1

def test_task_replacement_resets_and_archives_impact(repo):
    write_impact(repo, required_tests=["tests/old.py"])
    finish_task(repo)
    run_cli(repo, "task", "new", "TASK-999")
    assert archived_impact(repo)["impact"]["required_tests"] == ["tests/old.py"]
    assert current_impact(repo)["impact"]["required_tests"] == []

def test_complexity_write_failure_leaves_no_finding_or_evidence(harness):
    with pytest.raises(ValidationError):
        write_complexity_review(harness, review_with_valid_then_invalid_finding())
    assert not list((harness / "findings").glob("CPLX-*.yaml"))
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_cli_task_recovery.py tests/test_task_new.py tests/test_complexity_review.py -q`

Expected: blocked bypass succeeds; impact leaks; first complexity finding persists.

- [ ] **Step 3: Implement focused command modules and transaction publication**

Move existing task, finding, and impact handlers without behavior changes except planned integrity rules. Use one unique temporary staging directory under `.harness`; validate all copies/templates before `publish`. Use `tempfile.NamedTemporaryFile(dir=path.parent, delete=False)` for individual atomic writes.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_cli_task_recovery.py tests/test_task_new.py tests/test_complexity_review.py tests/test_finding_transition.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/task_commands.py src/harness/finding_commands.py src/harness/impact_commands.py src/harness/controlplane.py src/harness/transaction.py src/harness/complexity.py tests/test_cli_task_recovery.py tests/test_task_new.py tests/test_complexity_review.py tests/test_finding_transition.py
git commit -m "fix: make control-plane lifecycle publication atomic"
```

### Task 5: Evidence execution identity and bounded collection

**Files:**
- Modify: `src/harness/collect_evidence.py`, `src/harness/evidence_validator.py`, `src/harness/schemas/evidence.schema.json`
- Test: `tests/test_evidence.py`, `tests/test_evidence_validator.py`, `tests/test_cli_evidence_reuse.py`

**Interfaces:**
- Evidence records include command-derived pytest node IDs when command is pytest.
- For pytest evidence, declared `covered_tests` must be exact executed node IDs; a timeout produces failed evidence with deterministic `EVIDENCE_COMMAND_TIMEOUT` diagnostic.

- [ ] **Step 1: Write failing tests**

```python
def test_pytest_evidence_rejects_declared_node_not_executed(tmp_path):
    result = collect(["--type", "unit_test", "--covered-test", "tests/test_x.py::test_y", "--command", "pytest tests/test_other.py"])
    assert result == 2

def test_evidence_command_timeout_is_recorded(tmp_path):
    result = collect(["--type", "unit_test", "--command", "python -c 'import time; time.sleep(99)'"])
    assert result == 1
    assert read_record(tmp_path)["error"] == "EVIDENCE_COMMAND_TIMEOUT"
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_evidence.py tests/test_evidence_validator.py tests/test_cli_evidence_reuse.py -q`

Expected: declared coverage is accepted and no timeout policy exists.

- [ ] **Step 3: Implement bounded subprocess and pytest identity validation**

Call `subprocess.run(..., timeout=DEFAULT_TIMEOUT_SECONDS)`; map `TimeoutExpired` to deterministic failed record. Parse pytest command node arguments with `shlex.split`; only accept declared tests when each is an exact command node or file selector. Preserve generic-command behavior and explicit evidence scope.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_evidence.py tests/test_evidence_validator.py tests/test_cli_evidence_reuse.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/collect_evidence.py src/harness/evidence_validator.py src/harness/schemas/evidence.schema.json tests/test_evidence.py tests/test_evidence_validator.py tests/test_cli_evidence_reuse.py
git commit -m "fix: bind evidence coverage to executed tests"
```

### Task 6: Skills, docs, package isolation, and repository hygiene

**Files:**
- Modify: `SKILL.md`, `skills/quality-gate/SKILL.md`, `skills/convergence/SKILL.md`, `skills/task-contract/SKILL.md`, `skills/diagnosability-review/SKILL.md`, `README.md`, `README.zh-CN.md`, `docs/worked-example.md`, `src/harness/controlplane.py`, `src/harness/__init__.py`, `.gitignore`
- Delete from index: tracked `.harness/**` runtime artifacts
- Test: `tests/test_readme_docs.py`, `tests/test_wheel_isolation.py`, `tests/test_version_consistency.py`

**Interfaces:**
- Skills use `DECISION:` and persisted state for Gate routing; no workflow invokes deprecated converge.
- Task-contract begins at `CLASSIFIED -> SPECIFYING`; DIAG review runs at `REVIEWING`.
- Wheel test creates virtualenv without system packages.

- [ ] **Step 1: Write failing documentation and isolation tests**

```python
def test_operational_docs_do_not_describe_gate_exit_as_pass_signal():
    assert "exit 0=PASS" not in operational_skill_text()

def test_wheel_installation_does_not_use_system_site_packages():
    assert "system_site_packages=True" not in Path("tests/test_wheel_isolation.py").read_text()
```

- [ ] **Step 2: Run RED tests**

Run: `pytest tests/test_readme_docs.py tests/test_wheel_isolation.py tests/test_version_consistency.py -q`

Expected: stale workflow assertions fail.

- [ ] **Step 3: Synchronize generated/public workflow text**

Use `src/harness` source wording; instruct `harness gate`, inspect `DECISION:`/`harness status`, and use `resume` only after `CONTINUE`. Remove direct state-file edits and deprecated converge from all workflows. Update module docstring. Document CLI as public interface. Remove tracked `.harness` operational files with `git rm --cached` while preserving local ignored worktree state.

- [ ] **Step 4: Run GREEN tests**

Run: `pytest tests/test_readme_docs.py tests/test_wheel_isolation.py tests/test_version_consistency.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add SKILL.md skills README.md README.zh-CN.md docs/worked-example.md src/harness/__init__.py src/harness/controlplane.py .gitignore tests/test_readme_docs.py tests/test_wheel_isolation.py tests/test_version_consistency.py
git rm --cached -r .harness
git commit -m "docs: align harness control-plane workflow"
```

### Task 7: End-to-end regression and review

**Files:**
- Test: full `tests/`

- [ ] **Step 1: Run focused integration suite**

Run: `pytest tests/test_quality_gate.py tests/test_diagnosability_gate.py tests/test_risk_boundaries.py tests/test_cli_task_recovery.py tests/test_task_new.py tests/test_complexity_review.py tests/test_evidence.py tests/test_readme_docs.py -q`

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run: `pytest -q`

Expected: PASS with no new warnings.

- [ ] **Step 3: Inspect diff**

Run: `git diff --check && git diff --stat`

Expected: no whitespace error; diff limited to planned modules, tests, docs, and ignored Harness runtime cleanup.

- [ ] **Step 4: Commit verification artifact**

```bash
git add -A
git commit -m "test: verify control-plane integrity repairs"
```

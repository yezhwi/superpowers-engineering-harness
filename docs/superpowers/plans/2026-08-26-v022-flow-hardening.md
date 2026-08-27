# v0.2.2 Flow Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make recovery reason-driven, expose current Evidence validity before Gate, and compute complexity review scope from repository state.

**Architecture:** Add shared workspace snapshots and Evidence projection; Gate emits typed blockers; control-plane-only commands route blocked and review states. Preserve existing schemas, proof validation, Finding lifecycle, and generic transitions except new guarded edges.

**Tech Stack:** Python 3.11+, stdlib `subprocess`/`dataclasses`, PyYAML, jsonschema, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-v022-flow-hardening-design.md`

## Global Constraints

- Keep `CONVERGED -> DONE` as sole completion path.
- Keep stale/failed Evidence and malformed Harness data fail-closed.
- Keep RED/GREEN Finding proof identity and full-regression policy unchanged.
- Do not add plugin system, UI, database, workflow engine, CLI framework, or review agent.
- Reuse one `.harness/**` ignore policy for evidence, status, Gate, and complexity scope.
- `harness status` must be read-only; full suite remains explicitly authorized.
- Preserve `covered_tests`; do not implement v0.3 requirement traceability.

---

### Task 1: Shared workspace snapshot and review scope

**Files:**
- Create: `src/harness/workspace.py`
- Modify: `src/harness/collect_evidence.py`
- Modify: `src/harness/complexity.py`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/controlplane.py`
- Create: `tests/test_workspace.py`
- Modify: `tests/evidence_factory.py`

**Interfaces:**
- Produces `WorkspaceSnapshot(head: str, fingerprint: str, changed_paths: tuple[str, ...])`.
- Produces `ReviewScope(base_ref, base_commit, head_commit, workspace, files)`.
- Produces `snapshot(repo_root: Path | None = None) -> WorkspaceSnapshot` and `review_scope(base_ref: str, repo_root: Path | None = None) -> ReviewScope`.
- Consumers replace imports of `collect_evidence.git_head` and `workspace_fingerprint` with workspace API or compatibility delegates.

- [ ] **Step 1: Write failing workspace tests**

```python
def test_dirty_and_untracked_business_files_are_in_snapshot(tmp_path):
    repo = committed_repo(tmp_path)
    (repo / "tracked.py").write_text("changed\n")
    (repo / "new.py").write_text("new\n")
    state = snapshot(repo)
    assert state.changed_paths == ("new.py", "tracked.py")
    assert state.fingerprint.startswith("sha256:")


def test_base_equal_head_keeps_dirty_files_in_review_scope(tmp_path):
    repo = committed_repo(tmp_path)
    (repo / "service.py").write_text("change\n")
    scope = review_scope("HEAD", repo)
    assert scope.base_commit == scope.head_commit
    assert scope.files == ("service.py",)
```

Also cover committed delta, staged-only delta, `.harness/` exclusion, deterministic sorted paths, and invalid base ref.

- [ ] **Step 2: Run focused tests RED**

Run: `python -m pytest tests/test_workspace.py -q`

Expected: FAIL because `harness.workspace` does not exist.

- [ ] **Step 3: Implement minimal snapshot API**

```python
@dataclass(frozen=True)
class WorkspaceSnapshot:
    head: str
    fingerprint: str
    changed_paths: tuple[str, ...]


def snapshot(repo_root: Path | None = None) -> WorkspaceSnapshot: ...
def review_scope(base_ref: str, repo_root: Path | None = None) -> ReviewScope: ...
```

Use `git merge-base`, `git diff --name-only`, `git diff --cached --name-only`, and `git ls-files --others --exclude-standard`; union and sort paths; exclude `.harness/**`. Build fingerprint from same effective tracked/untracked business content current collector uses. Keep `collect_evidence.git_head` and `workspace_fingerprint` as delegating compatibility functions.

- [ ] **Step 4: Move existing callers onto snapshot API**

Replace direct local fingerprint/head calculations in collector, complexity metadata, Gate, control-plane verification guards, and test factory. Do not change Evidence JSON field names.

- [ ] **Step 5: Run focused tests GREEN**

Run: `python -m pytest tests/test_workspace.py tests/test_evidence.py tests/test_evidence_validator.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/workspace.py src/harness/collect_evidence.py src/harness/complexity.py src/harness/quality_gate.py src/harness/controlplane.py tests/test_workspace.py tests/evidence_factory.py
git commit -m "feat: centralize workspace snapshots"
```

### Task 2: Shared Evidence status projection

**Files:**
- Modify: `src/harness/evidence_validator.py`
- Modify: `src/harness/quality_gate.py`
- Create: `tests/test_status_projection.py`
- Modify: `tests/test_evidence_validator.py`
- Modify: `tests/test_quality_gate.py`

**Interfaces:**
- Produces `EvidenceStatus` enum: `FRESH`, `STALE`, `MISSING`, `INVALID`, `FAILED`.
- Produces `EvidenceProjection(status, code, record, expected_fingerprint, current_fingerprint, changed_paths)`.
- `project_evidence(path, current_head, workspace, expected_success)` is sole classification API used by status and Gate.
- Existing `validate_evidence(...)` remains public and raises `EvidenceValidationError` from projection code.

- [ ] **Step 1: Write failing projection tests**

```python
@pytest.mark.parametrize(("mutate", "status"), [
    (lambda record: record.update(exit_code=1), EvidenceStatus.FAILED),
    (lambda record: record.update(commit="0" * 40), EvidenceStatus.STALE),
])
def test_projection_classifies_current_evidence(mutate, status):
    record = fresh_record()
    mutate(record)
    assert project_record(record, current_head=HEAD, workspace=SNAPSHOT,
                          expected_success=True).status is status


def test_missing_required_evidence_is_missing(tmp_path):
    assert project_evidence(tmp_path / "build.json", HEAD, SNAPSHOT, True).status is EvidenceStatus.MISSING
```

Add invalid JSON/schema, workspace stale, and successful fresh cases. Add Gate assertion that stale and failed projection codes appear in structured Gate blockers.

- [ ] **Step 2: Run focused tests RED**

Run: `python -m pytest tests/test_status_projection.py tests/test_evidence_validator.py -q`

Expected: FAIL because projection API and enum do not exist.

- [ ] **Step 3: Implement projection without weakening validation**

Use schema parse failures for `INVALID`, missing path for `MISSING`, HEAD/workspace mismatch for `STALE`, current nonzero result for `FAILED`, and current successful record for `FRESH`. Include stable reason code, command, timestamp, exit code, covered tests, and snapshot data in projection. Make `validate_evidence` call projection and preserve its existing error codes.

- [ ] **Step 4: Convert Gate Evidence checks to projection**

For required verification, requirement/invariant evidence, and complexity review, classify through one projection call. Gate only accepts `FRESH`; map other states to stable blocker codes. Keep invalid persisted Harness documents exit code 2 where current policy requires it.

- [ ] **Step 5: Run focused tests GREEN**

Run: `python -m pytest tests/test_status_projection.py tests/test_evidence_validator.py tests/test_quality_gate.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/evidence_validator.py src/harness/quality_gate.py tests/test_status_projection.py tests/test_evidence_validator.py tests/test_quality_gate.py
git commit -m "feat: project evidence freshness status"
```

### Task 3: Typed Gate blockers and deterministic blocked recovery

**Files:**
- Create: `src/harness/blockers.py`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/state_machine.py`
- Modify: `src/harness/schemas/task.schema.json`
- Modify: `src/harness/templates/current-task.yaml`
- Create: `tests/test_blocker_recovery.py`
- Modify: `tests/test_state_machine.py`
- Modify: `tests/test_quality_gate.py`

**Interfaces:**
- Produces `GateBlocker(code, category, message, source=None, finding_id=None, recover_to=None)` and `GateResult(passed, blockers)`.
- Produces `select_recovery(blockers) -> str | None` with `defect > implementation > verification > convergence` precedence.
- Adds `cmd_resume() -> int`; CLI command is `harness resume`.

- [ ] **Step 1: Write failing recovery tests**

```python
def test_resume_routes_stale_evidence_to_verifying(repo):
    set_blocked(repo, [blocker("EVIDENCE_WORKSPACE_STALE", "verification", "VERIFYING")])
    result = run_cli(repo, "resume")
    assert result.returncode == 0
    assert task_state(repo) == "VERIFYING"


def test_resume_cannot_bypass_open_finding_to_verifying(repo):
    set_blocked(repo, [blocker("FINDING_OPEN", "defect", "REPRODUCING", finding_id="FND-001")])
    assert run_cli(repo, "resume").returncode == 0
    assert task_state(repo) == "REPRODUCING"


def test_resume_routes_iteration_limit_to_escalated(repo):
    set_blocked(repo, [blocker("MAX_CONVERGENCE_ITERATIONS", "convergence", "ESCALATED")])
    assert run_cli(repo, "resume").returncode == 0
    assert task_state(repo) == "ESCALATED"
```

Add missing evidence, mixed defect+verification priority, malformed/legacy string rejection without mutation, and generic `transition VERIFYING` rejection from `BLOCKED`.

- [ ] **Step 2: Run focused tests RED**

Run: `python -m pytest tests/test_blocker_recovery.py tests/test_state_machine.py -q`

Expected: FAIL because typed blocker API, `resume`, and guarded transition do not exist.

- [ ] **Step 3: Implement typed result and schema**

Create stable code-to-category/recovery mapping. Change internal Gate checks from appended strings to `GateBlocker`; render `message` for CLI. Update task schema/template so `gate.blocked_by` accepts only blocker objects written by v0.2.2. Preserve legacy strings only in status rendering; `resume` rejects them with `HARNESS_SCHEMA_INVALID` rather than guessing.

- [ ] **Step 4: Implement `harness resume` and state guards**

Add graph edge `BLOCKED -> VERIFYING`. In `cmd_transition`, reject that edge. `cmd_resume` requires `BLOCKED`, schema-valid blockers, computes target with `select_recovery`, verifies edge with `require_legal`, atomically saves state, and prints selected code/route. Add `BLOCKED -> ESCALATED` handling only for convergence blocker.

- [ ] **Step 5: Run focused tests GREEN**

Run: `python -m pytest tests/test_blocker_recovery.py tests/test_state_machine.py tests/test_quality_gate.py tests/test_control_plane.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/blockers.py src/harness/quality_gate.py src/harness/controlplane.py src/harness/cli.py src/harness/state_machine.py src/harness/schemas/task.schema.json src/harness/templates/current-task.yaml tests/test_blocker_recovery.py tests/test_state_machine.py tests/test_quality_gate.py
git commit -m "feat: route blocked tasks from typed evidence"
```

### Task 4: Structured review outcomes

**Files:**
- Create: `src/harness/review_outcome.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/state_machine.py`
- Modify: `src/harness/schemas/task.schema.json`
- Create: `tests/test_review_outcome.py`
- Modify: `tests/test_control_plane.py`
- Modify: `tests/test_state_machine.py`

**Interfaces:**
- Produces `ReviewOutcome` enum: `PASS`, `VERIFICATION_GAP`, `DEFECT`.
- Produces `validate_outcome(outcome, reason_code, finding_ids, findings) -> dict`.
- Adds `cmd_review_outcome(outcome, reason_code, finding_ids) -> int`.
- Persists canonical `review` artifact in `current-task.yaml`; routes atomically.

- [ ] **Step 1: Write failing outcome tests**

```python
def test_verification_gap_routes_reviewing_to_verifying(repo):
    set_task_state(repo, "REVIEWING")
    result = run_cli(repo, "review", "outcome", "VERIFICATION_GAP",
                     "--reason-code", "TEST_COVERAGE_INSUFFICIENT")
    assert result.returncode == 0
    assert task_state(repo) == "VERIFYING"


def test_defect_requires_existing_nonterminal_finding(repo):
    set_task_state(repo, "REVIEWING")
    result = run_cli(repo, "review", "outcome", "DEFECT", "--finding", "FND-404")
    assert result.returncode == 2
    assert task_state(repo) == "REVIEWING"
```

Add PASS to GATING, valid DEFECT to REPRODUCING, terminal Finding rejection, and rejection of generic `transition GATING`/`transition VERIFYING` from REVIEWING.

- [ ] **Step 2: Run focused tests RED**

Run: `python -m pytest tests/test_review_outcome.py tests/test_control_plane.py tests/test_state_machine.py -q`

Expected: FAIL because `review outcome` command and guarded edges do not exist.

- [ ] **Step 3: Implement artifact validation and routing**

Validate `REVIEWING` source, uppercase enum, required stable reason code, and no `finding_ids` for PASS/VERIFICATION_GAP. Require at least one existing nonterminal Finding for DEFECT. Persist:

```yaml
review:
  outcome: VERIFICATION_GAP
  reason_code: TEST_COVERAGE_INSUFFICIENT
  message: ""
  finding_ids: []
```

Add `REVIEWING -> VERIFYING` to state graph. Make `cmd_review_outcome` sole entry for all REVIEWING exits; generic transition prints `REVIEW_OUTCOME_REQUIRED` without mutation.

- [ ] **Step 4: Run focused tests GREEN**

Run: `python -m pytest tests/test_review_outcome.py tests/test_control_plane.py tests/test_state_machine.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/review_outcome.py src/harness/controlplane.py src/harness/cli.py src/harness/state_machine.py src/harness/schemas/task.schema.json tests/test_review_outcome.py tests/test_control_plane.py tests/test_state_machine.py
git commit -m "feat: route review outcomes deterministically"
```

### Task 5: Deterministic complexity review scope and status renderer

**Files:**
- Modify: `src/harness/complexity.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/harness_status.py`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/schemas/evidence.schema.json`
- Modify: `tests/test_cli_complexity.py`
- Modify: `tests/test_complexity_review.py`
- Modify: `tests/test_status_projection.py`

**Interfaces:**
- `cmd_review_complexity(source: Path, base_ref: str) -> int` computes scope before artifact persistence.
- `write_complexity_review(harness_dir, review, scope: ReviewScope) -> list[Path]` persists canonical `review_scope`.
- `harness status` uses Evidence projection and emits no writes.

- [ ] **Step 1: Write failing scope and status tests**

```python
def test_complexity_rejects_claimed_scope_that_omits_dirty_file(repo, review_file):
    set_task_state(repo, "VERIFYING")
    (repo / "uncommitted.py").write_text("x = 1\n")
    write_review(review_file, files=[])
    result = run_cli(repo, "review", "complexity", "--base", "HEAD", "--file", str(review_file))
    assert result.returncode == 2
    assert "COMPLEXITY_REVIEW_SCOPE_MISMATCH" in result.stderr


def test_status_projects_stale_evidence_without_write(repo):
    before = (repo / ".harness/current-task.yaml").read_bytes()
    make_build_evidence(repo)
    (repo / "app.py").write_text("changed\n")
    result = run_cli(repo, "status")
    assert "build" in result.stdout and "STALE" in result.stdout
    assert (repo / ".harness/current-task.yaml").read_bytes() == before
```

Add command/timestamp/exit/covered-test rendering, `FAILED`, `MISSING`, `INVALID`, expected/current fingerprint output, complexity post-review stale output, and `base != head` committed file coverage.

- [ ] **Step 2: Run focused tests RED**

Run: `python -m pytest tests/test_cli_complexity.py tests/test_complexity_review.py tests/test_status_projection.py -q`

Expected: FAIL because `--base` is absent and status uses persisted verification fields.

- [ ] **Step 3: Implement computed complexity review**

Require `--base`; retain `--file`. Ignore artifact `head`/`base` as authority. Calculate `ReviewScope`, compare optional submitted `review_scope.files` to canonical files, reject mismatch, and write canonical `review_scope` into `complexity-review.json`. Validate freshness using shared Evidence projection before VERIFYING -> REVIEWING and in Gate.

- [ ] **Step 4: Implement read-only dynamic status**

Load task/config/requirements/invariants/findings/evidence and current snapshot. Render known required Evidence plus complexity review using projection. Render typed blocker code/message and deterministic next action (`harness resume`, refresh evidence, rerun complexity review, or resolve Finding). Do not call Gate write-back or mutate task/records.

- [ ] **Step 5: Run focused tests GREEN**

Run: `python -m pytest tests/test_cli_complexity.py tests/test_complexity_review.py tests/test_status_projection.py tests/test_control_plane.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/complexity.py src/harness/controlplane.py src/harness/cli.py src/harness/harness_status.py src/harness/quality_gate.py src/harness/schemas/evidence.schema.json tests/test_cli_complexity.py tests/test_complexity_review.py tests/test_status_projection.py
git commit -m "feat: compute review scope and project evidence status"
```

### Task 6: Lifecycle E2E, release metadata, and documentation

**Files:**
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `tests/test_readme_docs.py`
- Modify: `tests/test_cli_v022_lifecycle.py`
- Modify: `tests/test_wheel_isolation.py`

**Interfaces:**
- Version is `0.2.2`.
- Documentation presents `harness resume`, `harness review outcome`, and `harness review complexity --base <ref> --file <review.yaml>`.

- [ ] **Step 1: Write failing release and E2E tests**

```python
def test_stale_evidence_recovery_never_enters_implementing(repo):
    prepare_gating_task_with_fresh_evidence(repo)
    (repo / "tests/test_feature.py").write_text("changed\n")
    assert run_cli(repo, "converge").returncode == 0
    assert task_state(repo) == "BLOCKED"
    assert run_cli(repo, "resume").returncode == 0
    assert task_state(repo) == "VERIFYING"


def test_readmes_document_v022_commands():
    for text in (readme_en(), readme_zh()):
        assert "harness resume" in text
        assert "harness review outcome" in text
        assert "harness review complexity --base" in text
```

Add E2E verification-gap loop with no Finding, DEFECT requiring Finding/reproduction route, dirty/untracked complexity scope, and installed-wheel help/output coverage.

- [ ] **Step 2: Run focused tests RED**

Run: `python -m pytest tests/test_cli_v022_lifecycle.py tests/test_readme_docs.py tests/test_wheel_isolation.py -q`

Expected: FAIL because v0.2.2 commands/docs/version do not yet exist.

- [ ] **Step 3: Apply release updates**

Set `[project].version = "0.2.2"`. Add changelog bullets for four P0 capabilities. Update English and Chinese README daily operations and complexity command examples. Link v0.2.2 design. Keep wording explicit that `status` is read-only and resume chooses route from blockers.

- [ ] **Step 4: Run focused tests GREEN**

Run: `python -m pytest tests/test_cli_v022_lifecycle.py tests/test_readme_docs.py tests/test_wheel_isolation.py -q`

Expected: PASS.

- [ ] **Step 5: Run regression suite only after user full-suite authorization**

Run after authorization: `harness authorize full-suite && harness evidence --type unit_test --scope full_suite --command "python -m pytest tests/ -q"`

Expected: Evidence recorded with `exit_code=0`; then run `python -m pytest tests/ -q` and expect PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml CHANGELOG.md README.md README.zh-CN.md tests/test_readme_docs.py tests/test_cli_v022_lifecycle.py tests/test_wheel_isolation.py
git commit -m "release: prepare v0.2.2 flow hardening"
```

## Final verification checklist

- [ ] `python -m pytest tests/test_workspace.py tests/test_status_projection.py tests/test_blocker_recovery.py tests/test_review_outcome.py tests/test_cli_complexity.py tests/test_cli_v022_lifecycle.py -q`
- [ ] User authorizes and full `python -m pytest tests/ -q` passes.
- [ ] `python -m build` succeeds and wheel-isolation tests pass.
- [ ] `harness status` performs no filesystem mutation.
- [ ] `harness resume` accepts only typed blocker-selected route.
- [ ] `git diff --check` passes.
- [ ] `git diff --stat` and `git status --short` reviewed before release.

# FAST Risk Revalidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Fail closed when Q1/FAST changed business paths cross declared Q2/Q3 boundaries without persisted risk escalation.

**Architecture:** New pure boundary-policy module validates YAML and classifies changed repository paths. FAST Gate obtains changed business paths from immutable task baseline/current workspace, invokes pure revalidation before RED/GREEN checks, and emits typed IMPLEMENTING recovery blockers. Gate never mutates risk.

**Tech Stack:** Python 3.11, pathlib.PurePosixPath, YAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-fast-risk-revalidation-design.md`

## Global Constraints

- No keyword/semantic inference.
- `.harness/` excluded.
- `tests/`, `test/`, `docs/`, root `*.md` are docs/tests-only exceptions.
- Missing policy permits no changed business FAST path.
- Q2 boundary requires Q2; Q3 requires Q3; escalation only through existing CLI.
- STANDARD/STRICT behavior unchanged.

---

### Task 1: Pure boundary policy and path classification

**Files:**
- Create: `src/harness/risk_boundaries.py`
- Create: `tests/test_risk_boundaries.py`

**Interfaces:**
- `load_boundaries(path: Path) -> dict[str, tuple[str, ...]]` raises `RiskBoundaryPolicyError`.
- `required_level(paths: Iterable[str], boundaries: dict[str, tuple[str, ...]]) -> str | None` returns `Q2`, `Q3`, or `None`.
- `business_paths(paths: Iterable[str]) -> tuple[str, ...]` excludes policy-defined docs/tests paths.

- [ ] **Step 1: Write failing policy tests**

```python
def test_business_paths_excludes_docs_and_tests_only():
    assert business_paths(["docs/a.md", "tests/test_a.py", "README.md", "src/api/x.py"]) == ("src/api/x.py",)


def test_q3_boundary_wins_over_q2(tmp_path):
    policy = tmp_path / "risk-boundaries.yaml"
    policy.write_text("boundaries:\n  q2: [src/**]\n  q3: [auth/**]\n")
    assert required_level(["src/api.py", "auth/login.py"], load_boundaries(policy)) == "Q3"


def test_malformed_policy_fails_closed(tmp_path):
    path = tmp_path / "risk-boundaries.yaml"; path.write_text("boundaries: {q2: nope}")
    with pytest.raises(RiskBoundaryPolicyError): load_boundaries(path)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_risk_boundaries.py -q`

Expected: import failure.

- [ ] **Step 3: Implement pure module**

Use `yaml.safe_load`; require mapping exactly with `boundaries.q2` and `boundaries.q3` lists of nonempty strings. Match with `PurePosixPath(path).match(pattern)`. `Q3` wins. No filesystem mutation.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m pytest tests/test_risk_boundaries.py -q`

```bash
git add src/harness/risk_boundaries.py tests/test_risk_boundaries.py
git commit -m "feat: classify FAST risk boundaries"
```

### Task 2: FAST Gate baseline revalidation and typed recovery

**Files:**
- Modify: `src/harness/workspace.py`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/blockers.py`
- Modify: `tests/test_quality_gate.py`
- Modify: `tests/test_workspace.py`

**Interfaces:**
- `changed_paths_since(base_commit: str, repo_root: Path | None = None) -> tuple[str, ...]` includes committed baseline-to-HEAD and working paths under existing ignore policy.
- `run_fast_gate` blocks `RISK_REVALIDATION_POLICY_MISSING` or `RISK_ESCALATION_REQUIRED`; both recover to IMPLEMENTING.

- [ ] **Step 1: Write Gate failing tests**

```python
def test_fast_business_change_without_policy_blocks_escalation(tmp_path, monkeypatch):
    task, harness = fast_task_with_changed_file(tmp_path, "src/api/public.py")
    monkeypatch.chdir(tmp_path)
    status, blockers = run_gate(harness)
    assert status == "BLOCKED"
    assert blockers[0].code == "RISK_REVALIDATION_POLICY_MISSING"


def test_fast_q3_boundary_requires_q3_escalation(tmp_path, monkeypatch):
    task, harness = fast_task_with_changed_file(tmp_path, "auth/login.py")
    write_policy(tmp_path, q2=["src/**"], q3=["auth/**"])
    monkeypatch.chdir(tmp_path)
    status, blockers = run_gate(harness)
    assert any(blocker.code == "RISK_ESCALATION_REQUIRED" for blocker in blockers)
```

Add docs/tests-only no-policy pass, Q2 match pass after persisted Q2 escalation, Q3 match pass after Q3 escalation, malformed policy block, and recovery policy tests.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_quality_gate.py tests/test_workspace.py -q`

Expected: missing revalidation blockers.

- [ ] **Step 3: Implement changed-path fact and Gate check**

`changed_paths_since` uses `git diff --name-only <base>..HEAD` plus current `snapshot().changed_paths`, excludes `.harness` through existing helpers, and fails closed on Git errors.

In `run_fast_gate`, before evidence checks:
1. calculate business paths;
2. return PASS through this check when empty;
3. load `.harness/risk-boundaries.yaml` when business paths exist;
4. missing/invalid policy adds `RISK_REVALIDATION_POLICY_MISSING`;
5. compare required level with `task.risk.level`; insufficient level adds `RISK_ESCALATION_REQUIRED`.

Add both codes to `RECOVERY_POLICY` with `IMPLEMENTING` target.

- [ ] **Step 4: Run GREEN and commit**

Run: `python -m pytest tests/test_risk_boundaries.py tests/test_quality_gate.py tests/test_workspace.py tests/test_blocker_recovery.py -q`

```bash
git add src/harness/risk_boundaries.py src/harness/workspace.py src/harness/quality_gate.py src/harness/blockers.py tests/test_risk_boundaries.py tests/test_quality_gate.py tests/test_workspace.py tests/test_blocker_recovery.py
git commit -m "fix: revalidate FAST risk boundaries"
```

### Task 3: Operator documentation and cross-profile regression

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `tests/test_readme_docs.py`
- Modify: `tests/test_risk.py`

- [ ] **Step 1: Write documentation failing test**

```python
def test_docs_explain_fast_risk_boundary_escalation():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md", REPO / "SKILL.md"):
        text = path.read_text()
        assert "risk-boundaries.yaml" in text
        assert "RISK_ESCALATION_REQUIRED" in text
        assert "harness task escalate" in text
```

- [ ] **Step 2: Run RED; document; run GREEN**

Run: `python -m pytest tests/test_readme_docs.py::test_docs_explain_fast_risk_boundary_escalation -q`

Document Q2/Q3 patterns, docs/tests exception, missing policy behavior, typed blocker, and explicit escalation command. Do not promise semantic inference.

- [ ] **Step 3: Run cross-profile regression and commit**

Run: `python -m pytest tests/test_risk.py tests/test_readme_docs.py tests/test_quality_gate.py -q`

```bash
git add SKILL.md README.md README.zh-CN.md tests/test_readme_docs.py tests/test_risk.py
git commit -m "docs: explain FAST risk revalidation"
```

## Final verification

- [ ] Continue `TASK-021` requirements/invariants; do not alter task state directly.
- [ ] Record impact and focused tests via `harness impact add-*`.
- [ ] Request explicit current-task full-suite authorization.
- [ ] Run full pytest, wheel build, complexity review, verification, review outcome, Gate, then `CONVERGED → DONE`.

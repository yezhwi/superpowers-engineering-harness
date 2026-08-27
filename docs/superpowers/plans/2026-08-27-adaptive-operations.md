# Adaptive Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Add controlled recovery regression coverage, FAST soft evidence budgets, local telemetry, and deterministic fixture benchmarks.

**Architecture:** Keep recovery state machine unchanged. Add budget/telemetry modules owning persisted state and pure policy. Collector is sole budget enforcement point. Benchmark runner validates versioned fixtures and reports only local measured telemetry.

**Tech Stack:** Python 3.11, argparse, JSON/YAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-adaptive-operations-design.md`

## Global Constraints

- No state shortcut transitions.
- Budget only evidence test/build/retry executions; reuse hits never increment.
- FAST defaults only: test 2, build 1, retry 1; STANDARD/STRICT unlimited.
- Over-limit execution requires all three explicit override fields.
- Local telemetry only; no network/identifier/source/output capture; unknown is `null`.
- Benchmark does not claim unavailable token/external-agent metrics.

---

### Task 1: Phase 5 recovery-route regression audit

**Files:**
- Modify: `tests/test_blocker_recovery.py`
- Modify: `tests/test_review_outcome.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`

**Produces:** regression matrix proving `resume` routes evidence blockers to VERIFYING, review verification gaps to VERIFYING, invariant violations to IMPLEMENTING, and findings to REPRODUCING.

- [ ] **Step 1: Write failing matrix tests**

```python
@pytest.mark.parametrize("code,target", [
    ("EVIDENCE_MISSING", "VERIFYING"),
    ("EVIDENCE_WORKSPACE_STALE", "VERIFYING"),
    ("INVARIANT_VIOLATED", "IMPLEMENTING"),
    ("FINDING_OPEN", "REPRODUCING"),
])
def test_resume_routes_only_by_blocker_code(code, target, task):
    task["state"] = "BLOCKED"
    task["gate"] = {"blocked_by": [blocker(code)]}
    assert run_cli("resume").state == target
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_blocker_recovery.py tests/test_review_outcome.py -q`

Expected: add cases expose any missing controlled route.

- [ ] **Step 3: Repair only missing regression behavior**

Do not add transitions. If a test fails, repair existing `RECOVERY_POLICY` or controlled review outcome routing; preserve bare `transition REVIEWING → VERIFYING` guard.

- [ ] **Step 4: Document legal commands and run GREEN**

Document `harness resume` and `harness review outcome VERIFICATION_GAP --reason-code TEST_COVERAGE_INSUFFICIENT`; state direct shortcut transitions remain forbidden.

Run: `python -m pytest tests/test_blocker_recovery.py tests/test_review_outcome.py tests/test_readme_docs.py -q`

- [ ] **Step 5: Commit**

```bash
git add tests/test_blocker_recovery.py tests/test_review_outcome.py README.md README.zh-CN.md
git commit -m "test: audit controlled recovery routes"
```

### Task 2: FAST soft budget policy and collector enforcement

**Files:**
- Create: `src/harness/budget.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/collect_evidence.py`
- Modify: `src/harness/schemas/task.schema.json`
- Modify: `src/harness/templates/current-task.yaml`
- Create: `tests/test_budget.py`

**Interfaces:**
- `budget_action(type, exit_code, command) -> "test" | "build" | "retry" | None`.
- `check_budget(task, action, override) -> None` raises `BudgetOverrideRequired`.
- `record_budget(task, action, override) -> None`.

- [ ] **Step 1: Write failing policy tests**

```python
def test_fast_test_limit_requires_complete_override():
    task = fast_task(test_runs=2)
    with pytest.raises(BudgetOverrideRequired):
        check_budget(task, "test", None)


def test_standard_budget_is_unlimited():
    check_budget(standard_task(test_runs=999), "test", None)


def test_valid_override_is_audited():
    task = fast_task(test_runs=2)
    override = {"reason": "new consumer", "evidence": "unit-test.json", "hypothesis": "shared path"}
    check_budget(task, "test", override); record_budget(task, "test", override)
    assert task["budget"]["overrides"][-1] == {"action": "test", **override}
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_budget.py -q`

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement pure budget module/schema/template**

Use task `risk.profile`; initialize counters/overrides in template. Add optional budget schema. Treat `unit_test` as test, `build` as build, and repeated failed same command as retry. Raise only before shell execution. Never increment for reuse.

- [ ] **Step 4: Add CLI/collector failing test and run RED**

```python
def test_over_budget_evidence_does_not_execute_command(tmp_path):
    setup_fast_task(tmp_path, test_runs=2)
    result = cli(tmp_path, "evidence", "--type", "unit_test", "--scope", "related", "--covered-test", "tests/x.py", "--command", "false")
    assert result.returncode == 2
    assert "BUDGET_OVERRIDE_REQUIRED" in result.stderr
```

Run: `python -m pytest tests/test_budget.py -q`

- [ ] **Step 5: Wire override flags and run GREEN**

Add `--budget-override-reason`, `--budget-override-evidence`, `--budget-override-hypothesis`; require all together. Pass through CLI/controlplane to collector. Load/save current task around actual execution only.

Run: `python -m pytest tests/test_budget.py tests/test_evidence.py tests/test_cli_evidence_reuse.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/harness/budget.py src/harness/controlplane.py src/harness/cli.py src/harness/collect_evidence.py src/harness/schemas/task.schema.json src/harness/templates/current-task.yaml tests/test_budget.py
git commit -m "feat: add fast soft evidence budgets"
```

### Task 3: Local telemetry

**Files:**
- Create: `src/harness/telemetry.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Create: `tests/test_telemetry.py`

**Interfaces:**
- `update_telemetry(harness_dir: Path, task: dict) -> dict`.
- `harness telemetry show` prints `.harness/telemetry.json` with no mutation.

- [ ] **Step 1: Write failing telemetry test**

```python
def test_telemetry_contains_only_local_command_facts(tmp_path):
    update_telemetry(harness(tmp_path), fast_task(test_runs=2, build_runs=1))
    data = json.loads((harness(tmp_path) / "telemetry.json").read_text())
    assert data["evidence"]["test_runs"] == 2
    assert data["token_estimate"] is None
    assert "command" not in json.dumps(data)
```

- [ ] **Step 2: Run RED; implement; run GREEN**

Run: `python -m pytest tests/test_telemetry.py -q`

Persist task/risk, counters, elapsed seconds or null, gate/iterations/escalations. Invoke update after evidence, classify/escalate, and Gate commands. Add `telemetry show` read-only command.

- [ ] **Step 3: Commit**

```bash
git add src/harness/telemetry.py src/harness/cli.py src/harness/controlplane.py tests/test_telemetry.py
git commit -m "feat: record local harness telemetry"
```

### Task 4: Fixture benchmark runner

**Files:**
- Create: `src/harness/benchmark.py`
- Modify: `src/harness/cli.py`
- Create: `benchmarks/fixtures/q1-fast.yaml`
- Create: `benchmarks/fixtures/q2-standard.yaml`
- Create: `tests/test_benchmark.py`

**Interfaces:**
- `run_benchmarks(fixtures: Path, telemetry: Path) -> dict`.
- `harness benchmark run --fixtures <dir>` returns nonzero for invalid fixture/expectation.

- [ ] **Step 1: Write failing fixture test**

```python
def test_benchmark_report_uses_null_for_unavailable_metrics(tmp_path):
    report = run_benchmarks(fixtures(tmp_path), telemetry(tmp_path))
    assert report["metrics"]["token_estimate"] is None
    assert report["fixtures"][0]["expected_profile"] == "FAST"
```

- [ ] **Step 2: Run RED; implement; run GREEN**

Run: `python -m pytest tests/test_benchmark.py -q`

Validate fixture id, risk level/profile, expected gate result. Aggregate only telemetry fields. Write `benchmark-report.json`; never execute fixture commands or call network.

- [ ] **Step 3: Commit**

```bash
git add src/harness/benchmark.py src/harness/cli.py benchmarks/fixtures tests/test_benchmark.py
git commit -m "feat: add local adaptive benchmark fixtures"
```

## Final verification

- [ ] Create `TASK-020`; do not reuse completed `TASK-019`.
- [ ] Complete requirements/invariants/minimal implementation via Harness CLI.
- [ ] Request explicit `TASK-020` full-suite authorization only after Tasks 1–4.
- [ ] Run full pytest, wheel build, complexity review, requirement/invariant verification, review outcome, Gate, then DONE.

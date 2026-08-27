# Benchmark Correctness Comparator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Compare baseline/adaptive run artifacts fail-closed and report correctness preservation only with complete vector proof.

**Architecture:** Extend benchmark module with pure artifact loading, fixture-required vector comparison, and numeric-only metric deltas. CLI adds `benchmark compare`; existing `benchmark run` remains expectation validation.

**Tech Stack:** Python 3.11, JSON, YAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-benchmark-correctness-comparator-design.md`

## Global Constraints

- No agent execution/network/token estimation.
- Missing/malformed proof is `INCONCLUSIVE`.
- Required correctness vector uses explicit `true`; never scalar score.
- Metric delta only when both values numeric.
- Existing benchmark validation unchanged.

---

### Task 1: Pure fixture/artifact comparator

**Files:**
- Modify: `src/harness/benchmark.py`
- Modify: `tests/test_benchmark.py`

**Interfaces:**
- `compare_benchmarks(fixtures: Path, baseline: Path, adaptive: Path) -> dict`.
- Per-fixture statuses: `CORRECTNESS_PRESERVED`, `CORRECTNESS_REGRESSION`, `INCONCLUSIVE`.

- [ ] **Step 1: Write preserved-vector RED test**

```python
def test_compare_reports_correctness_preserved_and_numeric_deltas(tmp_path):
    fixture = write_fixture(tmp_path, required=["gate_pass", "regression_detected"])
    write_artifact(tmp_path / "baseline", "q1", "baseline", {"gate_pass": True, "regression_detected": True}, {"tool_calls": 10, "elapsed_seconds": 20})
    write_artifact(tmp_path / "adaptive", "q1", "adaptive", {"gate_pass": True, "regression_detected": True}, {"tool_calls": 5, "elapsed_seconds": 10})
    report = compare_benchmarks(fixtures_dir(tmp_path), tmp_path / "baseline", tmp_path / "adaptive")
    assert report["overall"] == "CORRECTNESS_PRESERVED"
    assert report["fixtures"][0]["metrics"]["tool_calls_delta"] == -5
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_benchmark.py -q`

Expected: import failure for `compare_benchmarks`.

- [ ] **Step 3: Implement artifact validation/comparison**

Require artifact `fixture_id`, `mode`, `correctness`, `metrics`; require fixture `id`, `required_correctness`. Read `<dir>/<id>.json`. For each required field, baseline/adaptive must equal `True`; missing/null creates INCONCLUSIVE, adaptive false creates CORRECTNESS_REGRESSION. Overall is regression if any regression, inconclusive if no regression and any inconclusive, preserved otherwise.

- [ ] **Step 4: Add fail-closed tests**

```python
@pytest.mark.parametrize("case", ["missing", "bad_json", "wrong_fixture_id", "wrong_mode", "missing_required_field"])
def test_compare_is_inconclusive_when_proof_is_incomplete(tmp_path, case):
    report = compare_case(tmp_path, case)
    assert report["overall"] == "INCONCLUSIVE"


def test_compare_reports_adaptive_required_false_as_regression(tmp_path):
    report = compare_adaptive_false(tmp_path)
    assert report["overall"] == "CORRECTNESS_REGRESSION"


def test_compare_preserves_null_metric_delta(tmp_path):
    report = compare_with_null_metrics(tmp_path)
    assert report["fixtures"][0]["metrics"]["token_estimate_delta"] is None
```

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m pytest tests/test_benchmark.py -q`

```bash
git add src/harness/benchmark.py tests/test_benchmark.py
git commit -m "feat: compare benchmark correctness artifacts"
```

### Task 2: CLI report persistence and documentation

**Files:**
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `tests/test_benchmark.py`
- Modify: `tests/test_readme_docs.py`

**Interfaces:**
- `harness benchmark compare --fixtures <dir> --baseline <dir> --adaptive <dir>` writes `.harness/benchmark-report.json`.

- [ ] **Step 1: Write CLI RED test**

```python
def test_cli_benchmark_compare_writes_correctness_report(tmp_path):
    create_compare_inputs(tmp_path)
    result = cli(tmp_path, "benchmark", "compare", "--fixtures", "fixtures", "--baseline", "baseline", "--adaptive", "adaptive")
    assert result.returncode == 0
    assert json.loads((tmp_path / ".harness/benchmark-report.json").read_text())["overall"] == "CORRECTNESS_PRESERVED"
```

- [ ] **Step 2: Run RED; wire CLI/controlplane; run GREEN**

Run: `python -m pytest tests/test_benchmark.py -q`

Add compare parser arguments, call `compare_benchmarks`, write JSON report. Comparator findings (regression/inconclusive) are valid report outcomes and CLI returns 0; invalid invocation/input paths return 2.

- [ ] **Step 3: Write doc RED test and document limits**

```python
def test_readmes_do_not_claim_benchmark_proves_unrecorded_agent_metrics():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "benchmark compare" in text
        assert "INCONCLUSIVE" in text
        assert "external agent" in text
```

Run: `python -m pytest tests/test_readme_docs.py -q`

Document artifact inputs, vector correctness, INCONCLUSIVE, and external-agent boundary.

- [ ] **Step 4: Run focused regression and commit**

Run: `python -m pytest tests/test_benchmark.py tests/test_readme_docs.py tests/test_cli_evidence_reuse.py -q`

```bash
git add src/harness/cli.py src/harness/controlplane.py README.md README.zh-CN.md tests/test_benchmark.py tests/test_readme_docs.py
git commit -m "docs: define benchmark correctness comparison"
```

## Final verification

- [ ] Continue `TASK-021`; record impact and focused tests.
- [ ] Request explicit current-task full-suite authorization.
- [ ] Run full pytest, wheel build, complexity review, requirement/invariant verification, review outcome, Gate, then DONE.

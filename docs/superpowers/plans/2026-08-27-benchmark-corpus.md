# Benchmark Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Add validated 50-fixture benchmark corpus and fail-closed AC16–20 artifact evidence evaluation.

**Architecture:** Pure corpus validator owns fixture shape/distribution. Benchmark comparator retains artifact comparison and adds per-AC evaluator that reports PASS/FAIL/INCONCLUSIVE without executing agents or inferring metrics.

**Tech Stack:** Python 3.11, YAML, JSON, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-benchmark-corpus-design.md`

## Global Constraints

- Exact corpus: Q0 10, Q1 20, Q2 10, Q3 10.
- No fake artifacts or agent execution.
- Missing artifact/metric/proof yields INCONCLUSIVE.
- Existing benchmark run/compare stay compatible.

---

### Task 1: Pure corpus validation and versioned fixtures

**Files:**
- Modify: `src/harness/benchmark.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Create: `benchmarks/corpus/q0/*.yaml` (10)
- Create: `benchmarks/corpus/q1/*.yaml` (20)
- Create: `benchmarks/corpus/q2/*.yaml` (10)
- Create: `benchmarks/corpus/q3/*.yaml` (10)
- Modify: `tests/test_benchmark.py`

**Interfaces:**
- `validate_corpus(corpus: Path) -> list[dict]` raises `ValueError("BENCHMARK_CORPUS_INVALID: ...")`.
- `harness benchmark corpus validate --corpus <dir>` returns 0 without report mutation.

- [ ] **Step 1: Write RED validator tests**

```python
def test_validate_corpus_requires_exact_level_distribution(tmp_path):
    corpus = write_corpus(tmp_path, {"Q0": 10, "Q1": 20, "Q2": 10, "Q3": 9})
    with pytest.raises(ValueError, match="BENCHMARK_CORPUS_INVALID"):
        validate_corpus(corpus)


def test_validate_corpus_rejects_duplicate_id_and_bad_profile(tmp_path):
    corpus = write_valid_corpus(tmp_path)
    duplicate_fixture(corpus, "q1-01-error-mapper")
    with pytest.raises(ValueError, match="BENCHMARK_CORPUS_INVALID"):
        validate_corpus(corpus)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_benchmark.py -q`

Expected: `validate_corpus` import failure.

- [ ] **Step 3: Implement validator and CLI**

Require id/level/expected_profile/scenario/risk_tags/required_correctness. Enforce directory level equals YAML level, expected profile mapping, Q0 null profile/empty required correctness, nonempty scenario/tags, exact counts, unique IDs. Add `benchmark corpus validate` parser/controlplane branch. It must not write `.harness/benchmark-report.json`.

- [ ] **Step 4: Create corpus fixtures**

Create 50 individual YAML fixture files. Use required correctness `[gate_pass, regression_detected]` for Q1; Q2 adds `contract_violation_detected`; Q3 adds relevant `security_violation_detected`/`contract_violation_detected`. Give every fixture specific scenario/risk tags matching spec categories.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m pytest tests/test_benchmark.py -q && harness benchmark corpus validate --corpus benchmarks/corpus`

```bash
git add src/harness/benchmark.py src/harness/cli.py src/harness/controlplane.py benchmarks/corpus tests/test_benchmark.py
git commit -m "feat: validate benchmark corpus"
```

### Task 2: AC16–20 fail-closed evaluator

**Files:**
- Modify: `src/harness/benchmark.py`
- Modify: `src/harness/controlplane.py`
- Modify: `tests/test_benchmark.py`

**Interfaces:**
- `evaluate_acceptance(report: dict, fixtures: list[dict]) -> dict` returns `{AC16: {status, ...}, ..., AC20: {status, ...}}`.

- [ ] **Step 1: Write complete-artifact RED test**

```python
def test_acceptance_passes_only_complete_improving_artifacts(tmp_path):
    fixtures = complete_corpus(tmp_path)
    report = compare_complete_runs(fixtures, baseline_metrics={"tool_calls": 10, "token_estimate": 100, "elapsed_seconds": 20}, adaptive_metrics={"tool_calls": 5, "token_estimate": 50, "elapsed_seconds": 10})
    ac = evaluate_acceptance(report, fixtures)
    assert all(ac[key]["status"] == "PASS" for key in ("AC16", "AC17", "AC18", "AC19", "AC20"))
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_benchmark.py -q`

Expected: missing evaluator.

- [ ] **Step 3: Implement evaluator**

Carry baseline/adaptive correctness and metrics into comparison fixture rows. For Q1 require all 20 numeric values for AC16–18 and strict lower mean. For AC19 require every corpus fixture complete and compare successful counts. For AC20 require all Q2/Q3 complete and compare required true vector counts. Return INCONCLUSIVE on any incomplete input; FAIL on complete non-improvement/regression.

- [ ] **Step 4: Add counterexample tests**

```python
def test_acceptance_is_inconclusive_for_missing_q1_metric(tmp_path):
    assert evaluate_missing_metric(tmp_path)["AC16"]["status"] == "INCONCLUSIVE"


def test_acceptance_fails_when_adaptive_success_rate_drops(tmp_path):
    assert evaluate_success_regression(tmp_path)["AC19"]["status"] == "FAIL"
```

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m pytest tests/test_benchmark.py -q`

```bash
git add src/harness/benchmark.py src/harness/controlplane.py tests/test_benchmark.py
git commit -m "feat: evaluate benchmark acceptance evidence"
```

### Task 3: Evidence reporting documentation

**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `tests/test_readme_docs.py`

- [ ] **Step 1: Write docs RED test**

```python
def test_readmes_document_benchmark_corpus_and_inconclusive_acs():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "benchmark corpus validate" in text
        assert "AC16" in text and "AC20" in text
        assert "INCONCLUSIVE" in text
```

- [ ] **Step 2: Run RED; document; run GREEN**

Run: `python -m pytest tests/test_readme_docs.py -q`

Document corpus validation, required baseline/adaptive artifacts, AC16–20 proof coverage, INCONCLUSIVE, and no external agent execution claim.

- [ ] **Step 3: Commit**

```bash
git add README.md README.zh-CN.md tests/test_readme_docs.py
git commit -m "docs: explain benchmark corpus evidence"
```

## Final verification

- [ ] Continue `TASK-021`; record impact and focused tests.
- [ ] Request explicit full-suite authorization.
- [ ] Run full pytest, wheel build, complexity review, verify requirements/invariants, review outcome, Gate, DONE.

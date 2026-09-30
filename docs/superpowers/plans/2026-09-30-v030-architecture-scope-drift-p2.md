# v0.3.0 Architecture Scope & Drift P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add controlled Architecture Drift Detection and Context Recovery experiments with deterministic corpus validation, three-run evidence, correctness precedence, and no unsupported efficiency claims.

**Architecture:** Extend existing benchmark reporting with a separate Architecture corpus and two explicit experiment kinds. Persisted run artifacts remain external inputs; comparison code validates treatments and reports correctness before efficiency. No benchmark result mutates canonical Harness state.

**Tech Stack:** Python 3.11+, YAML/JSON fixtures, existing `harness.benchmark`, argparse CLI, pytest.

**Spec:** `docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md`

## Global Constraints

- Requires completed P0 and P1 plans.
- Keep Drift Detection and Context Recovery as separate experiments with one treatment each.
- Each baseline/adaptive arm has at least three runs per fixture.
- Correctness and integrity failures override efficiency metrics.
- Drift experiment uses exact formulas: correctly blocked drift cases / all labeled drift cases; correct unresolved-or-ambiguous diagnostics / all emitted unresolved-or-ambiguous diagnostics; incorrectly blocked clean cases / all labeled clean cases; expected modules absent from declared modules / all expected modules.
- Context factual recovery is exact-match projected `(id, responsibility, depends_on)` records / all expected projected records.
- token and tool-call cost are required run-level efficiency metrics and never participate in correctness. Search/file/elapsed may be additional fields only; they cannot replace token/tool cost or justify a verdict when correctness declines.
- Every metric reports numerator, denominator, and `not_applicable` case count; Diagnostic precision is `not_applicable` when no unresolved/ambiguous diagnostic was emitted.
- Missing, malformed, mismatched, estimated, or incomplete runs yield `INCONCLUSIVE`, never fabricated values.
- Benchmark never changes Architecture, task, Gate, Context, Finding, or evidence authority.
- Every implementation commit requires fresh explicit user authorization.
- Run focused related tests only.

## Review Focus

- Adaptive detects drift but baseline fixture differs in any non-treatment input: fixture is invalid/inconclusive.
- Three attempts exist but one lacks correctness or usage: no efficiency conclusion.
- Architecture model omits true owner: classify as declaration quality, not detector false negative.
- Extra unresolved/ambiguous diagnostic identities reduce Diagnostic precision; scope-drift blockers do not enter Diagnostic precision and instead affect drift recall or clean-case false-positive rate as labeled.
- Context adaptive saves tokens but has lower recovery success: experiment fails by correctness precedence.

---

### Task 1: Architecture Benchmark Corpus Contract

**Files:**
- Create: `benchmarks/architecture/drift/*.yaml`
- Create: `benchmarks/architecture/context/*.yaml`
- Modify: `src/harness/benchmark.py`
- Modify: `src/harness/cli.py`
- Create: `tests/test_architecture_benchmark.py`
- Modify: `tests/test_benchmark_cli.py`

**Interfaces:**
- Produces: `validate_architecture_corpus(root: Path) -> list[dict]`; CLI `harness benchmark architecture-corpus validate --corpus <path>`.
- Consumes: existing YAML loading/error convention; does not alter `validate_corpus()` exact Q0–Q3 distribution.

- [ ] **Step 1: Write failing corpus validation tests**

Require unique IDs, experiment kind, scenario, fixed task/model/Git inputs, expected blocker identities or expected recovery facts, and explicit treatment. Reject mixed treatments, unknown fields, duplicate IDs, invalid module/rule IDs, and corpus stored inside existing Q0–Q3 distribution.

- [ ] **Step 2: Add ten required scenario fixtures**

Cover normal ownership, unexpected module, unresolved path, ambiguity, shared ownership, support path, rename D+A, adopted/protected paths, Context recovery, and false-positive control. Mark declaration-quality truth separately from detector expectations.

- [ ] **Step 3: Run RED**

Run: `pytest tests/test_architecture_benchmark.py tests/test_benchmark_cli.py -q`
Expected: FAIL because validator/CLI/corpus are absent.

- [ ] **Step 4: Implement validator and CLI**

Keep Architecture corpus independent from existing `benchmarks/corpus` cardinality rules. Stable error: `ARCHITECTURE_BENCHMARK_CORPUS_INVALID`.

- [ ] **Step 5: Run GREEN**

Run focused command from Step 3.
Expected: PASS.

- [ ] **Step 6: Commit checkpoint**

Request authorization, then commit `test: add architecture benchmark corpus`.

---

### Task 2: Separate Experiment Comparison

**Files:**
- Modify: `src/harness/benchmark.py`
- Modify: `src/harness/cli.py`
- Modify: `tests/test_architecture_benchmark.py`
- Modify: `tests/test_benchmark.py`

**Interfaces:**
- Produces: `compare_architecture_experiment(fixtures: Path, baseline: Path, adaptive: Path, *, experiment: Literal["drift_detection", "context_recovery"]) -> dict`; CLI `harness benchmark architecture-compare --experiment ... --fixtures ... --baseline ... --adaptive ...`.
- Consumes: existing run normalization, telemetry validation, `INCONCLUSIVE`, median/p90, and correctness precedence patterns.

- [ ] **Step 1: Write failing treatment-parity tests**

Drift: baseline mode off, adaptive required, every other persisted input equal. Context: both use same required assessment/task facts/token budget; adaptive alone includes Architecture projection. Mismatch yields invalid/inconclusive row.

- [ ] **Step 2: Write failing three-run and correctness tests**

Require at least three attempts per arm. Missing correctness/usage, malformed identity, estimated usage, or fixture mismatch gives `INCONCLUSIVE`. Any safety/correctness regression gives `FAIL` before efficiency.

- [ ] **Step 3: Write failing metric tests**

Pin all six formulas independently:

- Drift recall = correctly blocked drift cases / all labeled drift cases.
- Diagnostic precision = correct unresolved-or-ambiguous diagnostics / all emitted unresolved-or-ambiguous diagnostics; no emitted diagnostics means `not_applicable`.
- False-positive rate = incorrectly blocked clean cases / all labeled clean cases.
- Missed-impact proxy = expected modules absent from declared modules / all expected modules, labeled declaration quality only.
- Context factual recovery = exact-match projected `(id, responsibility, depends_on)` records / all expected projected records.
- Token and tool-call cost uses existing run-level statistics and does not participate in correctness.

Use stable `(code, source)` identity only inside the metric whose labeled unit requires it. Assert scope-drift blockers do not enter Diagnostic precision. Every result carries numerator, denominator, and `not_applicable` case count.

- [ ] **Step 4: Add review-focus counterexamples**

Pin differing non-treatment input, incomplete third run, omitted true owner, extra unresolved/ambiguous diagnostic identity, and cheaper-but-less-correct Context. Scope drift follows drift recall or clean-case false-positive labeling, not Diagnostic precision.

- [ ] **Step 5: Run RED**

Run: `pytest tests/test_architecture_benchmark.py tests/test_benchmark.py -q`
Expected: FAIL because comparison interface is absent.

- [ ] **Step 6: Implement experiment-specific comparison**

Reuse low-level run/usage helpers, but do not route Architecture experiments through Q1-only acceptance logic. Return separate experiment status and confidence; never combine two treatments into one verdict.

- [ ] **Step 7: Run GREEN**

Run focused command from Step 5.
Expected: PASS.

- [ ] **Step 8: Commit checkpoint**

Request authorization, then commit `feat: compare architecture experiments`.

---

### Task 3: P2 Reports and Acceptance

**Files:**
- Modify: `tests/test_architecture_benchmark.py`
- Modify: `tests/test_benchmark_cli.py`
- Modify: `CHANGELOG.md`
- Create: `docs/superpowers/reports/v030-architecture-benchmark-template.md`

**Interfaces:**
- Consumes: Tasks 1–2 interfaces and externally collected run artifacts.
- Produces: deterministic JSON report plus human-readable report template; does not claim measured improvement without actual accepted runs.

- [ ] **Step 1: Write failing report tests**

Assert deterministic fixture ordering, explicit experiment/treatment descriptions, three-run counts, correctness status before efficiency fields, null/INCONCLUSIVE unavailable metrics, separate declaration-quality section, and numerator/denominator/`not_applicable` counts for each fixed metric.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_architecture_benchmark.py tests/test_benchmark_cli.py -q`
Expected: FAIL on report contract.

- [ ] **Step 3: Implement report output and template**

Template labels unexecuted results as pending; no synthetic run artifacts or benchmark claims enter repository.

- [ ] **Step 4: Run P2 acceptance**

```bash
pytest tests/test_architecture_benchmark.py tests/test_benchmark.py tests/test_benchmark_cli.py -q
harness benchmark architecture-corpus validate --corpus benchmarks/architecture
python -m pip wheel . --no-deps -w /tmp/harness-v030-p2
```

Expected: all PASS; corpus validates; absent real run sets remain pending/INCONCLUSIVE.

- [ ] **Step 5: Run real experiments only when run artifacts are supplied**

For each fixture and arm, collect at least three independent persisted runs. Run comparison separately for `drift_detection` and `context_recovery`. Never substitute generated fixtures for measured agent runs.

- [ ] **Step 6: Run Harness verification/review/Gate**

Collect fresh focused evidence, reconcile Plan, perform required reviews, run Gate.
Expected: `DECISION: CONVERGED`.

- [ ] **Step 7: Commit checkpoint**

Request authorization, then commit `feat: complete architecture evaluation p2`.

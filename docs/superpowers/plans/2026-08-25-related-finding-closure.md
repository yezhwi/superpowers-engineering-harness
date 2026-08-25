# Related Finding Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permit major findings to close from impact-covered related tests; keep critical and high-impact findings full-suite-only.

**Architecture:** Persist scope and covered test IDs in evidence. Add one finding-closure validator shared by lifecycle transition and quality gate; it layers policy checks on existing freshness/identity validation.

**Tech Stack:** Python 3.11, argparse, JSON Schema, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-related-finding-closure-design.md`

## Global Constraints

- No dependency added.
- Critical findings require authorized `full_suite` proof.
- Major related proof must cover every `.harness/impact.yaml` `required_tests` entry.
- `impact.full_suite.recommended: true` overrides major related closure.
- Never infer test coverage from a command string.
- Existing generic evidence stays compatible.

---

### Task 1: Persist structured evidence scope and coverage

**Files:**
- Modify: `src/harness/schemas/evidence.schema.json`
- Modify: `src/harness/collect_evidence.py`
- Modify: `src/harness/controlplane.py:cmd_evidence`
- Modify: `src/harness/cli.py:evidence parser/dispatch`
- Modify: `tests/test_evidence.py`
- Modify: `tests/test_cli_complexity.py`

**Interfaces:**
- `collect(evidence_type, command, finding_id=None, test_id=None, scope="related", covered_tests=()) -> dict`
- Evidence fields: `scope` enum `related|full_suite`; `covered_tests` array of nonempty strings.
- CLI accepts repeatable `--covered-test`.

- [ ] **Step 1: Write failing tests**

```python
def test_related_evidence_persists_covered_tests(tmp_path):
    result = run_cli(tmp_path, "evidence", "--type", "unit_test",
        "--scope", "related", "--covered-test", "tests/a.py::test_a",
        "--command", "python -c 'pass'")
    record = json.loads((tmp_path / ".harness/evidence/unit-test.json").read_text())
    assert record["scope"] == "related"
    assert record["covered_tests"] == ["tests/a.py::test_a"]


def test_related_scope_requires_covered_test(tmp_path):
    result = run_cli(tmp_path, "evidence", "--type", "unit_test",
        "--scope", "related", "--command", "python -c 'pass'")
    assert result.returncode == 2
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_evidence.py tests/test_cli_complexity.py -q`

Expected: evidence has no scope/coverage and parser rejects `--covered-test`.

- [ ] **Step 3: Implement minimal evidence plumbing**

Add optional schema properties. Add `--covered-test` with `action="append"`. Reject `scope == "related" and not covered_tests` only for `type == "unit_test"`; preserve generic evidence compatibility. Pass scope/coverage through CLI, `cmd_evidence`, and `collect`; serialize list deterministically.

- [ ] **Step 4: Run GREEN**

Run: `python -m pytest tests/test_evidence.py tests/test_cli_complexity.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/schemas/evidence.schema.json src/harness/collect_evidence.py src/harness/controlplane.py src/harness/cli.py tests/test_evidence.py tests/test_cli_complexity.py
git commit -m "feat: record evidence scope and test coverage"
```

### Task 2: Enforce closure policy in transition and gate

**Files:**
- Modify: `src/harness/evidence_validator.py`
- Modify: `src/harness/controlplane.py:cmd_finding_transition`
- Modify: `src/harness/quality_gate.py`
- Modify: `tests/test_finding_transition.py`
- Modify: `tests/test_finding_lifecycle.py`

**Interfaces:**
- Add `validate_finding_closure_evidence(finding, record, impact, *, current_head, current_workspace) -> None`.
- Raises `EvidenceValidationError` with `FINDING_SCOPE_MISSING`, `FULL_SUITE_REQUIRED_FOR_CRITICAL`, `FULL_SUITE_REQUIRED_BY_IMPACT`, or `RELATED_TEST_COVERAGE_MISSING`.

- [ ] **Step 1: Write failing policy tests**

```python
def test_major_finding_accepts_related_evidence_covering_impact(tmp_path):
    # FND-001 major is FIXED; impact requires tests/a.py::test_a.
    # related full-proof record names that test in covered_tests.
    assert transition(tmp_path, "VERIFIED", "related.json").returncode == 0


def test_critical_finding_rejects_related_evidence(tmp_path):
    result = transition(tmp_path, "VERIFIED", "related.json")
    assert result.returncode == 2
    assert "FULL_SUITE_REQUIRED_FOR_CRITICAL" in result.stderr


def test_major_finding_rejects_incomplete_related_coverage(tmp_path):
    result = transition(tmp_path, "VERIFIED", "related.json")
    assert result.returncode == 2
    assert "RELATED_TEST_COVERAGE_MISSING" in result.stderr
```

Add gate tests for manually edited `VERIFIED` and `CLOSED` major findings with missing scope/coverage and for `impact.full_suite.recommended: true`.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_finding_transition.py tests/test_finding_lifecycle.py -q`

Expected: related evidence is currently accepted without policy or test helpers cannot produce structured scope.

- [ ] **Step 3: Implement shared validator**

Keep `validate_evidence` unchanged for generic callers. New validator calls it with `expected_success=True`, loads `impact["impact"]`, then enforces severity/scope/coverage policy from spec. Treat absent `scope` as `FINDING_SCOPE_MISSING`; compare `set(required_tests)` against `set(covered_tests)`; do not parse `command`.

In `cmd_finding_transition`, replace `VERIFIED` proof call with validator using `.harness/impact.yaml`. In `quality_gate`, use same validator for `VERIFIED` and `CLOSED` full-regression proof.

- [ ] **Step 4: Run GREEN and regressions**

Run: `python -m pytest tests/test_finding_transition.py tests/test_finding_lifecycle.py tests/test_quality_gate.py tests/test_evidence_validator.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/evidence_validator.py src/harness/controlplane.py src/harness/quality_gate.py tests/test_finding_transition.py tests/test_finding_lifecycle.py tests/test_quality_gate.py tests/test_evidence_validator.py
git commit -m "feat: allow impact-covered major finding closure"
```

### Task 3: Align workflow documentation and installed behavior

**Files:**
- Modify: `skills/reproduce-finding/SKILL.md`
- Modify: `SKILL.md`
- Modify: `tests/test_wheel_isolation.py`

- [ ] **Step 1: Write failing documentation assertions**

Add assertions that lifecycle docs state: critical/full suite; major/related coverage; impact full-suite override.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_readme_docs.py -q`

Expected: missing policy text.

- [ ] **Step 3: Update docs and wheel test**

Replace unconditional full-regression wording with policy table. Add installed-wheel CLI smoke assertion for `harness evidence --help` containing `--covered-test`.

- [ ] **Step 4: Verify**

Run:

```bash
python -m pytest tests/test_readme_docs.py tests/test_wheel_isolation.py -q
python -m pytest tests/ -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/reproduce-finding/SKILL.md SKILL.md tests/test_readme_docs.py tests/test_wheel_isolation.py
git commit -m "docs: describe related finding closure policy"
```

## Self-Review

- Spec coverage: Task 1 persists auditable scope/coverage; Task 2 applies identical closure policy at transition and gate; Task 3 prevents workflow documentation drift.
- No command-string inference, dependency, or state-machine change.

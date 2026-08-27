# FAST Light Gate Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Require deterministic repository verification in FAST Light Gate while preserving FAST scope and authorization boundaries.

**Architecture:** Load `gate.yaml` for FAST only to resolve `gate.fast.verification`; default to build required. Reuse existing evidence validator for required repository proof. Keep P0-3 revalidation before verification and leave STANDARD checks isolated.

**Tech Stack:** Python 3.11, YAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-fast-light-gate-completeness-design.md`

## Global Constraints

- FAST RED/GREEN always required.
- Default FAST build required; typecheck opt-in.
- Required evidence must be successful and current HEAD/workspace.
- No requirements/invariants/complexity/findings generic ceremony in FAST.
- Authorization records remain separate; Gate makes no external-side-effect detection claim.

---

### Task 1: FAST verification policy and Gate enforcement

**Files:**
- Modify: `src/harness/templates/gate.yaml`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/blockers.py`
- Modify: `tests/test_quality_gate.py`

**Interfaces:**
- `fast_verification_policy(gate_doc: dict) -> dict[str, str]` returns configured policy or `{"build": "required"}`.
- FAST blocker `FAST_REPOSITORY_VERIFICATION_MISSING` recovers `VERIFYING`.

- [ ] **Step 1: Write failing default-build test**

```python
def test_fast_gate_requires_build_by_default(tmp_path):
    h = make_fast_harness(tmp_path, red=True, green=True)
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any(item.code == "FAST_REPOSITORY_VERIFICATION_MISSING" for item in blockers)
```

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_quality_gate.py::test_fast_gate_requires_build_by_default -q`

Expected: FAIL because current FAST Gate passes with only RED/GREEN.

- [ ] **Step 3: Implement policy and required evidence validation**

Add template:

```yaml
fast:
  verification:
    build: required
    typecheck: optional
```

Load `gate.yaml` in FAST branch. For each required type, read `<type-with-dashes>.json`; validate `expected_success=True`, current HEAD/workspace. Missing/invalid/failed record creates typed FAST repository verification blocker. Do not call standard evidence/requirement/invariant/finding checks.

- [ ] **Step 4: Add typecheck/optional/freshness tests**

```python
def test_fast_gate_requires_explicit_typecheck(tmp_path):
    h = make_fast_harness(tmp_path, red=True, green=True, build=True)
    set_fast_policy(h, {"build": "required", "typecheck": "required"})
    assert has_code(run_gate(h), "FAST_REPOSITORY_VERIFICATION_MISSING")


def test_fast_gate_accepts_required_build_and_optional_typecheck(tmp_path):
    h = make_fast_harness(tmp_path, red=True, green=True, build=True)
    set_fast_policy(h, {"build": "required", "typecheck": "optional"})
    assert run_gate(h)[0] == "PASS"
```

Add stale/failed build tests asserting same blocker.

- [ ] **Step 5: Run GREEN and commit**

Run: `python -m pytest tests/test_quality_gate.py tests/test_blocker_recovery.py -q`

```bash
git add src/harness/templates/gate.yaml src/harness/quality_gate.py src/harness/blockers.py tests/test_quality_gate.py tests/test_blocker_recovery.py
git commit -m "fix: require FAST repository verification"
```

### Task 2: Documentation and authorization boundary regression

**Files:**
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `tests/test_readme_docs.py`

- [ ] **Step 1: Write failing doc contract**

```python
def test_docs_define_fast_verification_and_authorization_boundary():
    for path in (REPO / "SKILL.md", REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "gate.fast.verification" in text
        assert "FAST_REPOSITORY_VERIFICATION_MISSING" in text
        assert "outside Harness" in text
```

- [ ] **Step 2: Run RED; document; run GREEN**

Run: `python -m pytest tests/test_readme_docs.py::test_docs_define_fast_verification_and_authorization_boundary -q`

Document default build, typecheck opt-in, typed verification blocker, independent grants, and inability to detect external actions outside Harness.

- [ ] **Step 3: Commit**

```bash
git add SKILL.md README.md README.zh-CN.md tests/test_readme_docs.py
git commit -m "docs: define FAST verification boundary"
```

## Final verification

- [ ] Continue `TASK-021`; record impact and focused tests via Harness CLI.
- [ ] Request explicit full-suite authorization for current task.
- [ ] Run full pytest, wheel build, complexity review, requirement/invariant verification, review outcome, Gate, then DONE.

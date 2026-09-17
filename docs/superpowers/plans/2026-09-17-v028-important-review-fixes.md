# v0.2.8 Important Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve Important findings 3–7 without weakening decision freshness, FAST evidence discipline, or typed review scope boundaries.

**Architecture:** Share FAST GREEN evidence resolution between verification and Light Gate. Treat historical decisions as byte-hashed metadata records until current-task ownership or explicit cross-task linkage requires full YAML construction. Tighten new review evidence schema while preserving legacy typed-scope migration on read.

**Tech Stack:** Python 3.11, PyYAML node API, jsonschema, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-17-v028-important-review-fixes-design.md`

## Global Constraints

- Keep every canonical `decisions/DEC-*.yaml` byte-hashed in Context freshness.
- Do not deserialize or project unreferenced historical decision bodies.
- Do not skip FAST RED from `verification_mode` alone.
- Preserve legacy `DEC-*` review-scope migration in `workspace.claimed_scope_sets()`.
- `requires_reproduction` remains non-persisting and leaves task `CLASSIFIED`.
- Do not modify product code or unrelated untracked documents; `docs/2026-09-16-v0.2.8-runtime-optimization-implementation-guide.md` is explicitly in scope and must be added to its documentation commit.

---

### Task 1: Shared FAST GREEN Resolver and Valid Existing-Mode Gate

**Files:**
- Modify: `src/harness/existing_verification.py`
- Modify: `src/harness/quality_gate.py`
- Modify: `tests/test_verify_existing.py`
- Modify: `tests/test_quality_gate.py`

**Interfaces:**
- Produces: `green_unit_test_evidence(harness_dir: Path, *, head: str, workspace_hash: str) -> dict | None` in `existing_verification.py`.
- Consumes: `validate_evidence(record, current_head, current_workspace, expected_success=True)`.
- Produces: `has_existing_verification(task: dict) -> bool`, used by `run_fast_gate()` to decide whether RED is required.

- [ ] **Step 1: Write alternate-GREEN regression tests**

Add a verify-existing test that writes `unit-test.json` instead of `fast-green-unit-test.json`, invokes `task verify-existing`, and asserts return code 0. Add a Light Gate test with a valid `existing_verification` record and only `unit-test.json`, asserting `PASS`.

```python
def test_fast_gate_accepts_standard_green_evidence_for_existing_mode(tmp_path):
    h, task = fast_task(tmp_path)
    task["verification_mode"] = "existing_implementation"
    task["existing_verification"] = valid_existing_verification()
    write_evidence(REPO, h, "unit_test", name="unit-test.json")
    assert run_gate(h)[0] == "PASS"
```

- [ ] **Step 2: Run alternate-GREEN tests to establish preserved and failing behavior**

Run: `pytest -q tests/test_verify_existing.py::test_verify_existing_accepts_unit_test_green_evidence tests/test_verify_existing.py::test_fast_gate_accepts_standard_green_evidence_for_existing_mode`

Expected: verify-existing passes because it already accepts `unit-test.json`; Light Gate fails with `FAST_REGRESSION_EVIDENCE_MISSING`, proving its path set diverges.

- [ ] **Step 3: Write invalid existing-mode tests**

Add parameterized Gate tests for (a) mode only with no record, (b) malformed record missing `conclusion`, and (c) `requires_reproduction` conclusion. Each writes only GREEN evidence and asserts `BLOCKED` with `FAST_REGRESSION_EVIDENCE_MISSING`, proving RED was not skipped.

```python
@pytest.mark.parametrize("record", [None, {"reference": "HEAD"}, {"conclusion": "requires_reproduction"}])
def test_fast_gate_requires_red_without_valid_existing_verification(tmp_path, record):
    h, task = fast_task(tmp_path)
    task["verification_mode"] = "existing_implementation"
    if record is not None:
        task["existing_verification"] = record
    write_green_only(h)
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert any(item.code == "FAST_REGRESSION_EVIDENCE_MISSING" for item in blockers)
```

- [ ] **Step 4: Run invalid-mode tests to verify RED**

Run: `pytest -q tests/test_verify_existing.py -k 'existing_mode or fast_gate'`

Expected: current mode-only test incorrectly passes; malformed cases may currently pass or fail schema-adjacently. Adjust test setup until it fails because RED was skipped.

- [ ] **Step 5: Implement resolver and record predicate**

In `existing_verification.py`, define ordered path constant and resolver which reads both candidate files through `source_access`, validates fresh successful evidence, and returns only a `unit_test` record. Make `require_green_evidence()` call it.

```python
GREEN_UNIT_TEST_EVIDENCE = ("fast-green-unit-test.json", "unit-test.json")

def green_unit_test_evidence(harness_dir: Path, *, head: str, workspace_hash: str) -> dict | None:
    for name in GREEN_UNIT_TEST_EVIDENCE:
        record = _valid_success_evidence(harness_dir / "evidence" / name, head, workspace_hash)
        if record is not None and record.get("type") == "unit_test":
            return record
    return None
```

Define `has_existing_verification()` to require mode, mapping record, `reference`/`reason` non-empty strings, and conclusion in `{already_satisfied, duplicate_request}`. Use predicate in `run_fast_gate()`. Replace its direct `fast-green-unit-test.json` load with shared resolver; on `None`, append existing `FAST_REGRESSION_EVIDENCE_MISSING` blocker.

- [ ] **Step 6: Run Task 1 suite**

Run: `pytest -q tests/test_verify_existing.py tests/test_quality_gate.py tests/test_gate_source_access.py`

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/harness/existing_verification.py src/harness/quality_gate.py tests/test_verify_existing.py tests/test_quality_gate.py
git commit -m "fix: validate FAST existing verification mode"
```

### Task 2: Contract, Workflow Text, and Typed Diagnosability Scope Schema

**Files:**
- Modify: `src/harness/schemas/diagnosability-review-evidence.schema.json`
- Modify: `tests/test_cli_diagnosability.py`
- Modify: `docs/Superpowers-Engineering-Harness-v0.2.8-Implementation-Contract.md`
- Modify: `docs/2026-09-16-v0.2.8-runtime-optimization-implementation-guide.md`
- Modify: `SKILL.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/architecture.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: JSON Schema `review_scope.files` and `review_scope.contract_refs` persisted by diagnosability CLI.
- Preserves: `workspace.claimed_scope_sets()` legacy migration for pre-schema artifacts.

- [ ] **Step 1: Write schema rejection and acceptance tests**

Add direct schema validation tests. A fresh evidence document with `review_scope.files = ["DEC-001:orders"]` must raise schema validation error. A document with `files = ["src/orders.py"]` and `contract_refs = ["DEC-001:orders"]` must validate.

```python
def test_diagnosability_evidence_schema_rejects_contract_label_as_file(tmp_path):
    record = valid_review_evidence()
    record["review_scope"]["files"] = ["DEC-001:orders"]
    with pytest.raises(ValidationError):
        validate(record, read_schema("diagnosability-review-evidence.schema.json"))
```

- [ ] **Step 2: Run schema tests to verify RED**

Run: `pytest -q tests/test_cli_diagnosability.py -k 'contract_label or contract_refs'`

Expected: label-in-files schema test fails because current `files.items` is unconstrained.

- [ ] **Step 3: Tighten schema only for new evidence**

Change schema item definitions:

```json
"files": {
  "type": "array",
  "items": {
    "type": "string",
    "minLength": 1,
    "not": {"pattern": "^DEC-"}
  }
},
"contract_refs": {
  "type": "array",
  "items": {"type": "string", "minLength": 1}
}
```

Do not change `claimed_scope_sets()`: it remains legacy read migration.

- [ ] **Step 4: Run Task 2 schema suite**

Run: `pytest -q tests/test_cli_diagnosability.py tests/test_diagnosability_source_access.py tests/test_impact_control_plane.py`

Expected: PASS.

- [ ] **Step 5: Synchronize documented semantics**

Update contract section governing FAST verification: existing implementation may skip RED only if persisted `verification_mode` plus valid `existing_verification` record exists; GREEN/build freshness remains mandatory. Update implementation guide, SKILL, README translations, architecture, and CHANGELOG to state `requires_reproduction` leaves task `CLASSIFIED` and directs user to existing finding/reproduce workflow.

- [ ] **Step 6: Verify documentation claims**

Run:

```bash
rg -n 'requires_reproduction|existing_implementation|verify-existing|FAST.*RED|RED.*FAST' \
  docs/Superpowers-Engineering-Harness-v0.2.8-Implementation-Contract.md \
  docs/2026-09-16-v0.2.8-runtime-optimization-implementation-guide.md \
  SKILL.md README.md README.zh-CN.md docs/architecture.md CHANGELOG.md
```

Expected: no document states or implies direct transition to `REPRODUCING`; all describe record-gated RED exemption.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/harness/schemas/diagnosability-review-evidence.schema.json tests/test_cli_diagnosability.py docs/Superpowers-Engineering-Harness-v0.2.8-Implementation-Contract.md docs/2026-09-16-v0.2.8-runtime-optimization-implementation-guide.md SKILL.md README.md README.zh-CN.md docs/architecture.md CHANGELOG.md
git commit -m "fix: document and type existing verification scope"
```

### Task 3: Decision Metadata Scan and Lazy Historical Bodies

**Files:**
- Modify: `src/harness/decision.py`
- Modify: `src/harness/context/source.py`
- Modify: `src/harness/context/model.py`
- Modify: `src/harness/context/selector.py`
- Modify: `src/harness/context/builder.py`
- Modify: `src/harness/context/integrity.py`
- Modify: `tests/test_context_automatic.py`
- Modify: `tests/test_context_builder.py`
- Modify: `tests/test_context_integrity.py`
- Modify: `tests/test_context_read_scope.py`

**Interfaces:**
- Produces: `DecisionMetadata` with `id`, `task_id`, `status`, `supersedes`, `superseded_by`, `path`, and byte hash/reference.
- Produces: `scan_decision_metadata(harness_dir: Path) -> list[DecisionMetadata]` and `load_decision(harness_dir, decision_id) -> dict`.
- Consumes: current task ID plus explicit decision IDs from current decisions, `impact.contracts` labels, and loaded interface-contract `decision_refs` to select full cross-task bodies.
- Preserves: `AuthoritativeContext.decisions: list[dict]` as fully loaded selected decisions; adds metadata collection for omission/reference accounting.

- [ ] **Step 1: Write historical-body regression tests**

Add fixture with one current accepted decision and 100 historical accepted decisions whose nested `question` values are `HISTORICAL-BODY-<id>`. Monkeypatch existing `decision._validate`, which is called only after full record construction. Build compact context with `build_context`; assert validation sees only current decision, output has no historical body string, and omitted records retain each historical ID/ref/reason.

```python
def test_context_does_not_deserialize_unreferenced_historical_decisions(harness, monkeypatch):
    add_current_and_historical_decisions(harness, count=100)
    validated = []
    original = decision._validate
    monkeypatch.setattr(decision, "_validate", lambda record: validated.append(record["id"]) or original(record))
    document = build_context(harness, mode="compact")
    assert validated == ["DEC-001"]
    assert "HISTORICAL-BODY-DEC-100" not in yaml.safe_dump(document)
```

- [ ] **Step 2: Run historical-body test to verify RED**

Run: `pytest -q tests/test_context_automatic.py::test_context_does_not_deserialize_unreferenced_historical_decisions`

Expected: FAIL because `decision.load_decisions()` currently calls full YAML loader for every canonical decision.

- [ ] **Step 3: Write dependency and freshness counterexamples**

Add tests proving (a) explicitly superseded historical decision is fully loaded and only Layer 2 referenced, (b) `impact.contracts = ["DEC-200:orders"]` and interface-contract `decision_refs = ["DEC-201"]` load their referenced historical bodies as Layer 2 only, (c) missing explicit ID raises `CONTEXT_REFERENCE_BROKEN`, (d) invalid top-level metadata raises `CONTEXT_SCHEMA_INVALID`, and (e) editing unreferenced historical decision bytes makes old Context `CONTEXT_STALE`.

- [ ] **Step 4: Run counterexamples to verify RED**

Run: `pytest -q tests/test_context_automatic.py tests/test_context_integrity.py -k 'historical or cross_task or stale'`

Expected: historical load-count assertion fails before implementation; existing explicit-reference and stale tests establish preserved behavior.

- [ ] **Step 5: Implement metadata scanner in decision domain**

In `decision.py`, add frozen `DecisionMetadata` and `_metadata_from_yaml(content: str, path: Path)`. Use `yaml.compose()` and inspect only top-level mapping scalar nodes for exact metadata fields. Reject duplicate metadata keys, missing/non-scalar `id`/`task_id`/`status`, or non-string non-null linkage fields with `DecisionError("DECISION_RECORD_INVALID")`. Do not call `_validate()` or construct nested YAML values in this scan.

```python
@dataclass(frozen=True)
class DecisionMetadata:
    id: str
    task_id: str
    status: str
    supersedes: str | None
    superseded_by: str | None
    path: Path

def scan_decision_metadata(harness_dir: Path) -> list[DecisionMetadata]:
    return [_metadata_from_yaml(source_access.read_text(path), path)
            for path in source_access.members(_directory(harness_dir), "DEC-*.yaml")]
```

Retain `load_decision()` as full schema validation and make `load_decisions()` use it for callers that explicitly need every full record.

- [ ] **Step 6: Implement Context selective body loading**

In `FileContextSource.load()`, replace decision `_records()` call with metadata scan. Register a byte-hash reference for every metadata path. Load full records for metadata where `task_id == current_task_id`; gather IDs from their `supersedes`/`superseded_by`, `impact.contracts` values matching `DEC-[0-9]+:` (extract prefix before `:`), and every loaded interface contract `decision_refs`; then load only requested cross-task metadata records. Verify metadata ID matches full record ID and reject missing requested IDs as `CONTEXT_REFERENCE_BROKEN`. Add `decision_metadata` to `AuthoritativeContext`; adapt selector omission loop to use metadata for unselected historical entries and full `decisions` only for selected records. Keep current-task decision Layer 0/working behavior unchanged.

- [ ] **Step 7: Run Task 3 suites**

Run: `pytest -q tests/test_context_automatic.py tests/test_context_builder.py tests/test_context_integrity.py tests/test_context_selector.py tests/test_context_read_scope.py tests/test_context_freshness_property.py`

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/harness/decision.py src/harness/context/source.py src/harness/context/model.py src/harness/context/selector.py src/harness/context/builder.py src/harness/context/integrity.py tests/test_context_automatic.py tests/test_context_builder.py tests/test_context_integrity.py tests/test_context_read_scope.py
git commit -m "fix: defer historical decision body loading"
```

### Task 4: Final Verification and New-Code Review

**Files:**
- Verify: all Task 1–3 files

- [ ] **Step 1: Run complete test suite**

Run: `pytest -q`

Expected: zero failures.

- [ ] **Step 2: Run static checks**

Run:

```bash
ruff check src tests
git diff HEAD~3..HEAD --check
```

Expected: zero findings and no whitespace errors.

- [ ] **Step 3: Review new code only**

Review commits from Task 1–3 for: mode-only RED bypass, malformed decision metadata fail-open, stale detection regression, schema migration breakage, and sensitive data in errors. Confirm each new branch has direct regression coverage.

- [ ] **Step 4: Commit verification-only corrections if required**

If review finds a defect, add a focused failing test, make minimal correction, rerun affected suite, then commit only tracked modified paths:

```bash
git add $(git diff --name-only)
git commit -m "fix: address review regression"
```

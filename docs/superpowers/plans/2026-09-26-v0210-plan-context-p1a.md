# v0.2.10 Plan Reconciliation P1A Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make enabled Plan Reconciliation artifacts authoritative, freshness-bound Context sources while projecting only a compact recovery summary.

**Architecture:** Refactor the P0 plan loader onto audited `source_access`, then reuse loaded normalized documents for a pure summary projection. Extend Context's conditional source registry, model, closed schema, integrity checks, and projection version without reading adjacent plan artifacts for disabled or FAST tasks.

**Tech Stack:** Python 3.11, PyYAML, jsonschema, pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-v0210-plan-context-p1a-design.md`

## Global Constraints

- Effective enablement requires persisted `enabled: true` and STANDARD/STRICT profile; FAST/Q1 never reads plan artifacts.
- compact and full modes project identical summary only; never inline plan/execution bodies.
- Missing enabled artifacts publish blocked Context with null hashes/references; malformed present artifacts fail `CONTEXT_SCHEMA_INVALID`.
- Stale fingerprint publishes blocked Context with `next_plan_item: null`.
- Projection helper performs no file I/O and never invokes reconciliation.
- `PROJECTION_VERSION` increments from `2` to `3`; old saved Context fails closed.
- No adapter exemption, new dependency, blocker code, evidence type, CLI, or Q3 task-level enforcement.
- Run focused related tests only; full repository suite is forbidden.
- Any plan task commit remains subject to explicit Harness commit authorization.

## Review Focus

- FAST task with ad hoc `enabled: true` beside malformed artifacts must remain unread and fresh.
- Enabled one-file-missing state must distinguish authoritative absence from malformed present content.
- Named plan hashes, generic `files` entries, and references must agree for present, missing, and disabled states.
- Terminal proof/disposition blockers must yield blocked summary without inventing `next_plan_item`.
- Mutation between freshness capture, source load, and publication must fail stale with no partial Context bundle.

---

### Task 1: Source-access-safe canonical loader and pure summary

**Files:**
- Modify: `src/harness/plan_reconciliation.py`
- Modify: `src/harness/context/dependency_closure.py`
- Modify: `tests/test_task_contract.py`
- Modify: `tests/test_context_dependency_closure.py`

**Interfaces:**
- Produces: `effective_plan_reconciliation(task: dict) -> dict` returning `{ "enabled": false }` or enabled config with `mode`.
- Produces: `load_plan_artifacts(harness_dir: Path, *, optional: bool) -> tuple[dict | None, dict | None]` using `source_access`; optional mode preserves per-file absence but raises `PlanArtifactError` for malformed present content.
- Produces: `plan_context_summary(task: dict, plan: dict | None, execution: dict | None, blockers: Iterable[GateBlocker]) -> dict` with no I/O.
- Preserves: `validate_plan_initialization` and `validate_plan_reconciliation` public behavior.

- [ ] **Step 1: Write failing loader and effective-enable regression tests**

Add focused tests proving: optional loading returns `(None, None)` for absence; malformed present YAML raises `PlanArtifactError`; FAST plus ad hoc enabled config returns `{enabled: false}`; STANDARD enabled config preserves `mode`.

- [ ] **Step 2: Run loader tests and verify RED**

Run: `pytest tests/test_task_contract.py -k 'plan_artifacts or effective_plan_reconciliation' -q`

Expected: FAIL because public loader/effective-enable functions do not exist and current loader performs direct `Path` I/O.

- [ ] **Step 3: Refactor canonical reads onto `source_access`**

Implement the two loader interfaces above. Replace direct `Path.read_text`, `Path.is_file`, and Requirement/Invariant reads in this module with `source_access` calls. Keep static schema/duplicate-ID failures as `PlanArtifactError`; keep semantic outcomes as existing issues/blockers.

- [ ] **Step 4: Write failing pure-summary tests**

Cover disabled shape, missing artifacts, stale fingerprint, first missing/nonterminal item in canonical order, all-terminal null item, and terminal `PLAN_PROOF_MISSING` with null item. Assert `final_status` only examines blocker codes beginning `PLAN_`.

- [ ] **Step 5: Implement `plan_context_summary`**

Use loaded documents only. Return `{enabled: false}` for ineffective configuration. For enabled configuration include `mode`, nullable `next_plan_item`, and `pass|blocked`; never call `validate_plan_reconciliation`.

- [ ] **Step 6: Extend and verify dependency closure**

Add `plan_reconciliation` to `ALLOWED`, not `ADAPTERS`. Add a regression assertion that it is absent from adapters, then run:

`pytest tests/test_context_dependency_closure.py tests/test_task_contract.py -q`

Expected: PASS with no `DIRECT_IO` or undeclared dependency.

- [ ] **Step 7: Commit Task 1 after authorization**

```bash
git add src/harness/plan_reconciliation.py src/harness/context/dependency_closure.py tests/test_task_contract.py tests/test_context_dependency_closure.py
git commit -m "refactor: make plan reconciliation context-safe"
```

### Task 2: Conditional plan freshness and projection version 3

**Files:**
- Modify: `src/harness/context/freshness.py`
- Modify: `src/harness/context/read_scope.py` only if the generic `versions["files"]` admission is insufficient
- Modify: `tests/test_context_freshness_property.py`
- Modify: `tests/test_context_protected_freshness.py`
- Modify: `tests/test_freshness_version_scope.py`

**Interfaces:**
- Consumes: `effective_plan_reconciliation(task)` from Task 1.
- Produces: `capture()` with `projection_version: 3`, nullable `plan_hash` / `plan_execution_hash`, and conditional plan keys in `files`.
- Preserves: `context_read_scope(harness_dir, versions)` derives allowed files from the captured `files` map; no unconditional plan paths.

- [ ] **Step 1: Write failing disabled freshness tests**

Assert disabled and FAST/ad-hoc-enabled tasks omit both plan keys from `generated_from.files`, set both named hashes to null, and produce the same capture before and after malformed adjacent plan files are created or edited.

- [ ] **Step 2: Run disabled tests and verify RED**

Run: `pytest tests/test_context_protected_freshness.py tests/test_freshness_version_scope.py -k plan -q`

Expected: FAIL because plan named hashes and conditional registry do not exist.

- [ ] **Step 3: Write failing enabled presence tests**

For enabled STANDARD task, assert each plan key exists in `files`; present bytes produce SHA-256, missing produces null; named hashes equal those entries. Assert creation, deletion, and edit change capture.

- [ ] **Step 4: Implement conditional finite registry**

Keep plan files out of `ROOT_FILES`. During bootstrap, read only `current-task.yaml` to compute effective enablement. Thread selected plan names through `version_scope` and `_capture_versions`; stat/version those names only when effective enablement is true. Set `PROJECTION_VERSION = 3`.

- [ ] **Step 5: Verify read-scope behavior**

If `context_read_scope` already admits all keys in `versions["files"]`, leave it unchanged and document that result in the task ledger. Otherwise make the smallest change needed to admit only captured plan keys.

Run: `pytest tests/test_context_freshness_property.py tests/test_context_protected_freshness.py tests/test_freshness_version_scope.py -q`

Expected: PASS.

- [ ] **Step 6: Commit Task 2 after authorization**

```bash
git add src/harness/context/freshness.py src/harness/context/read_scope.py tests/test_context_freshness_property.py tests/test_context_protected_freshness.py tests/test_freshness_version_scope.py
git commit -m "feat: bind enabled plan artifacts to context freshness"
```

### Task 3: Authoritative Context summary, references, manifest, and schema

**Files:**
- Modify: `src/harness/context/source.py`
- Modify: `src/harness/context/model.py`
- Modify: `src/harness/context/builder.py`
- Modify: `src/harness/context/integrity.py`
- Modify: `src/harness/schemas/context.schema.json`
- Modify: `tests/test_context_builder.py`
- Modify: `tests/test_context_integrity.py`
- Modify: `tests/test_schema_resources.py`

**Interfaces:**
- Consumes: Task 1 loader/summary and Task 2 version map.
- Produces: `AuthoritativeContext.plan: dict | None` and `.plan_execution: dict | None`.
- Produces: `ControlCore.plan_reconciliation: dict`.
- Produces: Context references `plan.yaml` / `plan-execution.yaml` only for effectively enabled tasks, each reference object or null.
- Produces: manifest source `plan_reconciliation` with `loaded` true only when both documents exist, `hash: digest({"plan": versions["plan_hash"], "execution": versions["plan_execution_hash"]})`, canonical plan item `total` (zero when plan is absent), and `included: 0`.

- [ ] **Step 1: Write failing source-loading/error tests**

In `tests/test_context_builder.py`, add helpers to enable STANDARD Plan Reconciliation and write matching artifacts. Assert enabled present documents and canonical refs load; both/one missing remain `None` plus null refs; malformed present content raises `CONTEXT_SCHEMA_INVALID`; FAST ad-hoc-enabled malformed content is ignored.

- [ ] **Step 2: Run source tests and verify RED**

Run: `pytest tests/test_context_builder.py -k plan_reconciliation -q`

Expected: FAIL because authoritative model/source fields do not exist.

- [ ] **Step 3: Extend source and model**

Load optional plan artifacts before `quality_gate.assess_gate`; map `PlanArtifactError` to `ContextBuildError("CONTEXT_SCHEMA_INVALID", ...)`. Populate refs only on effective enabled path. Pass normalized documents into `AuthoritativeContext`.

- [ ] **Step 4: Write failing projection and tamper tests**

Assert compact/full summary equality, exact disabled/enabled shapes, first nonterminal order, stale null item, terminal proof blocker null item, and rejection when `control.plan_reconciliation` is altered.

- [ ] **Step 5: Extend builder and integrity**

Add summary via Task 1 helper. Recompute from authoritative documents and current assessment in `_check_document`. Add present plan references to omission accounting as `body_not_inlined`; never add absent/disabled entries.

- [ ] **Step 6: Extend manifest and closed schema**

Add plan source accounting without bodies. Update `context.schema.json`: require `control.plan_reconciliation`; encode disabled shape versus enabled required fields; require projection version `3`; add nullable named plan hashes and their cross-checks in integrity tests.

- [ ] **Step 7: Verify Task 3 focused files**

Run: `pytest tests/test_context_builder.py tests/test_context_integrity.py tests/test_schema_resources.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 3 after authorization**

```bash
git add src/harness/context/source.py src/harness/context/model.py src/harness/context/builder.py src/harness/context/integrity.py src/harness/schemas/context.schema.json tests/test_context_builder.py tests/test_context_integrity.py tests/test_schema_resources.py
git commit -m "feat: project plan reconciliation into context"
```

### Task 4: End-to-end freshness, publication, and FAST regressions

**Files:**
- Modify: `tests/test_context_cli.py`
- Modify: `tests/test_context_lifecycle_integration.py`
- Modify: `tests/test_context_read_scope.py`
- Modify: affected Context tests only if a concrete uncovered seam remains

**Interfaces:**
- Consumes: complete P1A Context projection from Tasks 1–3.
- Produces: end-to-end proof that generation, saved validation, and atomic publication obey conditional authority.

- [ ] **Step 1: Add enabled artifact mutation regressions**

Build/save Context, then create/delete/edit each enabled plan artifact and assert saved validation raises `CONTEXT_STALE`. Inject mutation during generation and assert no partial `current.yaml`, `manifest.yaml`, or `evidence.yaml` publication.

- [ ] **Step 2: Add disabled and FAST isolation regressions**

Generate Context beside malformed artifacts for disabled and FAST/ad-hoc-enabled tasks. Assert summary is `{enabled: false}`, generated hashes are null, `files` omits both keys, and saved Context stays fresh after artifact edits.

- [ ] **Step 3: Add projection migration regression**

Alter saved `generated_from.projection_version` to `2` and assert closed schema rejects it with `CONTEXT_SCHEMA_INVALID`.

- [ ] **Step 4: Run end-to-end focused tests**

Run: `pytest tests/test_context_cli.py tests/test_context_lifecycle_integration.py tests/test_context_read_scope.py tests/test_context_dependency_closure.py -q`

Expected: PASS, including FAST lazy-import/source-scope regressions.

- [ ] **Step 5: Run complete P1A focused verification through Harness evidence**

Use one related unit-test evidence command covering only all files changed by Tasks 1–4. Bind P1A Requirement/Invariant cases, collect build evidence into `/tmp`, run complexity review, review outcome, and Gate. Do not run the full repository suite.

- [ ] **Step 6: Commit Task 4 after authorization**

```bash
git add tests/test_context_cli.py tests/test_context_lifecycle_integration.py tests/test_context_read_scope.py
git commit -m "test: verify plan context integrity lifecycle"
```

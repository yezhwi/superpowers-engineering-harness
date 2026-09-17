# v0.2.8 Decision Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Remove steady-state historical decision body reads while preserving fail-closed Context freshness.

**Architecture:** `decisions/index.yaml` stores canonical decision member metadata and content hashes. Decision writes update body and index atomically. Context validates index against directory membership and hashes, then only loads current-task or explicitly referenced body files.

**Spec:** `docs/superpowers/specs/2026-09-17-v028-important-review-fixes-design.md`

## Constraints

- Index metadata: `id`, `task_id`, `status`, `supersedes`, `superseded_by`, `sha256`.
- Direct `DEC-*.yaml` membership must exactly equal index membership.
- Missing, duplicate, malformed, or hash-mismatched index entries fail closed.
- Missing index migrates once under existing task/telemetry lock, then atomically publishes index.
- Never read unreferenced historical decision bodies after migration.

### Task 1: Index Schema, Migration, and Atomic Decision Writes

**Files:**
- Modify: `src/harness/decision.py`
- Modify: `src/harness/context/freshness.py`
- Test: `tests/test_decision.py`
- Test: `tests/test_context_freshness_property.py`

- [ ] Write failing tests: no-index fixture migrates to index; index body hash mismatch raises stable stale error; extra/missing `DEC-*.yaml` entry raises stable schema error; `propose`, `accept`, and `reject` leave valid index.
- [ ] Run only new tests. Expect missing index and mismatch assertions fail.
- [ ] Add index schema validator and `load_decision_index()`. Build migration by fully loading legacy decisions once, extracting metadata and sha256, then atomically write index under existing lock.
- [ ] Change decision mutation transaction to stage body changes and rebuilt index in same publish operation.
- [ ] Make freshness include index hash and validate index member hashes before accepting Context freshness.
- [ ] Run `pytest -q tests/test_decision.py tests/test_context_freshness_property.py tests/test_freshness_version_scope.py`.
- [ ] Commit: `git commit -m "feat: index decision metadata"`.

### Task 2: Context Selective Decision Loading

**Files:**
- Modify: `src/harness/context/source.py`
- Modify: `src/harness/context/model.py`
- Modify: `src/harness/context/selector.py`
- Modify: `src/harness/context/builder.py`
- Modify: `src/harness/context/integrity.py`
- Test: `tests/test_context_automatic.py`
- Test: `tests/test_context_builder.py`
- Test: `tests/test_context_integrity.py`

- [ ] Write failing fixture with one current decision and 100 `HISTORICAL-BODY-*` decisions. After index exists, monkeypatch `decision.load_decision`; compact build must call it only for current task body, must omit historical body text, and must retain historical Layer 2 refs.
- [ ] Add failing tests for supersession, `impact.contracts` `DEC-<id>:` label, and loaded interface contract `decision_refs`; each must load target body as Layer 2 only. Missing target must raise `CONTEXT_REFERENCE_BROKEN`.
- [ ] Run new tests. Expect current full-loader path to load all decisions.
- [ ] Source loader reads validated index, registers every index reference, loads current-task bodies plus exact explicit ID closure, and rejects index/body ID disagreement.
- [ ] Selector uses index metadata for historical omission accounting; Control Core retains full current-task ACCEPTED decisions only.
- [ ] Run `pytest -q tests/test_context_automatic.py tests/test_context_builder.py tests/test_context_integrity.py tests/test_context_selector.py tests/test_context_read_scope.py tests/test_context_freshness_property.py`.
- [ ] Commit: `git commit -m "fix: defer historical decision body loading"`.

### Task 3: Final Verification

- [ ] Run `pytest -q`.
- [ ] Run `ruff check src tests` and `git diff --check`.
- [ ] Review new code for index/body mismatch fail-open, migration races, and legacy compatibility.

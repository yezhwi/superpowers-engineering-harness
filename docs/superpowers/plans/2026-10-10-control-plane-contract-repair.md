# Control-Plane Contract Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair protected-path adoption, immutable evidence receipts, early case validation, diagnosability workflow guidance, and plan-proof diagnostics.

**Architecture:** Add versioned, task-aware user-change snapshots so v1 keeps current aggregate semantics and v2 can remove an adopted path without rebasing others. Preserve immutable evidence receipts with suffix allocation and deterministic equivalence selection. Keep existing blocker codes/state transitions while improving deterministic validation and messages.

**Tech Stack:** Python 3.11, pytest, JSON Schema, YAML, Markdown skills.

**Spec:** `docs/superpowers/specs/2026-10-10-control-plane-contract-repair-design.md`

## Global Constraints

- Do not weaken fresh evidence, exact receipt byte digest, unadopted user-path protection, or automated node-coverage rules.
- Preserve v1 `risk.user_changes: {paths, fingerprint}` behavior.
- v2 stores optional `path_fingerprints`; task schema remains backward compatible.
- Keep `PLAN_PROOF_MISSING` and `recover_to=VERIFYING`; do not add plan-status JSON fields.
- Invalid covered test cases fail before subprocess execution or evidence persistence with exit 2 and `COVERED_TEST_CASE_INVALID`.
- Root `SKILL.md` and `skills/engineering-harness/SKILL.md` must remain byte-identical.
- No complexity-review schema.

## Review Focus

- Legacy protected snapshots modified before adoption reject without mutating task bytes.
- v2 adoption removes only target path; unchanged remaining path does not become modified.
- Seventeenth duplicate fresh receipt does not trigger auto-proof candidate limit.
- Reuse never selects receipt with different case IDs, runtime, HEAD, workspace, scope, command, or covered tests.
- Refresh-proof hint repeats every current item evidence reference because refresh replaces list.

---

### Task 1: Versioned protected-path snapshots and adoption

**Files:**
- Modify: `src/harness/workspace.py:342-356`
- Modify: `src/harness/controlplane.py:2739-2795`
- Modify: `src/harness/plan_automation.py:87-116`
- Modify: `src/harness/quality_gate.py:356` and user-change call sites
- Modify: `src/harness/schemas/task.schema.json:user_changes`
- Test: `tests/test_workspace.py`
- Test: `tests/test_task_contract.py`
- Test: `tests/test_plan_automation.py`
- Test: `tests/test_plan_mutation_cli.py`
- Test: `tests/test_quality_gate.py`

**Interfaces:**
- Produces: `protected_user_changes_fingerprint(user_changes, *, repo_root=None) -> str`, version-aware current aggregate.
- Produces: v2 `risk.user_changes.path_fingerprints`, mapping path to canonical classification-time path contribution.
- Consumes: existing `harness impact adopt-path <path>` task mutation route.

- [ ] **Step 1: Write failing v2 adoption tests**

Add tests proving a v2 snapshot with two protected paths: after adopting one changed path, the remaining unchanged path has matching current/stored aggregate; adopted path is removed from `risk.user_changes.paths` and `scope.protected_user_paths`, and added to `scope.owned_paths`; it is usable as plan surface.

- [ ] **Step 2: Run v2 adoption tests to verify RED**

Run: `pytest tests/test_plan_mutation_cli.py tests/test_plan_automation.py tests/test_quality_gate.py -q`

Expected: failure because adoption does not persist v2 snapshot updates and plan automation still accepts only path-list fingerprint callback.

- [ ] **Step 3: Write failing legacy-snapshot safety tests**

Add tests proving v1 unchanged snapshot migrates during adoption; v1 snapshot whose aggregate differs from current value exits with `USER_CHANGE_BASELINE_STALE` and leaves current-task bytes unchanged; adoption of path absent from protection list leaves baseline unchanged.

- [ ] **Step 4: Run legacy tests to verify RED**

Run: `pytest tests/test_task_contract.py tests/test_plan_mutation_cli.py tests/test_workspace.py -q`

Expected: failure because schema lacks v2 field and adoption rebases from current contents.

- [ ] **Step 5: Implement versioned snapshot helpers and schema**

In `workspace.py`, keep legacy path-list aggregate behavior for v1. Add canonical per-path contribution and deterministic v2 aggregation helpers plus task-aware `protected_user_changes_fingerprint`. Extend `task.schema.json` with optional v2 `path_fingerprints` and version marker/shape required by implementation. Ensure classification writes v2 snapshots. Replace FAST and `mechanical_surface_facts` path-list fingerprint calls with task-aware helper; update injected test seams accordingly.

- [ ] **Step 6: Implement atomic adoption migration**

In `cmd_impact`, validate/migrate v1 only when legacy current aggregate equals stored aggregate. On mismatch return `USER_CHANGE_BASELINE_STALE` without save. For protected v2 path, atomically update owned/protected scope lists, paths, path contribution map, and aggregate; leave non-protected requests behavior unchanged.

- [ ] **Step 7: Run Task 1 tests to verify GREEN**

Run: `pytest tests/test_workspace.py tests/test_task_contract.py tests/test_plan_automation.py tests/test_plan_mutation_cli.py tests/test_quality_gate.py -q`

Expected: PASS.

### Task 2: Immutable evidence receipts and deterministic proof selection

**Files:**
- Modify: `src/harness/collect_evidence.py:198-225, 760-870`
- Modify: `src/harness/paths.py:28-41` if filename allocation belongs in path module
- Modify: `src/harness/plan_automation.py:45-84, 201-244`
- Modify: `src/harness/plan_reconciliation.py:363-399, 650-790`
- Test: `tests/test_evidence.py`
- Test: `tests/test_plan_automation.py`
- Test: `tests/test_plan_mutation.py`

**Interfaces:**
- Produces: immutable receipt sequence `<identity>.json`, `<identity>-2.json`, ….
- Produces: deterministic receipt preference: highest numeric suffix for equivalent identity/coverage.
- Consumes: existing `can_reuse_evidence` equality predicate and `harness plan refresh-proof` repeated `--evidence` CLI syntax.

- [ ] **Step 1: Write failing evidence immutability/reuse tests**

Add tests showing two ordinary same-identity related runs produce original then `-2` file without changing original bytes; `--reuse-if-valid` chooses newest fully `can_reuse_evidence`-matching receipt and does not execute command; different covered case IDs do not reuse.

- [ ] **Step 2: Run evidence tests to verify RED**

Run: `pytest tests/test_evidence.py -q`

Expected: failure because existing output path overwrites deterministic identity file.

- [ ] **Step 3: Write failing auto-proof selection tests**

Add tests with 17 fresh equal-coverage receipts proving selection picks highest suffix without `PLAN_AUTO_LIMIT_EXCEEDED`; add distinct equal-size covers proving `PLAN_AUTO_PROOF_AMBIGUOUS` remains.

- [ ] **Step 4: Run auto-proof tests to verify RED**

Run: `pytest tests/test_plan_automation.py -q`

Expected: failure because duplicate candidates exceed limit or are ambiguous.

- [ ] **Step 5: Implement receipt allocation and reuse scan**

Allocate lowest unused suffix for non-reuse collection. Scan evidence directory for fresh records and apply existing `can_reuse_evidence` for reuse; choose highest suffix deterministically. Keep generic and finding evidence naming behavior unchanged unless same immutable identity rule applies by specification.

- [ ] **Step 6: Implement coverage-mask folding**

Before `_MAX_CANDIDATES` and minimum-cover calculation, fold candidate records by coverage bitmask and retain highest suffix reference per mask. Preserve ambiguity for distinct minimum covers.

- [ ] **Step 7: Improve stale-proof remedy**

Build stale proof message from complete item `evidence_refs`; emit one refresh command with repeated `--evidence <ref>` for every current reference. Preserve `PLAN_PROOF_MISSING` and `VERIFYING` recovery.

- [ ] **Step 8: Run Task 2 tests to verify GREEN**

Run: `pytest tests/test_evidence.py tests/test_plan_automation.py tests/test_plan_mutation.py -q`

Expected: PASS.

### Task 3: Early case validation and node-specific proof diagnostics

**Files:**
- Modify: `src/harness/collect_evidence.py:760-870`
- Modify: `src/harness/plan_reconciliation.py:451-479, 650-790`
- Test: `tests/test_evidence.py`
- Test: `tests/test_plan_mutation.py`
- Test: `tests/test_plan_reporting.py`

**Interfaces:**
- Produces: `COVERED_TEST_CASE_INVALID` exit code 2 before command execution/write.
- Produces: one existing-code `PLAN_PROOF_MISSING` message containing all missing `REQ/TC` or `INV/TC` and pytest node pairs.

- [ ] **Step 1: Write failing covered-case validation tests**

Add CLI tests passing `REQ-004/TC-004` and a valid value together. Assert exit 2, `COVERED_TEST_CASE_INVALID`, no command side effect, and no evidence file. Add valid bare `TC-004` acceptance test.

- [ ] **Step 2: Run validation tests to verify RED**

Run: `pytest tests/test_evidence.py -q`

Expected: failure because invalid value is currently written.

- [ ] **Step 3: Implement shared case-ID validator**

Validate every parsed covered case before output path selection, reuse lookup, subprocess invocation, or write. Route every evidence command entry point through same helper.

- [ ] **Step 4: Write failing missing-node diagnostic test**

Create automated contract case with multiple nodes and evidence covering only one. Assert exactly one `PLAN_PROOF_MISSING`, `recover_to=VERIFYING`, and message includes missing parent reference and node ID; assert status projection fields remain unchanged.

- [ ] **Step 5: Run diagnostic test to verify RED**

Run: `pytest tests/test_plan_mutation.py tests/test_plan_reporting.py -q`

Expected: failure because current message is generic.

- [ ] **Step 6: Implement detailed proof assessment**

Derive all missing automated coverage pairs once; pass details into existing item blocker message without changing blocker count, code, recovery target, or status JSON projection.

- [ ] **Step 7: Run Task 3 tests to verify GREEN**

Run: `pytest tests/test_evidence.py tests/test_plan_mutation.py tests/test_plan_reporting.py -q`

Expected: PASS.

### Task 4: Diagnosability workflow documentation contract

**Files:**
- Modify: `SKILL.md`
- Modify: `skills/engineering-harness/SKILL.md`
- Modify: `skills/diagnosability-review/SKILL.md`
- Test: `tests/test_readme_docs.py`
- Test: `tests/test_cli_diagnosability.py`

**Interfaces:**
- Produces: identical root and engineering-harness skill bytes.
- Consumes: CLI acceptance of diagnosability review in `VERIFYING` and `REVIEWING`.

- [ ] **Step 1: Write failing workflow-document tests**

Extend documentation tests to assert root workflow tells Q3 users to persist diagnosability evidence before `VERIFYING -> REVIEWING`, Q2 condition remains `observability.required: true`, and diagnosability skill names both accepted states.

- [ ] **Step 2: Run documentation tests to verify RED**

Run: `pytest tests/test_readme_docs.py tests/test_cli_diagnosability.py -q`

Expected: failure because current skills place diagnosability review only in REVIEWING.

- [ ] **Step 3: Update skills synchronously**

Update diagnosability-review state wording and engineering-harness phase/routing wording. Copy final engineering-harness bytes to root `SKILL.md`; do not alter Q2 condition or CLI state behavior.

- [ ] **Step 4: Run Task 4 tests to verify GREEN**

Run: `pytest tests/test_readme_docs.py tests/test_cli_diagnosability.py -q`

Expected: PASS.

### Task 5: Integration verification

**Files:**
- Modify: only files required by prior tasks
- Test: declared task-contract and changed-module tests only

- [ ] **Step 1: Run focused regression suite**

Run: `pytest tests/test_workspace.py tests/test_task_contract.py tests/test_plan_mutation_cli.py tests/test_quality_gate.py tests/test_evidence.py tests/test_plan_automation.py tests/test_plan_mutation.py tests/test_plan_reporting.py tests/test_readme_docs.py tests/test_cli_diagnosability.py -q`

Expected: PASS.

- [ ] **Step 2: Inspect final diff**

Run: `git diff --check && git diff -- src/harness tests SKILL.md skills docs/superpowers/specs docs/superpowers/plans`

Expected: no whitespace errors; only scoped control-plane, tests, skills, spec, and plan changes.

# v0.3.0 Architecture Scope & Drift P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship canonical Architecture model, deterministic ownership and Git attribution, Alignment seal v2, Q2/Q3 Architecture Gate, P0 mutation/read CLI, and lifecycle compatibility.

**Architecture:** Pure `harness.architecture` domain module owns validation, fingerprinting, resolution, and assessment types. Existing `workspace`, `alignment`, `quality_gate`, `source_access`, `transaction`, and task-replacement seams own Git, freeze, Gate, I/O, atomicity, and lifecycle effects. No second freeze, Gate, lock, cache, state, or File Scope Gate.

**Tech Stack:** Python 3.11+, dataclasses, PyYAML, jsonschema, pytest, existing Harness CLI and transaction/Git adapters.

**Spec:** `docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md`

## Global Constraints

- Architecture artifact is `.harness/architecture.yaml`; canonical YAML remains authority.
- Configuration is `gate.architecture.mode: off | required`; missing config means `off`.
- FAST/Q1 and mode-off paths do not read Architecture artifact/schema or execute resolver/Architecture Git collection.
- Required checks apply only to Q2/Q3.
- No automatic module, dependency, ownership, or scope inference.
- Reuse Alignment seal; no `architecture-freeze.yaml`.
- Only `harness align freeze` publishes v2; off phase-entry may bootstrap missing legacy v1 only.
- Required phase-entry, Gate, and Context never bootstrap a missing seal.
- Missing required artifact is blocker data; malformed present artifact fails closed.
- Git attribution includes committed, staged, worktree, and untracked layers; every query excludes `.harness` via `_PRODUCT_EXCLUDE`.
- Preserve docs/tests/support paths; never use `business_paths()` for Architecture.
- Reuse telemetry lock and atomic publication; exact semantic retry leaves bytes unchanged.
- Hard bounds are exact: canonical YAML: 1 MiB UTF-8; maximum 256 modules; maximum 1024 ownership rules; maximum 64 declared modules/task; maximum 32 dependencies/module; maximum 16 evidence records/module; module ID: 64 code points; name: 128 code points; responsibility: 512 code points; path/pattern/empty reason: 512 code points. Exceeding any bound is Invalid Harness State.
- Every implementation commit requires fresh explicit user authorization; commit steps below are checkpoints, not standing authorization.
- Run only focused related tests; do not run unrestricted repository `pytest`.

## Review Focus

- Same path has cached `M` and worktree `D`: retain both typed facts, resolve ownership once, derive current existence from Git index.
- Required task deletes `scope.modules` after v2 freeze: report `CONTRACT_CHANGED`, never normalize to support-only.
- Off task with frozen Alignment and missing seal enters implementation: publish legacy v1 only, never v2.
- Task replacement with v2/required seal and template default off: restore required from trusted same-task seal.
- Architecture artifact missing while independent evidence and Plan blockers exist: emit stable Architecture blocker and preserve independent blockers in same assessment.

---

### Task 1: Architecture Schema and Pure Domain Model

**Files:**
- Create: `src/harness/architecture.py`
- Create: `src/harness/schemas/architecture.schema.json`
- Modify: `src/harness/schema_resources.py`
- Test: `tests/test_architecture.py`
- Test: `tests/test_schema_resources.py`

**Interfaces:**
- Produces: `ArchitectureError(code: str)`, `ArchitectureModel`, `OwnershipResolution`, `load_architecture_document(document: object) -> ArchitectureModel`, `architecture_fingerprint(model: ArchitectureModel) -> str`, `resolve_ownership(model: ArchitectureModel, path: str) -> OwnershipResolution`.
- Consumes: `schema_resources.read_schema(name)` only for schema validation; domain resolution performs no file or Git I/O.

- [ ] **Step 1: Write failing schema and bound tests**

Add boundary and boundary+1 tests for canonical YAML: 1 MiB UTF-8; maximum 256 modules; maximum 1024 ownership rules; maximum 32 dependencies/module; maximum 16 evidence records/module; module ID: 64 code points; name: 128 code points; responsibility: 512 code points; path/pattern/empty reason: 512 code points. `architecture.schema.json enforces 256 modules`; it does not enforce per-task declared scope. Also cover `OWN-nnn` IDs, production/shared/support cardinality, evidence paths, dependency references, self-dependency rejection, allowed multi-module cycles, duplicate IDs/rules, `allow_empty`/`empty_reason`, and schema registration/package loading. Task 4 separately proves `task.schema.json enforces 64 declared modules/task`.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_architecture.py tests/test_schema_resources.py -q`
Expected: FAIL because schema and interfaces do not exist.

- [ ] **Step 3: Implement model loading and semantic validation**

Use immutable dataclasses internally. Raise stable `ArchitectureError` codes; never infer missing fields. Normalize ordering only for comparisons/fingerprints, not by rewriting caller data.

- [ ] **Step 4: Write failing resolver/fingerprint tests**

Cover literal, one-segment `*`, trailing `/**`, forbidden glob syntax, exact/literal/segment score, equal-score ambiguity, shared owner set, support no-module result, canonical POSIX rejection, and semantic hash stability across YAML order/comments.

- [ ] **Step 5: Implement pure resolver and fingerprint**

Fingerprint canonical semantic values with UTF-8 JSON, sorted keys and normalized collections, fixed separators, and `sha256:<hex>` output.

- [ ] **Step 6: Run GREEN**

Run: `pytest tests/test_architecture.py tests/test_schema_resources.py -q`
Expected: PASS.

- [ ] **Step 7: Commit checkpoint**

Request explicit authorization, then stage only files listed above and commit `feat: add architecture domain model`.

---

### Task 2: Typed Four-Layer Git Change Adapter

**Files:**
- Modify: `src/harness/workspace.py`
- Test: `tests/test_workspace.py`
- Test: `tests/test_workspace_untracked_scope.py`
- Create: `tests/test_architecture_workspace.py`

**Interfaces:**
- Produces: `ArchitectureChangeRecord(kind: Literal["added", "modified", "deleted", "untracked"], path: str)`, `architecture_changes(base_commit: str, repo_root: Path | None = None) -> tuple[ArchitectureChangeRecord, ...]`, `architecture_path_index(repo_root: Path | None = None) -> tuple[str, ...]`.
- Consumes: existing `verify_git_ref()`, `_run()`, `_PRODUCT_EXCLUDE`, `WorkspaceError`.

- [ ] **Step 1: Write failing adapter tests**

Create real temporary Git repositories covering committed, cached-only, worktree-only, untracked, rename as D+A under `--no-renames`, copy as destination `added`, same-path multi-kind, docs/tests inclusion, `.harness` exclusion, UTF-8/path rejection, and `U/X/B` fail-closed behavior.

- [ ] **Step 2: Add review-focus counterexample tests**

Assert cached `M` plus worktree `D` yields both records; current-path index comes from tracked minus `ls-files --deleted` plus untracked, not record reduction.

- [ ] **Step 3: Run RED**

Run: `pytest tests/test_architecture_workspace.py tests/test_workspace.py tests/test_workspace_untracked_scope.py -q`
Expected: FAIL because typed adapter is absent.

- [ ] **Step 4: Implement fixed Git queries**

Use exact committed `<base>..HEAD`, worktree `HEAD`, cached `--cached HEAD`, untracked, tracked, and deleted queries from spec. Decode `-z`, sort/dedupe by `(path, kind)`, preserve different kinds for same path, and raise `WorkspaceError("ARCHITECTURE_CHANGESET_INVALID")` for invalid status/path.

- [ ] **Step 5: Run GREEN**

Run focused command from Step 3.
Expected: PASS.

- [ ] **Step 6: Commit checkpoint**

Request authorization, then commit `feat: add typed architecture change adapter`.

---

### Task 3: Architecture Store, Publication, and Read CLI

**Files:**
- Create: `src/harness/architecture_store.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_architecture_cli.py`
- Test: `tests/test_context_dependency_closure.py`
- Test: `tests/test_schema_resources.py`

**Interfaces:**
- Produces: `load_architecture(harness_dir: Path, *, required: bool) -> ArchitectureModel | None`, `publish_architecture(harness_dir: Path, candidate: Path) -> bool`, and CLI commands `architecture publish|validate|resolve|check` plus `architecture scope add|remove`.
- Consumes: Task 1 domain interface, `source_access`, `transaction.stage/publish`, `telemetry_lock`, current task state.

- [ ] **Step 1: Write failing mutation tests**

Assert SPECIFYING-only publication/scope edits; IMPLEMENTING returns `ARCHITECTURE_REALIGNMENT_REQUIRED` with zero writes, and every other non-SPECIFYING state also performs zero writes. Assert candidate-before-write validation, evidence path validation, duplicate/no-op byte stability, rollback, lock use, and no automatic freeze/Decision/Finding creation. Publication must use Task 2 canonical path index—not directory traversal—to require every `allow_empty: false` rule to match at least one tracked or task-attributable path, reject duplicate rules, and reject every same-score conflict.

- [ ] **Step 2: Write failing read-command tests**

Assert validate/resolve/check are read-only, deterministic text/JSON, body-free, and reject malformed present artifacts. `architecture summary` is intentionally deferred to P1 because its interface is the Context-equivalent bounded projection.

- [ ] **Step 3: Run RED**

Run: `pytest tests/test_architecture_cli.py tests/test_context_dependency_closure.py tests/test_schema_resources.py -q`
Expected: FAIL because commands/store are absent.

- [ ] **Step 4: Implement store and CLI dispatch**

Keep pure domain in `dependency_closure.ALLOWED`; do not add it to `ADAPTERS`. Store coordinates existing audited adapters and performs no direct `Path.read_*`, `exists`, glob, or subprocess calls inside trusted closure.

- [ ] **Step 5: Run GREEN**

Run focused command from Step 3.
Expected: PASS.

- [ ] **Step 6: Commit checkpoint**

Request authorization, then commit `feat: add architecture artifact commands`.

---

### Task 4: Gate and Task Schemas, Templates, and Explicit Scope

**Files:**
- Modify: `src/harness/schemas/gate.schema.json`
- Modify: `src/harness/schemas/task.schema.json`
- Modify: `src/harness/templates/gate.yaml`
- Modify: `src/harness/templates/current-task.yaml`
- Modify: `src/harness/init.py`
- Test: `tests/test_task_contract.py`
- Test: `tests/test_cli_init.py`
- Test: `tests/test_task_new.py`

**Interfaces:**
- Produces: validated `gate.architecture.mode`; optional legacy `scope.modules`, with required-mode presence enforced semantically at freeze rather than globally by schema.
- Consumes: existing init/template and schema validation paths.

- [ ] **Step 1: Write failing compatibility tests**

Assert missing `gate.architecture` means off, template explicitly writes off, old off tasks without modules remain valid, explicit `modules: []` is distinguishable from missing, duplicates fail, and init remains non-destructive. `task.schema.json enforces 64 declared modules/task`: 64 entries pass and 65 fail as Invalid Harness State; this limit does not reduce Architecture model modules below 256.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_task_contract.py tests/test_cli_init.py tests/test_task_new.py -q`
Expected: FAIL on new fields/defaults.

- [ ] **Step 3: Implement schema/template changes**

Do not globally require modules in task schema; freeze semantics in Task 5 enforce required-mode presence before defaulting.

- [ ] **Step 4: Run GREEN**

Run focused command from Step 2.
Expected: PASS.

- [ ] **Step 5: Commit checkpoint**

Request authorization, then commit `feat: add architecture task policy schema`.

---

### Task 5: Alignment Seal v2 and Conditional Legacy Bootstrap

**Files:**
- Modify: `src/harness/schemas/alignment-freeze.schema.json`
- Modify: `src/harness/alignment.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_alignment.py`
- Test: `tests/test_cli_alignment.py`
- Test: `tests/test_test_plan_transition.py`

**Interfaces:**
- Produces: `freeze_record(..., architecture_mode: str, architecture_fingerprint: str | None, declared_modules: tuple[str, ...]) -> dict` writing v2; `sealed_freeze_drift(..., bootstrap_legacy_off: bool, architecture_facts: ... | None) -> list[AlignmentIssue]` with no default bootstrap flag.
- Consumes: Task 1/3 validated Architecture model and Task 4 mode/scope fields.

- [ ] **Step 1: Write failing v1/v2 schema tests**

Assert `oneOf` accepts exact v1 and v2, rejects mixed/unknown fields, and required mode semantically rejects missing/v1/v2-off seal before Architecture artifact reads.

- [ ] **Step 2: Write failing writer/bootstrap tests**

Assert explicit `align freeze` always writes v2; required missing modules returns `ARCHITECTURE_SCOPE_DECLARATION_REQUIRED` with zero writes; explicit empty is valid support-only. Assert only off PLANNED→IMPLEMENTING and IMPLEMENTING→VERIFYING may bootstrap missing v1; required/Gate/read-only paths never write.

- [ ] **Step 3: Add v2 drift tests**

Cover mode, fingerprint, declared modules, task ID, Decision selections, and boundary refs; ensure comparison dispatches by actual seal version.

- [ ] **Step 4: Run RED**

Run: `pytest tests/test_alignment.py tests/test_cli_alignment.py tests/test_test_plan_transition.py -q`
Expected: FAIL on v2 and conditional bootstrap contracts.

- [ ] **Step 5: Implement v2 writer and version-aware validation**

Keep legacy v1 construction private to `bootstrap_legacy_off=True`. Preserve atomic two-file Alignment publication and existing unfreeze deletion behavior.

- [ ] **Step 6: Run GREEN**

Run focused command from Step 4.
Expected: PASS.

- [ ] **Step 7: Commit checkpoint**

Request authorization, then commit `feat: seal architecture scope in alignment v2`.

---

### Task 6: Task Replacement Preserves Trusted Architecture Mode

**Files:**
- Modify: `src/harness/task_replacement.py`
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_task_new.py`
- Test: `tests/test_cli_task_recovery.py`

**Interfaces:**
- Produces: private `trusted_architecture_mode(harness_dir: Path, old_task: dict) -> Literal["off", "required"]` used by both task-new and task-recover staging.
- Consumes: validated gate config and same-task schema-valid v2 seal.

- [ ] **Step 1: Write failing replacement tests**

Cover v2/required restoring required after template copy, v2/off, no-v2 fallback to validated current config, task-ID mismatch, malformed gate/seal atomic failure, preserved `architecture.yaml`, and archived old seal.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_task_new.py tests/test_cli_task_recovery.py -q`
Expected: FAIL because replacement currently resets mode to template off.

- [ ] **Step 3: Implement one shared staged-replacement helper**

Resolve trusted mode before template overwrite, write it into staged gate YAML, then publish through existing replacement transaction. Do not add a repository-policy file.

- [ ] **Step 4: Run GREEN**

Run focused command from Step 2.
Expected: PASS.

- [ ] **Step 5: Commit checkpoint**

Request authorization, then commit `fix: preserve architecture mode across task replacement`.

---

### Task 7: Architecture Assessment and Gate Integration

**Files:**
- Create: `src/harness/architecture_gate.py`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/blockers.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/review_outcome.py`
- Test: `tests/test_architecture_gate.py`
- Test: `tests/test_quality_gate.py`
- Test: `tests/test_convergence_cli.py`

**Interfaces:**
- Produces: `ArchitectureAssessment(blockers: tuple[GateBlocker, ...], model: ArchitectureModel | None, declared_modules: tuple[str, ...], relevant_modules: tuple[str, ...])`; `assess_architecture(harness_dir: Path, task: dict, gate_config: dict, *, allow_preflight: bool) -> ArchitectureAssessment`.
- Consumes: Tasks 1–6 interfaces, existing `GateBlocker`, `RECOVERY_POLICY`, blocker fingerprint, and `WorkspaceError` invalid-state path.

- [ ] **Step 1: Write failing isolation and mode tests**

Spy on source/schema/Git calls: FAST/Q1 and mode off may validate gate policy/static imports but never touch Architecture artifact/schema/resolver/Git adapter. Required Q2/Q3 reads after seal-mode precheck.

- [ ] **Step 2: Write failing blocker tests**

Cover seven repairable codes separately: required missing, scope invalid, evidence invalid, ownership empty/unresolved/ambiguous, and `ARCHITECTURE_SCOPE_DRIFT`. For only these codes assert category `implementation`, exact stable identities (`artifact:`, `module:`, `path:`, `ownership:`, `path:|module:`), and `RECOVERY_POLICY -> IMPLEMENTING`. For `CONTRACT_CHANGED`, assert source `artifact:.harness/alignment-freeze.yaml`, `RECOVERY_POLICY["CONTRACT_CHANGED"] == "ESCALATED"`, `is_user_authority_blocker()` true, and `select_recovery()` returns `None`; never rename `ARCHITECTURE_SCOPE_DRIFT` to `SCOPE_DRIFT_*`.

- [ ] **Step 3: Add attribution and independent-blocker tests**

Cover `preexisting_user_paths - owned_paths`, adopted paths, support paths, deleted-rule task locality, same-path records, and Architecture-local short-circuit while requirements/evidence/Plan blockers remain present. For one shared path with two undeclared owners, assert one `ARCHITECTURE_SCOPE_DRIFT` per unexpected shared owner and source `path:<path>|module:<id>` for each.

- [ ] **Step 4: Add preflight guidance tests**

Pin repairable state routes and separate `CONTRACT_CHANGED` authority matrix, including BLOCKED, Finding states, PLANNED, GATING, CONVERGED, DONE, and ESCALATED. Assert exact critical rows: repairable PLANNED: `harness transition IMPLEMENTING` then `harness transition SPECIFYING --reason SCOPE_DRIFT`; CONTRACT_CHANGED PLANNED: `harness task recover`; CONTRACT_CHANGED GATING: `harness gate` to ESCALATED, then `harness task new`. Add `ARCHITECTURE_SCOPE_INCOMPLETE` to controlled verification-gap reasons and use `GATE_PREFLIGHT_BLOCKED` for non-evidence blockers.

- [ ] **Step 5: Run RED**

Run: `pytest tests/test_architecture_gate.py tests/test_quality_gate.py tests/test_convergence_cli.py -q`
Expected: FAIL because assessment and policies are absent.

- [ ] **Step 6: Implement one request-local assessment**

Gate constructs at most one Architecture assessment and merges blockers into existing list. Convert Git adapter failures to existing invalid Harness state; never persist blocker for malformed workspace/artifact.

- [ ] **Step 7: Run GREEN**

Run focused command from Step 5.
Expected: PASS.

- [ ] **Step 8: Commit checkpoint**

Request authorization, then commit `feat: enforce architecture scope at gate`.

---

### Task 8: P0 Lifecycle, Packaging, and Acceptance

**Files:**
- Modify: `tests/test_context_dependency_closure.py`
- Modify: `tests/test_schema_resources.py`
- Modify: `tests/test_version_consistency.py`
- Create: `tests/test_architecture_lifecycle_integration.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all P0 interfaces.
- Produces: packaged and lifecycle-tested P0 release candidate; no Context projection yet.

- [ ] **Step 1: Write failing end-to-end lifecycle tests**

Exercise off legacy task, required support-only task, required production drift, repairable resume/realign/refreeze, authority escalation/replacement, CLI no-op retry, wheel schema inclusion, and FAST/off zero-read closure.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_architecture_lifecycle_integration.py tests/test_context_dependency_closure.py tests/test_schema_resources.py tests/test_version_consistency.py -q`
Expected: FAIL on any missing integration or package registration.

- [ ] **Step 3: Complete registration and release notes**

Register pure modules in dependency closure, include schema via existing package-data wildcard, and document P0 without claiming P1/P2 delivery.

- [ ] **Step 4: Run P0 acceptance**

Run focused Architecture tests plus directly modified subsystem tests only:

```bash
pytest tests/test_architecture.py tests/test_architecture_workspace.py tests/test_architecture_cli.py tests/test_architecture_gate.py tests/test_architecture_lifecycle_integration.py tests/test_workspace.py tests/test_workspace_untracked_scope.py tests/test_alignment.py tests/test_cli_alignment.py tests/test_test_plan_transition.py tests/test_quality_gate.py tests/test_convergence_cli.py tests/test_task_contract.py tests/test_cli_init.py tests/test_task_new.py tests/test_cli_task_recovery.py tests/test_context_dependency_closure.py tests/test_schema_resources.py tests/test_version_consistency.py -q
python -m pip wheel . --no-deps -w /tmp/harness-v030-p0
```

Expected: all tests PASS; wheel contains `architecture.schema.json`.

- [ ] **Step 5: Run Harness verification/review/Gate**

Collect fresh focused evidence, reconcile canonical Plan, run complexity/diagnosability reviews as required, then `harness gate`.
Expected: `DECISION: CONVERGED`.

- [ ] **Step 6: Commit checkpoint**

Request authorization, then commit `feat: complete architecture scope gate p0`.

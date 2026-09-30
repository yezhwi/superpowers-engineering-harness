# v0.3.0 Architecture Scope & Drift P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authoritative, bounded, body-free Architecture projection and freshness to Q2/Q3 required-mode Context without changing FAST/Q1 or mode-off source scope.

**Architecture:** Extend existing `AuthoritativeContext` and `ControlCore`; reuse P0 `ArchitectureAssessment` instead of recomputing Architecture. Context source/read-scope/freshness remain finite and fail closed; Architecture module IDs are domain version inputs, never repository paths.

**Tech Stack:** Python 3.11+, existing Context source/builder/integrity/freshness modules, JSON Schema, pytest.

**Spec:** `docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md`

## Global Constraints

- Requires completed P0 plan and its stable interfaces.
- FAST/Q1 and mode off add no Architecture source dependency, reference, schema load, resolver, or Git query.
- Required missing artifact projects status `missing` and blocker `ARCHITECTURE_REQUIRED`; malformed present source raises `CONTEXT_SCHEMA_INVALID`.
- Projection includes declared modules plus one-hop direct dependencies only.
- Deduplicated projection cannot exceed global 256-module bound. Legal input is fully projected at the bound; never truncate. Any apparent overflow means malformed input and fails validation.
- FAST/Q1 and mode off omit `control.architecture`; required mode alone adds `control.architecture`.
- Current required projection contains only `status`, `fingerprint`, `declared_modules`, and `relevant_modules`; missing required additionally contains `blockers: [ARCHITECTURE_REQUIRED]`. Other drift blockers remain in `control.blockers`.
- Projection includes metadata/responsibility/dependencies, never evidence or source bodies.
- Context is derived view, never Gate truth or new authority.
- Module IDs enter version inputs, not `_declared_paths()` or path/symlink validation.
- No persistent cache, repository scan, manifest authority, or background index.
- Every implementation commit requires fresh explicit user authorization.
- Run focused related tests only.

## Review Focus

- Required artifact disappears between freshness capture and source load: fail freshness/build, never publish stale Context.
- self-dependency remains invalid. A valid two-or-more-module dependency cycle remains finite and deduplicated under one-hop projection.
- A module ID contains path-looking characters: schema rejects invalid ID; freshness never treats valid IDs as paths.
- Mode changes required→off without matching v2 seal: Context surfaces contract drift, not empty Architecture projection.
- Missing required artifact plus Plan blockers: projection and Gate blocker identities remain consistent from one assessment.

---

### Task 1: Authoritative Source and Isolation

**Files:**
- Modify: `src/harness/context/model.py`
- Modify: `src/harness/context/source.py`
- Modify: `src/harness/context/dependency_closure.py`
- Test: `tests/test_context_builder.py`
- Test: `tests/test_context_dependency_closure.py`
- Test: `tests/test_context_read_scope.py`

**Interfaces:**
- Produces: `AuthoritativeContext.architecture` stores the complete validated canonical `dict | None`; `AuthoritativeContext.architecture_assessment: ArchitectureAssessment | None` is shared with Gate, and `ArchitectureAssessment.model` stores the in-memory `ArchitectureModel | None` (`ArchitectureModel` in memory only). Later, `ControlCore["architecture"]` stores only the projected dict. This serialized `dict | None` never contains a dataclass.
- Consumes: P0 `assess_architecture()` and validated Gate assessment; no second Architecture evaluation per request.

- [ ] **Step 1: Write failing source isolation tests**

Spy on Architecture artifact/schema/resolver/Git calls for FAST/Q1 and mode off. Assert no Architecture reference is recorded and generated Context omits `control.architecture`. Required Q2/Q3 records `.harness/architecture.yaml` only when present. Required→off config with a v2/required seal must expose `CONTRACT_CHANGED` in the shared Gate assessment before any off early return; it must not emit an empty Architecture projection.

- [ ] **Step 2: Write failing source error tests**

Assert required missing stays `None` with assessment blocker; malformed Architecture/alignment/plan source raises `ContextBuildError("CONTEXT_SCHEMA_INVALID", ...)`; Gate invalid-state naming remains separate.

- [ ] **Step 3: Run RED**

Run: `pytest tests/test_context_builder.py tests/test_context_dependency_closure.py tests/test_context_read_scope.py -q`
Expected: FAIL because authoritative model lacks Architecture fields.

- [ ] **Step 4: Implement source integration**

Load Architecture only after effective mode/risk checks. Reuse request-local assessment object; do not call ownership resolver or Git adapter from builder.

- [ ] **Step 5: Run GREEN**

Run focused command from Step 3.
Expected: PASS.

- [ ] **Step 6: Commit checkpoint**

Request authorization, then commit `feat: load architecture into authoritative context`.

---

### Task 2: Bounded Control Core Projection and Summary

**Files:**
- Modify: `src/harness/context/model.py`
- Modify: `src/harness/context/builder.py`
- Modify: `src/harness/schemas/context.schema.json`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/cli.py`
- Test: `tests/test_context_builder.py`
- Test: `tests/test_context_integrity.py`
- Test: `tests/test_architecture_cli.py`

**Interfaces:**
- Produces: `architecture_context_summary(model: ArchitectureModel | None, assessment: ArchitectureAssessment) -> dict` shared by Control Core and new CLI command `harness architecture summary`.
- Consumes: P0 model and assessment; returns only `status`, `fingerprint`, `declared_modules`, `relevant_modules`, and missing blockers.

- [ ] **Step 1: Write failing projection tests**

Assert schema has optional `control.architecture`, not a required key: FAST/Q1 and mode off omit it and remain valid. In required mode, assert current projection contains exactly `status`, `fingerprint`, `declared_modules`, and `relevant_modules`; declared modules plus exactly one-hop dependencies; deterministic order; no unrelated module, recursive expansion, evidence body, or evidence path body. A legal 256-module model projects all relevant modules and never truncates.

- [ ] **Step 2: Add missing/support/cycle tests**

Assert fixed missing projection includes `blockers: [ARCHITECTURE_REQUIRED]`; current projection never contains that `blockers` key; explicit support-only empty projection; self-dependency rejection; bounded two-module cycle; shared dependency deduplication; and non-missing drift blockers only in `control.blockers`.

- [ ] **Step 3: Run RED**

Run: `pytest tests/test_context_builder.py tests/test_context_integrity.py tests/test_architecture_cli.py -q`
Expected: FAIL because Control Core/schema lack Architecture projection.

- [ ] **Step 4: Implement one shared pure projector**

Place projector in `harness.architecture` or another P0-approved pure module; both Context builder and summary CLI call it. Convert the in-memory model to the exact serialized dict shape; never serialize dataclasses. Keep Gate independent of projected output.

- [ ] **Step 5: Run GREEN**

Run focused command from Step 3.
Expected: PASS.

- [ ] **Step 6: Commit checkpoint**

Request authorization, then commit `feat: project bounded architecture context`.

---

### Task 3: Freshness, Read Scope, and Integrity

**Files:**
- Modify: `src/harness/context/freshness.py`
- Modify: `src/harness/context/read_scope.py`
- Modify: `src/harness/schemas/context.schema.json`
- Modify: `src/harness/context/integrity.py`
- Test: `tests/test_context_freshness_property.py`
- Test: `tests/test_context_protected_freshness.py`
- Test: `tests/test_freshness_version_scope.py`
- Test: `tests/test_context_read_scope.py`
- Test: `tests/test_context_integrity.py`

**Interfaces:**
- Produces: Architecture artifact digest in existing `generated_from.files`; gate mode remains covered by `gate.yaml`, module IDs by `current-task.yaml`, and seal facts by `alignment-freeze.yaml`. Set `PROJECTION_VERSION = 4` and schema `"projection_version": {"const": 4}`; do not add generated_from fields or a manifest store.
- Consumes: P0 gate mode/seal and P1 authoritative source.

- [ ] **Step 1: Write failing freshness tests**

Change artifact bytes, v2 seal bytes, sealed mode, or declared module IDs independently and assert old Context becomes stale through existing `files`/hash inputs. Assert `PROJECTION_VERSION = 4` and matching Context schema const invalidate v3 documents. Assert evidence body outside relevant source scope does not enter projection.

- [ ] **Step 2: Add module-ID non-path tests**

Spy `_declared_paths()` and containment/path existence checks; valid module IDs must never appear. Add path-looking invalid module fixture rejected by Architecture schema, not freshness.

- [ ] **Step 3: Add race tests**

Delete/change Architecture artifact between capture/load/capture and assert build fails without publication. FAST/off file membership and existing file hashes remain unchanged from P0; `architecture.yaml` is absent. Separately assert projection_version changes from 3 to 4 for every profile, so the complete capture mapping is intentionally not byte-identical to P0.

- [ ] **Step 4: Run RED**

Run: `pytest tests/test_context_freshness_property.py tests/test_context_protected_freshness.py tests/test_freshness_version_scope.py tests/test_context_read_scope.py tests/test_context_integrity.py -q`
Expected: FAIL on missing version inputs/read scope.

- [ ] **Step 5: Implement finite version inputs**

Add Architecture file to existing `files` only for required mode via a conditional source-name helper; rely on existing gate/task/seal file hashes for mode/modules/sealed facts. Update `PROJECTION_VERSION = 4` and `"projection_version": {"const": 4}` together; do not add generated_from fields. Authorize exact source in bootstrap/version/read scopes and preserve two-phase freshness checks.

- [ ] **Step 6: Run GREEN**

Run focused command from Step 4.
Expected: PASS.

- [ ] **Step 7: Commit checkpoint**

Request authorization, then commit `feat: version architecture context inputs`.

---

### Task 4: P1 Lifecycle and Acceptance

**Files:**
- Modify: `tests/test_context_lifecycle_integration.py`
- Modify: `tests/test_context_cli.py`
- Modify: `tests/test_context_remaining_triggers.py`
- Modify: `tests/test_schema_resources.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all P1 interfaces.
- Produces: restart-stable Context integration and P1 release candidate.

- [ ] **Step 1: Write failing lifecycle tests**

Exercise required current/missing/malformed contexts, restart/reload, mode changes, seal drift, expansion/selection, validate/explain, and exact FAST/off source isolation.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_context_lifecycle_integration.py tests/test_context_cli.py tests/test_context_remaining_triggers.py tests/test_schema_resources.py -q`
Expected: FAIL on incomplete integration.

- [ ] **Step 3: Complete CLI/schema/release wiring**

Update release notes to mark P1 delivered without P2 claims.

- [ ] **Step 4: Run P1 acceptance**

```bash
pytest tests/test_context_builder.py tests/test_context_integrity.py tests/test_context_freshness_property.py tests/test_context_protected_freshness.py tests/test_freshness_version_scope.py tests/test_context_read_scope.py tests/test_context_dependency_closure.py tests/test_context_lifecycle_integration.py tests/test_context_cli.py tests/test_context_remaining_triggers.py tests/test_architecture_cli.py -q
python -m pip wheel . --no-deps -w /tmp/harness-v030-p1
```

Expected: all PASS; wheel schema validation succeeds.

- [ ] **Step 5: Run Harness verification/review/Gate**

Collect fresh focused evidence, reconcile Plan, perform required reviews, run Gate.
Expected: `DECISION: CONVERGED`.

- [ ] **Step 6: Commit checkpoint**

Request authorization, then commit `feat: complete architecture context p1`.

# Changelog

## 0.2.7

- Close Decision and Interface Contract correctness gaps: task-scoped Gate participation, explicit cross-task Interface reuse, validated active Decision references, safe supersession acceptance, and canonical Decision/Interface IDs.
- Separate product workspace fingerprint from control-plane fingerprint: requirement/invariant verification, review outcomes, and other `.harness/` metadata writes no longer mark product test/build evidence `EVIDENCE_WORKSPACE_STALE`. Product code, tests, and non-control-plane config changes still stale evidence. Gate still fail-closes on tampered evidence payload, invalid bindings, and invalid control-plane schema, without reporting control-plane self-updates as product-test stale.
- Canonicalize covered tests to repository-root paths. Subproject cwd pytest/Vitest selectors (including `sh -lc 'cd ... && ...'`) bind to test-plan paths such as `backend/tests/foo.py`. Collection still rejects missing files, repo-escaping paths, invalid relative cwd, and selectors the command did not execute (`COVERED_TEST_NOT_EXECUTED`, `COVERED_TEST_PATH_INVALID`). Legacy cwd-relative covered tests remain accepted until the next collection.

- Add explicit task-owned and protected-user scopes, preventing unrelated dirty paths from entering review.
- Add DIAG proposal publication, Finding-aware `resume-review`, unified evidence references, and evidence run/attach modes.
- Add Gate preflight, independent quality/release-readiness results, MR draft-only output, and complexity audit decisions.
- Add persisted Decision Records, Decision CLI, active-decision status summaries, and Gate blockers for unresolved or inconsistent decision state.
- Add external Interface Contracts, public-interface impact classification, Q1 escalation guard, fresh interface verification, and deterministic interface Gate blockers.
- Make `harness gate` sole product Gate authority; disable direct standalone quality-gate evaluation and typedly reject open Findings before `review outcome PASS`.
- Restrict `covered_tests` claims to test evidence, require explicit Finding categories, and reject category-less legacy artifacts with `MIGRATION_REQUIRED`.
- Remove obsolete aggregate `finding.schema.json`; canonical validation uses adversarial, diagnosability, complexity, and interface schemas.

### Install

```bash
pi install git:github.com/yezhwi/superpowers-engineering-harness@v0.2.7
```

## 0.2.6

- Harden diagnosability review control-plane integrity: task-type propagation, centralized fail-closed review readiness, and proposed DIAG Finding linkage validation.
- Stage review evidence and proposed Findings before publish; rollback canonical artifacts on publish failure.
- Add shared complete-lifecycle test fixtures and cross-layer fail-closed regression scenarios.

### User impact

Diagnosability review artifacts now reject Contract mismatches, unsupported `not_applicable` checks, and out-of-scope or unlinked DIAG Findings before canonical persistence. This release does not add a logger SDK, OpenTelemetry, automatic log insertion, or universal source scanning.

### Install

Pin this release from Git:

```bash
pi install git:github.com/yezhwi/superpowers-engineering-harness@v0.2.6
```

## 0.2.5

- Add Production Diagnosability Observability Contract for Q2/Q3 tasks, including applicability, business keys, failure boundaries, and bugfix observability-gap analysis.
- Add scope-bound diagnosability review evidence, DIAG Finding static-compliance lifecycle, and Q2/Q3 Gate enforcement for critical and major diagnosability findings.
- Keep logger frameworks, OpenTelemetry, automatic log insertion, and universal source scanning as explicit non-goals.

### User impact

Production failures in declared Q2/Q3 paths now retain a reviewed diagnostic contract: business keys, failure boundaries, and context needed to distinguish caller, dependency, and local failures. Critical and major DIAG Findings block completion; low-value logging remains advisory.

### Install

Pin this release from Git:

```bash
pi install git:github.com/yezhwi/superpowers-engineering-harness@v0.2.5
```

### Boundaries

This release does not provide a logger SDK, OpenTelemetry integration, APM, automatic log insertion, or universal source scanning. Harness persists and gates diagnostic intent and review proof; agents judge business semantics and logging quality.

## 0.2.4

- Add Test Plan Gate for STANDARD and STRICT `PLANNED → IMPLEMENTING` transitions.
- Add structured `test_plan` strategies, cases, executable bindings, and Test Case-to-Evidence traceability.
- Require fresh Evidence coverage for automated case bindings and typed recovery for missing plans, bindings, and proof.
- Preserve Q1/FAST Light Gate behavior and existing Requirement/Invariant Evidence fields.

## 0.2.3

- Add explicit rule-based Q1/Q2/Q3 task classification with FAST, STANDARD, and STRICT profiles.
- Add FAST Light Gate with task-level RED/GREEN regression proof and protection for user changes present at classification.
- Add independent per-task authorization records for commit, full suite, push, MR, merge, and deploy actions.
- Add same-task Evidence reuse with exact runtime/proof identity.
- Add Soft evidence budgets, local telemetry, and fixture benchmarks with validation/comparison and INCONCLUSIVE evidence handling.
- Add FAST risk-boundary revalidation and required repository verification.
- Keep remote telemetry, external-agent execution, and unrecorded external metric claims unavailable.

## 0.2.2

- Add typed Gate blockers and `harness resume` reason-driven recovery.
- Add structured `harness review outcome` routing for pass, verification gaps, and defects.
- Project current Evidence freshness in read-only `harness status`.
- Calculate complexity review scope from task Git baseline, committed, staged, unstaged, and relevant untracked changes.
- Derive recovery target from typed blocker code; add controlled review reason codes and release version consistency coverage.
- Make `harness gate` sole Gate evaluation and convergence authority; deprecate `harness converge`.

## 0.2.1

- Package runtime modules, schemas, and templates inside installed distributions.
- Add wheel-isolation coverage for execution outside source checkout.
- Add audited `harness task recover` for replacing stale active tasks.

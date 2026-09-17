# Changelog

## 0.2.8

- Add validated derived Context: compact/full projection, task-bound expansion, source freshness, and fail-closed Integrity checks. Context Evidence records generated context, not agent consumption, and does not become product Gate evidence.
- Add task-bound cumulative host usage reporting with validated token and agent counters. Local telemetry updates preserve reported usage; missing host measurements remain null.
- Extend Benchmark artifacts with usage and multi-run statistics, including `tokens_per_success`, median/P90 token reporting, and agent tool/search/file-read counters. Missing data remains `INCONCLUSIVE`; estimated usage is low-confidence; known correctness or integrity failures override efficiency claims.
- Add controlled source-access, schema-resource, workspace, and telemetry-lock boundaries with regression coverage.
- Resolve `npm run <script> --` Vitest selectors from the package script at the command cwd; unresolvable or non-Vitest scripts fail closed with `TEST_RUNNER_UNRESOLVED`.
- Compare diagnosability/complexity/interface review file scope as a set, and list actual-only vs expected-only paths on `DIAGNOSABILITY_SCOPE_MISMATCH`.
- Split review scope into path `files` and `contract_refs`. `DEC-*` labels are rejected in `review_scope.files`, compared as refs, and migrated out of old artifacts instead of being treated as paths.
- Reject `harness task classify` below the path-required risk in `.harness/risk-boundaries.yaml` without persisting task state; print `RISK_ESCALATION_REQUIRED` and the classify command to rerun.
- Derive `harness status` Build/Unit/Integration summary from the same live evidence projection as the Evidence list, including the selected record path.
- Scope compact Layer 0 to the current task's ACCEPTED decisions. Unreferenced historical decisions are omitted as `different_task_not_referenced` and do not trigger `DECISION_OUTSIDE_SCOPE`; explicit `supersedes`/`superseded_by` cross-task ids stay Layer 2 refs.
- Record optional `execution_environment` on collected evidence for `kubectl exec` (namespace/workload/cwd/container when present). Unparseable kubectl commands store `transport: unknown` without changing result semantics.
- Add `harness task verify-existing` for already-implemented work: records `verification_mode: existing_implementation` from CLASSIFIED/PLANNED with GREEN evidence, without RED, fake findings, or tracker writes. FAST Gate skips RED only with that mode plus a valid persisted verification record.
- Keep `TEST_RUNNER_UNRESOLVED` for unbound test selectors only; `npm run` build/lint evidence is not treated as a missing test runner. Persist `contract_refs` on complexity and interface review evidence so Gate matches typed scope.
- Rebuild a missing decision index from existing members during `harness init`. Context freshness versions `decisions/index.yaml` and member names, not historical bodies, and selected bodies must match index id/task_id/sha256.
- Document that `TEST_RUNNER_UNRESOLVED` applies only when binding covered tests. Context load migrates a missing decision index from existing members.

### Install

```bash
pi install git:github.com/yezhwi/superpowers-engineering-harness@v0.2.8
```

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

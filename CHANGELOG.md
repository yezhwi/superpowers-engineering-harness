# Changelog

## 0.2.5

- Add Production Diagnosability Observability Contract for Q2/Q3 tasks, including applicability, business keys, failure boundaries, and bugfix observability-gap analysis.
- Add scope-bound diagnosability review evidence, DIAG Finding static-compliance lifecycle, and Q2/Q3 Gate enforcement for critical and major diagnosability findings.
- Keep logger frameworks, OpenTelemetry, automatic log insertion, and universal source scanning as explicit non-goals.

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

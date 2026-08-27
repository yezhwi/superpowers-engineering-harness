# Adaptive Operations Design

**Status:** Proposed. Covers remaining Phase 5–7, local telemetry, and fixture benchmarks. No implementation until user approves this document.

## Scope

One bundled task adds: (1) regression audit for already-supported recovery routes, (2) soft budgets for Harness-observable evidence actions, (3) local telemetry, and (4) deterministic fixture benchmark reporting. No release work.

## Phase 5: state-route audit

No state-machine changes. Existing controlled routes remain only:

- evidence verification blockers: `harness resume` routes `BLOCKED → VERIFYING`;
- review test/evidence gap: `harness review outcome VERIFICATION_GAP` routes `REVIEWING → VERIFYING`;
- invariant violation routes to `IMPLEMENTING`;
- defect finding routes to `REPRODUCING`.

Add regression matrix tests and document commands. Never expose a naked transition shortcut.

## Phase 6: soft budgets

Only count Harness-observable actions: successful or failed evidence `unit_test` executions as `test_runs`, evidence `build` executions as `build_runs`, and failed repeated evidence commands as `retry_runs`. Search/read/tool calls are excluded and never guessed.

Default FAST limits: test runs 2, build runs 1, retry runs 1. STANDARD/STRICT have no limits. Collector checks budget before shell execution. Below limit it runs and increments counter. At/above limit, caller must add `--budget-override-reason`, `--budget-override-evidence`, and `--budget-override-hypothesis`; missing fields exit 2 before executing. Valid override runs and appends audit entry. Reused evidence does not increment budget.

Persist in current task:

```yaml
budget:
  test_runs: 2
  build_runs: 1
  retry_runs: 1
  overrides:
    - action: test
      reason: new consumer discovered
      evidence: unit-test.json
      hypothesis: shared formatter path
```

## Local telemetry

Persist `.harness/telemetry.json`; no network, identifiers, source, command output, or guessed values. Update only from Harness command facts:

- task id, risk level/profile;
- evidence test/build counts;
- elapsed seconds from task creation timestamp when available;
- Gate status, iteration count, escalation count.

Unavailable values are `null`. `harness telemetry show` prints file JSON; it has no side effects.

## Fixture benchmarks

Versioned local fixtures declare expected task level/profile and expected Gate result. `harness benchmark run --fixtures <dir>` validates manifests and aggregates local telemetry into JSON report. Metrics unavailable from telemetry are `null`; report makes no token or external-agent claims. Fixture failure returns nonzero.

## Invariants

- Existing recovery routing, evidence freshness, authorization, and Gate behavior remain unchanged.
- Budget is soft only; valid explicit override always permits execution.
- Budget rejection, reuse hit, telemetry read, and benchmark validation never execute unintended shell commands.
- Runtime `.harness` state is never committed.

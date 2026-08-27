# Risk-Adaptive Harness Design

## Scope

Implement document phases 1–3 for v0.2.3:

- rule-based Q1/Q2/Q3 classification;
- FAST/STANDARD/STRICT profiles;
- Q1 FAST state path and Light Gate;
- independent authorization records;
- user-workspace-change protection.

Q0 remains agent behavior: no Harness command or task is created for an inquiry. Evidence reuse, budgets, state shortcuts, telemetry, and benchmark/ablation are deferred.

## Risk classification

`harness task classify` records an agent-provided classification. Harness does not infer intent from keywords.

```bash
harness task classify --level Q1 \
  --scope low --contract none --data none --authorization none \
  --security none --concurrency none --deployment none
```

Dimensions are `none|low|high` except `contract`, which is `none|low|high`. The classifier is deterministic:

- any high data, authorization, security, concurrency, or deployment risk requires Q3/STRICT;
- non-none contract risk requires at least Q2/STANDARD;
- scope high requires at least Q2/STANDARD;
- otherwise Q1/FAST is permitted.

An underspecified requested level fails closed with `RISK_LEVEL_UNDERSPECIFIED`; Harness never silently promotes it. `harness task escalate --level Q2 --reason ...` permits only Q1→Q2, Q1→Q3, or Q2→Q3. Downgrades fail.

Task state persists:

```yaml
risk:
  level: Q1
  profile: FAST
  dimensions: { scope: low, contract: none, data: none, authorization: none, security: none, concurrency: none, deployment: none }
  escalation_history: []
  workspace_fingerprint: sha256:...
```

## State and profiles

Add `CLASSIFIED` state.

FAST uses:

```text
CREATED → CLASSIFIED → IMPLEMENTING → VERIFYING → GATING → CONVERGED → DONE
```

Classification moves CREATED→CLASSIFIED. FAST skips SPECIFYING, PLANNED, minimal-decision enforcement, impact recording, requirements/invariants records, complexity review, and review-outcome routing. Existing STANDARD and STRICT tasks use current state path unchanged; Q2 and Q3 profile selection records metadata but does not weaken present controls.

State guards inspect `task.risk.profile`, not agent prose.

## FAST evidence and Light Gate

Extend existing evidence phase metadata so task-level Q1 proof does not require a Finding:

```bash
harness evidence --type unit_test --phase red --covered-test tests/x.py::test_bug --command "pytest tests/x.py::test_bug"
harness evidence --type unit_test --phase green --covered-test tests/x.py::test_bug --command "pytest tests/x.py::test_bug"
```

This writes `fast-red-unit-test.json` and `fast-green-unit-test.json`. Existing Finding evidence still requires paired `--finding`, `--test`, and phase, retaining its current filename and lifecycle semantics. Light Gate runs only from GATING for profile FAST and requires:

- no post-classification workspace change;
- current fresh RED evidence with nonzero exit;
- current fresh GREEN evidence with zero exit;
- no risk dimension requiring Q2/Q3;
- required verification evidence configured by repository policy;
- no unauthorized side effect.

On PASS it follows existing GATING→CONVERGED behavior. Failure writes typed blockers and uses existing recovery routing. FAST does not create requirements, invariants, impact, or complexity-review artifacts.

## Authorization

Replace singular authorization metadata with independent records:

```yaml
authorizations:
  commit: { granted: false }
  full_suite: { granted: false }
  push: { granted: false }
  create_mr: { granted: false }
  ready_mr: { granted: false }
  merge: { granted: false }
  deploy: { granted: false }
```

CLI:

```bash
harness authorize commit
harness authorize full-suite
harness authorize push
harness authorize revoke-push
```

All grants are independent. Existing `full_suite` authorization migrates compatibly. Only full-suite execution is currently a Harness side-effect command, so it alone enforces a grant now; stored future grants do not authorize other actions implicitly.

## User workspace protection

Classification records workspace fingerprint. FAST Gate rejects a changed workspace with typed verification blocker; it never resets, checks out, stages, or overwrites user changes. Commit commands remain outside Harness and must use exact paths.

## Interfaces

New module: `harness.risk` owns risk dimensions, profile selection, validation, escalation, and workspace classification record validation. CLI/control-plane remain thin adapters. Gate delegates FAST checks to a dedicated Light Gate function; existing STANDARD/STRICT gate logic remains intact.

## Tests

- Q1 accepts safe dimensions and maps FAST.
- Q1 declaration with Q2/Q3 trigger fails closed.
- escalation-only behavior and persisted history.
- FAST legal transitions and STANDARD/STRICT compatibility.
- Light Gate requires real, fresh RED and GREEN evidence, rejects workspace change, and converges on valid evidence.
- FAST does not require complexity/impact/contract artifacts.
- authorization grants are independent; legacy full-suite authorization remains valid.
- no existing recovery, evidence freshness, review routing, baseline, or typed-blocker regressions.

## Deferred

- evidence reuse/evidence-gain policy;
- execution budgets;
- new BLOCKED/REVIEWING shortcut transitions;
- telemetry, benchmark set, and ablation report.

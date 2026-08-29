# Production Diagnosability Standard Design

**Status:** Approved design for v0.2.5. No implementation in this change.

## Goal

Add production diagnosability as a Harness-controlled quality dimension without adding a logging platform, replacing a target project's logger, scanning an entire repository, or forcing logging into low-risk changes.

Harness persists diagnosability intent and review proof. An Agent evaluates business semantics and existing project conventions. Deterministic code validates artifact shape, scope, freshness, Finding linkage, lifecycle proof, and Gate policy.

```text
Agent semantic judgement
  -> Observability Contract
  -> Diagnosability Review artifact + Findings
  -> deterministic Harness validation + Gate
```

Harness does not claim generic cross-language detection of log quality or sensitive-data leakage.

## Risk routing

| Risk | Diagnosability behavior |
|---|---|
| Q0 | Skip. |
| Q1 / FAST | Agent checks business identifier, exception context, and sensitive-data exposure. No observability artifact. If risk exceeds Q1, Agent recommends explicit Q2 escalation. |
| Q2 / STANDARD | Agent records applicability. A full Contract and review are required only when `observability.required: true`. |
| Q3 / STRICT | Contract applicability and a fresh Diagnosability Review are always required. `required: false` needs explicit applicability reasons. |

This preserves current FAST minimum-ceremony behavior and current Q2/Q3 Contract/Review/Gate flow.

## Observability Contract

Create `.harness/observability.yaml` and validate it with a new `observability.schema.json`.

```yaml
version: 1
required: true
applicability:
  reasons:
    - external_dependency
    - state_transition
  inspected_paths:
    - src/orders/refund.py
  existing_conventions:
    logging: structlog
    correlation: trace_id
    masking: redact()

business_keys:
  - order_id
  - refund_id

critical_events:
  - refund_requested
  - refund_rejected
  - refund_completed

state_transitions:
  - business_key: order_id
    from: PAID
    to: REFUNDING
    trigger: refund_requested

external_dependencies:
  - name: payment_gateway
    operations: [refund]
    required_context: [dependency, operation, duration_ms, error_code, order_id]

failure_boundaries:
  - payment_refund
  - order_state_update

sensitive_data:
  policy: existing_project_policy
  prohibited: [password, token, authorization, cookie, secret, api_key]

bug_fix:
  observability_gap: true
  basis: payment success and local state failure cannot be separated
  missing_information: [payment_id, order_id, state_transition]
  improvement: record order-state-update failure with stable event and keys
```

### Contract rules

- `version` is integer `1`.
- `required` is boolean.
- `applicability.reasons` and `applicability.inspected_paths` are nonempty unique strings.
- `required: false` permits only `version`, `required`, and `applicability`, except bugfix tasks may also contain `bug_fix`. `applicability.reasons` states why none of external dependency, caller rejection, state transition, async/retry/fallback, compensation, consistency, permission, or critical business object applies.
- `required: true` requires nonempty `business_keys` and `failure_boundaries`, plus at least one nonempty applicable diagnostic dimension: `critical_events`, `state_transitions`, or `external_dependencies`.
- `state_transitions` records semantic transition data, not logger call locations.
- `external_dependencies.required_context` contains only required semantic fields. It does not prescribe a logger framework or message format.
- `sensitive_data.policy` identifies existing project policy or `none_known`; it never creates a new masking SDK requirement.
- For bugfix tasks, `bug_fix.observability_gap` and `bug_fix.basis` are mandatory. `true` requires nonempty `missing_information` and `improvement`; `false` prohibits them.
- Task Contract creates linked `REQ-*` diagnosability requirements only when `required: true`. Those requirements are `must`; Findings retain normal Requirement-to-Finding traceability.

The Contract records diagnostic needs, never a mandate to log every method, full object, request, response, exception, or retry stack trace.

## Diagnosability Review artifact

Add `diagnosability-review.schema.json`. `harness review diagnosability --file <artifact>` accepts source YAML or JSON, calculates actual review scope, validates all Contract and Finding references, then writes canonical `.harness/evidence/diagnosability-review.json`.

```json
{
  "type": "diagnosability_review",
  "command": "harness review diagnosability",
  "exit_code": 0,
  "commit": "abc123",
  "workspace_fingerprint": "sha256:current-workspace",
  "workspace_fingerprint_after": "sha256:current-workspace",
  "review_scope": {
    "files": ["src/orders/refund.py"],
    "direct_dependencies": ["src/payments/gateway.py"]
  },
  "contract_required": true,
  "outcome": "PASS",
  "finding_ids": [],
  "checks": {
    "business_keys": "pass",
    "external_failure_context": "pass",
    "state_transitions": "pass",
    "caller_rejections": "not_applicable",
    "sensitive_data": "pass",
    "duplicate_exception_logging": "pass",
    "low_value_logging": "pass"
  }
}
```

### Review rules

- Check values are exactly `pass`, `fail`, or `not_applicable`.
- Any `fail` requires one linked open `FND-*` diagnosability Finding.
- `not_applicable` requires Contract support; it cannot hide a declared required dimension.
- Canonical scope includes Contract `inspected_paths` and direct dependencies needed for changed behavior. It uses existing workspace snapshot and scope logic; workspace edits stale review evidence.
- A review `PASS` has no failed checks. It does not prove every production failure is diagnosable; it proves review of declared scope and Contract.
- Review Agent inspects existing logger, correlation, exception-handler, reason-code, and masking conventions before recommending code changes.

No generic source scanner is part of v0.2.5. A later project-specific scanner may consume this Contract but cannot replace review evidence.

## DIAG Findings

Reuse `FND-*`. Do not create a separate DIAG state machine.

```yaml
id: FND-004
kind: requirement_violation
target: REQ-003
category: diagnosability
reason_code: DIAG_MISSING_EXTERNAL_FAILURE_CONTEXT
severity: major
status: PROPOSED
location:
  file: src/orders/refund.py
  line: 84
scenario: >
  payment_gateway refund timeout occurs. Existing output lacks order_id,
  dependency, operation, duration, and normalized error code. Operator
  cannot distinguish remote timeout from local state-update failure.
compliance:
  evidence_kind: static_compliance
  required_checks: [external_failure_context, business_keys]
```

Extend `finding.schema.json` conditionally:

- `category: diagnosability` requires `reason_code`, `location`, and `compliance`.
- DIAG reason codes are:
  - `DIAG_MISSING_BUSINESS_ID`
  - `DIAG_MISSING_CRITICAL_EVENT`
  - `DIAG_MISSING_STATE_TRANSITION`
  - `DIAG_MISSING_EXTERNAL_FAILURE_CONTEXT`
  - `DIAG_MISSING_REASON_CODE`
  - `DIAG_UNDIAGNOSABLE_EXCEPTION`
  - `DIAG_DUPLICATE_EXCEPTION_LOG`
  - `DIAG_SENSITIVE_DATA_LOGGED`
  - `DIAG_EXCESSIVE_LOGGING`
  - `DIAG_LOW_VALUE_LOGGING`
- `location.file` is required; `location.line` is optional positive integer.
- `target` remains a linked `REQ-*`.
- `static_compliance` is an explicit alternative proof lifecycle. To reach terminal status, it requires fresh `diagnosability_review` evidence for current scope with all `required_checks: pass`.
- Existing Finding kinds and RED → GREEN → regression lifecycle remain unchanged. No ordinary Finding can use static-compliance proof.

Severity policy:

| Condition | Severity |
|---|---|
| Sensitive data logged without proven existing masking policy | critical |
| Key critical-path diagnostic context missing; external failure boundary cannot be located | major |
| Missing important event/state/reason code in declared scope | major unless Contract marks impact limited |
| Duplicate exception logging or low/excessive value logging without security/correctness impact | minor |

## Gate and state routing

Add policy to `templates/gate.yaml`:

```yaml
diagnosability:
  standard: required_when_contract_required
  strict: required
  blocking: [critical, major]
```

Gate behavior:

1. Q2 with `observability.required: true` needs fresh successful canonical review evidence.
2. Q3 always needs fresh successful review evidence and valid applicability artifact.
3. Review scope must cover every Contract inspected path. Scope mismatch is invalid Harness state.
4. `fail` without linked Finding, or linked Finding outside review scope, is invalid Harness state.
5. Open DIAG `critical` and `major` Findings block through existing Finding Gate logic. `minor` is advisory.
6. `DIAG_SENSITIVE_DATA_LOGGED` must be critical.

Do not add a state. Extend controlled review reason codes with `DIAGNOSABILITY_VIOLATION` under `DEFECT`:

```text
REVIEWING
  -> diagnosability PASS
  -> normal review PASS
  -> GATING

REVIEWING
  -> diagnosability Finding
  -> review outcome DEFECT / DIAGNOSABILITY_VIOLATION
  -> REPRODUCING -> FIXING -> VERIFYING -> REVIEWING
```

`harness review diagnosability` persists evidence and proposed Findings only. It does not transition task state. Existing `harness review outcome` remains sole transition authority.

## Modules and skills

New deep module: `src/harness/diagnosability.py`.

Its interface owns Contract validation, review artifact validation/persistence, DIAG Finding validation, scope linkage, and Gate readiness checks. CLI, control plane, and quality gate call this module. They do not duplicate YAML or schema interpretation.

```text
src/harness/diagnosability.py                       # new
src/harness/schemas/observability.schema.json       # new
src/harness/schemas/diagnosability-review.schema.json # new
src/harness/templates/observability.yaml            # new
src/harness/schemas/finding.schema.json             # DIAG conditions
src/harness/schemas/task.schema.json                # review reason code
src/harness/templates/gate.yaml                     # policy
src/harness/cli.py                                  # review diagnosability CLI
src/harness/controlplane.py                         # command + compliance lifecycle
src/harness/quality_gate.py                         # Gate readiness
src/harness/review_outcome.py                       # DIAGNOSABILITY_VIOLATION
skills/task-contract/SKILL.md                       # Contract generation
skills/engineering-harness/SKILL.md                 # risk routing
skills/diagnosability-review/SKILL.md               # new semantic review
```

The new review skill must not claim certainty beyond reviewed scope. It must avoid generic logging advice, full-object logging, method-entry/exit logs, and logging sensitive fields. It creates only structured review input and proposed `FND-*` records.

## Verification

Use TDD. Add unit, CLI integration, lifecycle, Gate, and fixture-corpus coverage.

1. Contract schema: true/false applicability, required dimensions, bugfix gap true/false, invalid combinations.
2. Review schema: allowed checks, fail-to-Finding linkage, `not_applicable` Contract support, calculated scope mismatch, fresh/stale workspace proof.
3. DIAG Finding schema: legal reason code, required location/compliance data, sensitive leakage severity, normal Finding compatibility.
4. CLI: canonical evidence and Findings written atomically; invalid artifact rejected without partial writes.
5. Lifecycle: static-compliance Finding closes only with fresh matching passing review; ordinary Finding still requires same-test RED/GREEN proof.
6. Gate: Q2 conditional review, Q3 mandatory review, open major/critical block, minor does not block, stale evidence blocks.
7. Fixture corpus: pure calculation/no Contract; payment external call/context failure; state transition failure; duplicate refund business rejection; password object log; entry/exit noise; diagnosable bug with `observability_gap: false`.

Fixtures prove Harness policy and artifact handling. They do not claim that every logger framework or every real application has been exhaustively analyzed.

## Non-goals

- OpenTelemetry, ELK, Loki, Prometheus, Grafana, APM, trace backend, or log collection.
- A logging SDK, logger framework replacement, or mandatory structured logger.
- Whole-repository logging scans.
- Automatic insertion of log calls.
- Mandatory logs for every bugfix.
- Universal deterministic detection of sensitive logging or diagnostic quality.

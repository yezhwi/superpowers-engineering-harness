# Benchmark Correctness Comparator Design

**Status:** Proposed P1-3. No implementation before user approves this document.

## Goal

Replace fixture expectation-only reporting with deterministic comparison of independently recorded baseline and risk-adaptive run artifacts. Never claim adaptive correctness is preserved when evidence is absent.

## Boundary

Harness does not execute external agents or infer token/tool-call counts. It reads local artifacts created by benchmark operator. Comparator validates shape and computes result; it cannot attest that artifacts describe a real run.

## Fixture and artifacts

Fixture declares required correctness dimensions:

```yaml
id: q1-error-mapper
required_correctness:
  - gate_pass
  - regression_detected
```

Each run artifact contains:

```yaml
fixture_id: q1-error-mapper
mode: baseline # or adaptive
correctness:
  gate_pass: true
  regression_detected: true
  contract_violation_detected: null
  security_violation_detected: null
metrics:
  token_estimate: null
  tool_calls: null
  elapsed_seconds: 12.4
```

Artifacts live in caller-selected baseline/adaptive directories; one `<fixture-id>.json` per mode.

## Comparator

`harness benchmark compare --fixtures <dir> --baseline <dir> --adaptive <dir>` writes `.harness/benchmark-report.json`.

For every fixture:

- missing/malformed artifact, fixture id mismatch, wrong mode, or missing required correctness field produces `INCONCLUSIVE`;
- required correctness values must be `true` for baseline and adaptive;
- adaptive false after baseline true produces `CORRECTNESS_REGRESSION`;
- only all fixtures passing correctness yields `CORRECTNESS_PRESERVED`;
- optional correctness fields are reported but never substitute required ones.

Metrics are compared only after correctness is preserved. Each delta is numeric only when both values are numeric; otherwise `null`. Report never states token/tool-call/time improvements for null metrics.

## Invariants

- No external agent execution, network, token estimation, or metric guessing.
- Correctness is vector-based; no scalar score masks a false required dimension.
- Existing `benchmark run` fixture expectation validator remains available and is explicitly labeled validation, not comparison.
- Reports use `INCONCLUSIVE` rather than correctness-preserved when proof is incomplete.

## Verification

TDD covers preserved vector, adaptive regression, missing artifact/field inconclusive, mode/id mismatch, optional fields, numeric metric delta, null metric delta, CLI output/report persistence, and existing validation regression.

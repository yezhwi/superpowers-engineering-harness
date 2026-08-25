# Related Finding Closure Design

## Goal

Allow major findings to close after impact-scoped related tests, while preserving full-suite proof for critical findings and high-impact changes.

## Policy

| Finding severity | Accepted proof for `FIXED -> VERIFIED` |
| --- | --- |
| `critical` | Fresh successful `full_suite` evidence only. |
| `major` | Fresh successful `related` evidence that covers every impact `required_tests` entry, plus existing same-regression-test GREEN proof. |
| `major` with `impact.full_suite.recommended: true` | Fresh successful `full_suite` evidence only. |
| other | Existing policy remains unchanged unless a finding is gate-blocking. |

`VERIFIED -> CLOSED` archives existing verified proof; it runs no additional test.

## Evidence model

Extend only unit-test evidence with optional structured fields:

```yaml
scope: related | full_suite
covered_tests:
  - tests/example.py::test_case
```

`scope` and `covered_tests` are optional for generic build, requirement, invariant, and historical evidence. They are mandatory when evidence is used to close a finding under this policy.

CLI:

```bash
harness evidence \
  --type unit_test \
  --scope related \
  --covered-test tests/example.py::test_case \
  --command "pytest tests/example.py::test_case"
```

`--covered-test` may repeat. `related` requires at least one. `full_suite` still requires persisted human authorization. Existing `--finding` / `--test` pairing remains reserved for finding RED/GREEN identity proof.

## Finding proof validation

Add one shared validator used by `cmd_finding_transition` and `quality_gate`.

Inputs: finding record, evidence record, impact document, current HEAD/workspace.

It first applies existing `validate_evidence` freshness and success checks. For `VERIFIED/CLOSED` finding full-regression proof it then applies:

1. Missing `scope`: reject `FINDING_SCOPE_MISSING`.
2. Critical finding with non-`full_suite` scope: reject `FULL_SUITE_REQUIRED_FOR_CRITICAL`.
3. Major finding when impact recommends full suite and scope is not `full_suite`: reject `FULL_SUITE_REQUIRED_BY_IMPACT`.
4. Major finding with `related` scope where `covered_tests` does not contain every `impact.required_tests` entry: reject `RELATED_TEST_COVERAGE_MISSING`.
5. Major finding with `full_suite` scope: accept after normal full-suite authorization/evidence validation.

The validator must not infer coverage by parsing command strings.

## Compatibility

- No dependency added.
- State-machine transitions remain unchanged.
- Generic evidence and historical evidence remain valid for requirements, invariants, builds, and non-finding uses.
- Historical evidence lacking scope cannot newly prove a finding `VERIFIED` or `CLOSED`.
- Root CLI/script compatibility remains unchanged except additive evidence flags.

## Failure handling

All closure-policy failures are fail-closed with stable error codes. A finding remains `FIXED` when policy proof fails. Gate revalidates every `VERIFIED` and `CLOSED` finding so a status-only YAML edit cannot bypass policy.

## Verification

Tests cover:

1. major finding closes with fresh related evidence covering all impact tests;
2. major finding rejects missing scope or incomplete coverage;
3. critical finding rejects related evidence;
4. major finding rejects related evidence when impact recommends full suite;
5. major finding accepts authorized full-suite evidence;
6. gate rejects a manually edited `VERIFIED/CLOSED` finding with insufficient proof;
7. existing generic evidence behavior and full-suite authorization remain compatible.

# Proof Integrity Hardening Design

## Scope

Fix CR-001 through CR-003 from `docs/Superpowers-Engineering-Harness-v0.2-Code-Review-修复报告.md`. CR-004 package-layout work is excluded.

## Evidence validator

Create `scripts/evidence_validator.py` as single source of truth:

```python
validate_evidence(record, *, current_head, current_workspace,
                  expected_success=None, finding_id=None, test_id=None) -> None
```

It validates evidence schema; exact HEAD; before/after workspace fingerprints equal current workspace and each other; optional expected exit status; optional structured finding subject and test identity. It raises deterministic reason-code errors.

Requirement/invariant verification, finding proof validation, quality gate, complexity review freshness, and CONVERGED-to-DONE use it. No duplicated freshness checks remain in those consumers.

## Structured regression evidence

Extend `harness evidence` with paired optional `--finding FND-NNN` and `--test <node-id>` arguments. When present, collected JSON includes:

```json
{
  "subject": {"kind": "finding", "id": "FND-001"},
  "test": {"node_id": "tests/test_refund.py::test_double_refund"}
}
```

Schema permits these fields only as an all-or-none pair. Existing general build, unit-test, and full-regression evidence remains valid.

Finding `CONFIRMED` requires fresh failed structured evidence matching finding ID and supplied test. `FIXED` requires fresh successful structured evidence matching stored finding ID and RED test path. `VERIFIED` continues to require separate fresh successful full-regression evidence.

## Current DONE enforcement

`cmd_transition` special-cases only `CONVERGED -> DONE`: rerun current deterministic gate. PASS permits transition. BLOCKED returns exit 1 with `CURRENT_GATE_PASS_REQUIRED` and leaves state CONVERGED. Invalid state returns exit 2.

## Tests

Test tracked/untracked workspace mutation, stale finding RED/GREEN/full evidence, unrelated `false`/`true` evidence, mismatched RED/GREEN tests, same-test success, new open finding after convergence, and current gate PASS DONE path. Run full regression after each finding and at end.

## Constraints

No new state, workflow, review type, reporting feature, UI, or standalone CLI command. No CR-004 packaging refactor.

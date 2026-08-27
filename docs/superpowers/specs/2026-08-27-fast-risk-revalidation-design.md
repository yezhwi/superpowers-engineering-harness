# FAST Risk Revalidation Design

**Status:** Proposed P0-3. No implementation before user approves this document.

## Goal

Prevent Q1/FAST Gate from passing when changed business files cross declared contract or high-risk boundaries without explicit persisted escalation.

## Policy

Projects may add `.harness/risk-boundaries.yaml`:

```yaml
boundaries:
  q2:
    - src/**/api/**
    - schemas/**
    - public/**
  q3:
    - auth/**
    - permissions/**
    - migrations/**
    - workers/**
```

Patterns are repository-relative Git paths using `pathlib.PurePosixPath.match`. `q2`/`q3` lists are required when policy exists; entries are nonempty strings. A path matching both requires Q3.

## Revalidation

FAST Gate calculates changed business paths from immutable `task.git.base_commit` through current HEAD plus working-tree paths, using existing workspace ignore policy. It ignores `.harness/`. It evaluates only non-test/non-documentation paths: paths under `tests/`, `test/`, `docs/`, and root files ending `.md` are documentation/test-only exception.

- no changed business paths: FAST proceeds;
- changed business paths with missing policy: block `RISK_REVALIDATION_POLICY_MISSING`, recover `IMPLEMENTING`;
- q2 match while persisted level is Q1: block `RISK_ESCALATION_REQUIRED`, recover `IMPLEMENTING`;
- q3 match while persisted level is Q1/Q2: block same code, recover `IMPLEMENTING`;
- declared level at least required level: FAST proceeds.

Gate never changes risk itself. Operator must run `harness task escalate --level Q2|Q3 --reason ...`; existing monotonic escalation history is audit proof.

## Invariants

- No semantic/keyword inference.
- Missing/invalid boundary policy never permits changed FAST business code.
- Existing RED/GREEN, user-change protection, freshness, and STANDARD/STRICT Gate behavior remain unchanged.
- Docs/tests-only FAST changes remain usable without policy.

## Verification

TDD proves missing policy blocks business change, docs/tests-only passes without policy, q2/q3 policy matches require correct escalation, persisted sufficient escalation passes, malformed policy fails closed, and blocker recovery routes to IMPLEMENTING.

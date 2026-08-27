# FAST Light Gate Completeness Design

**Status:** Proposed P1-1. No implementation before user approves this document.

## Goal

Complete FAST Light Gate deterministic checks without restoring STANDARD/STRICT ceremony.

## Existing guarantees

FAST already requires persisted Q1/FAST profile, user pre-existing change protection, boundary revalidation, real RED failure, current fresh GREEN success, and Gate execution. P0-3 supplies contract/high-risk revalidation through declared boundary policy.

## Required repo verification

Add profile policy to `gate.yaml`:

```yaml
gate:
  fast:
    verification:
      build: required
      typecheck: optional
```

FAST always requires task RED/GREEN. It also validates every `required` entry in `gate.fast.verification` using existing evidence validation: file exists, exit zero, current HEAD, current workspace.

When `gate.fast` is absent, FAST defaults to `build: required`. This preserves repository integrity floor. Typecheck remains opt-in because project support varies. FAST does not load STANDARD requirements, invariants, complexity, findings, or generic unit-test requirement.

Missing/invalid required FAST evidence blocks with `FAST_REPOSITORY_VERIFICATION_MISSING`, recovery `VERIFYING`.

## Risk and contract revalidation

P0-3 remains required before FAST evidence checks. `RISK_REVALIDATION_POLICY_MISSING` and `RISK_ESCALATION_REQUIRED` recover to `IMPLEMENTING`; Gate never mutates risk.

## Authorization boundary

Independent persisted authorizations remain sole Harness-enforced authorization boundary for full suite, commit, push, MR, merge, and deploy. FAST Gate does not claim to detect external actions executed outside Harness control. Documentation states this limit explicitly.

## Invariants

- FAST remains deterministic and narrower than STANDARD/STRICT.
- Required FAST repository evidence cannot be bypassed by RED/GREEN.
- Existing evidence freshness and authorization independence remain unchanged.
- No semantic inference or external side-effect detection claim.

## Verification

TDD proves default build requirement, explicit required typecheck, optional/missing type ignored, stale/failed required evidence blocks, profile policy does not impose STANDARD artifacts, and docs state authorization scope.

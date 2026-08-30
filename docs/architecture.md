# Harness Architecture: Big Picture

Superpowers Engineering Harness is deterministic control plane around agent development work. Agents and skills make engineering judgments. Harness persists artifacts, validates relations, controls state transitions, and blocks unsupported completion claims.

```text
User requirement
      │
      ▼
Task Contract
Requirements + Invariants + Risk + Test Plan + Observability
      │
      ▼
State machine
CREATED → CLASSIFIED → SPECIFYING → PLANNED → IMPLEMENTING
                                      │              │
                                      │              └─ TDD / Finding lifecycle
                                      ▼
VERIFYING → REVIEWING → GATING → CONVERGED → DONE
     │            │          │
     │            │          └─ Gate: evidence + freshness + findings + Contracts
     │            └─ complexity / diagnosability / code review
     └─ deterministic test and build proof
```

## Control-plane boundary

```text
Agent / skill
  - interpret requirement
  - inspect source
  - propose Contract, review, Finding, test, fix
  - run approved commands

Harness
  - persist canonical artifacts
  - validate schema and cross-artifact semantics
  - stage/publish review artifacts
  - enforce legal state transitions
  - calculate evidence freshness
  - fail-close Gate
```

Harness does not replace code review, business judgment, logging framework choice, or source-code implementation.

## Canonical artifacts

```text
.harness/
├── current-task.yaml       task, state, risk, authorizations, Git baseline
├── requirements.yaml       acceptance requirements and test bindings
├── invariants.yaml         non-negotiable properties and test bindings
├── observability.yaml      Q2/Q3 diagnosability Contract
├── findings/               one Finding per canonical YAML artifact
├── evidence/               command proof, review proof, freshness identity
├── gate.yaml               Gate projection
└── .staging/               uncommitted multi-artifact publish sets
```

Artifacts are source of truth. Status is projection, not separate truth.

## Core proof loops

```text
Requirement → executable test binding → fresh Evidence → Gate

Review failure → Finding → reproduce RED → fix GREEN → verify → Gate

Diagnosability Contract → scope-bound review → DIAG Finding when failed
                       → static-compliance closure → Gate
```

A test that is not bound to Requirement/Invariant is useful regression coverage, but does not prove a Contract item. Evidence that is stale, mismatched, or missing required coverage does not satisfy Gate.

## Risk routing

```text
Q0  answer only; no Harness task
Q1  FAST: RED / fix / GREEN / Light Gate
Q2  STANDARD: Task Contract, verification, review, Gate
Q3  STRICT: Q2 plus mandatory non-sentinel Observability Contract and fresh diagnosability review
```

Risk can escalate but never downgrade. User authorization controls Harness actions such as commit, full suite, push, and release; it does not prove external actions did not occur.

## Diagnosability review integrity

```text
Review input
      │
      ▼
input validation
      │
      ▼
readiness validation
Contract + Findings + Scope + Git HEAD + workspace fingerprint
      │
      ▼
.harness/.staging/<operation-id>/
      │
      ▼
publish canonical Findings + review evidence
      │
      ▼
Gate / Finding closure
```

Failed checks require linked, in-scope DIAG Findings. Contract mismatch, unsupported `not_applicable`, stale review identity, and invalid Finding linkage fail closed. A review with failed checks routes to DEFECT; it cannot make Gate pass.

## Release boundary

```text
Feature complete
→ focused verification
→ review / Gate PASS
→ version + changelog
→ explicitly authorized full suite
→ package checks
→ commit + push
→ immutable annotated tag
→ GitHub Release
```

Never move published tags. A fix after release becomes next patch release.

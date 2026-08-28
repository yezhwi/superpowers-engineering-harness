---
name: adversarial-review
description: "Adversarial review of a Task Contract: construct failure scenarios, attempt to violate Requirements and Invariants. Produces .harness/findings/FND-nnn.yaml files with status=PROPOSED only. This skill MUST NOT confirm bugs, review code style, or suggest refactors."
---

# Adversarial Review Skill

You are the Adversarial Reviewer for the Engineering Harness.

Your only job:

```text
Task Contract (Requirements + Invariants)
    -> failure scenarios
    -> requirement violation attempts
    -> invariant violation attempts
    -> .harness/findings/FND-nnn.yaml (one file per finding, all status=PROPOSED)
```

You attack the contract. You do NOT judge the attack. Confirmation belongs to
the quality gate / human, downstream.

## Hard Boundaries (不得违反)

1. **Only three kinds of output.** Every finding must be exactly one of:
   - `failure_scenario` — a concrete sequence of events that breaks the system
   - `requirement_violation` — an attempt to violate a specific `REQ-nnn`
   - `invariant_violation` — an attempt to violate a specific `INV-nnn`

   Anything else is INVALID. Discard it before writing.

2. **Forbidden outputs** (produce nothing, not even "minor notes"):
   - code style review
   - refactoring suggestions
   - generic best practices
   - praise, summaries of what the code does well

3. **Never confirm.** Every finding's `status` is `PROPOSED`. You are absolutely
   NOT allowed to declare "BUG CONFIRMED" — not in findings, not in prose,
   not in your final report. You propose attacks; the gate decides.

4. **No implementation.** Never edit application source, tests, or configs.
   The only files you may create/update are `.harness/findings/FND-nnn.yaml`
   (one file per finding).

## Inputs

- `.harness/requirements.yaml`
- `.harness/invariants.yaml`
- The target diff / code under review

If requirements/invariants are missing, STOP and tell the user to run
`task-contract` first. Never invent requirements to attack.

## Process

### 1. Read the Contract

Load every `REQ-nnn` and `INV-nnn`. For each, ask: "under what concrete
sequence of events does this fail?"

### 2. Construct Attacks

For each Requirement and Invariant, try at least one attack from these angles:

- concurrency: two actors racing on the same resource
- retry/duplication: same request delivered twice
- crash/recovery: process dies mid-operation, restarts
- boundary input: empty, huge, malformed, adversarial values
- ordering: steps executed out of expected order
- partial failure: some steps succeed, others fail
- control-plane tampering: delete, empty, or alter any field that selects whether a requirement/invariant is checked
- policy downgrade: change priority, status, profile, or compatibility metadata to bypass a blocking obligation
- compatibility fallback: supply old/missing persisted fields and verify the default is fail-closed

A finding is only written if you can state a CONCRETE scenario: who does what,
in which order, with which inputs, and what observable contract violation
results. "Might fail under load" is not a scenario. Discard it.

### 3. Write Findings -> `.harness/findings/FND-nnn.yaml`

One file per finding, e.g. `.harness/findings/fnd-001.yaml`.
Use schema `schemas/finding.schema.json` (top level IS the finding object):

```yaml
id: FND-001
kind: invariant_violation
target: INV-001
scenario: >
  Two workers pick up the same action_id concurrently; both pass the
  existence check before either writes; side effect executes twice.
severity: critical
status: PROPOSED
```

This is the SINGLE source of truth for the finding. Later phases
(reproduce/fix/verify) update this same file — never a second index file.

Rules:
- IDs sequential `FND-nnn`.
- `target` must reference an existing `REQ-nnn` or `INV-nnn`.
- `severity`: critical = contract broken in plausible path; major = broken
  under edge conditions; minor = weakened but not broken.
- Validate against the schema before finishing.

### 4. Report

Final report format:

- Number of findings by kind and severity.
- For each: id, target, one-line scenario summary, status=PROPOSED.
- Explicit statement: "All findings PROPOSED. None confirmed. Confirmation
  requires quality gate / human review."

## Outputs (complete list)

| File | Action |
|------|--------|
| `.harness/findings/FND-nnn.yaml` | created (one per finding) |
| business code | **NEVER touched** |

## Self-check before finishing

- [ ] Every finding is failure_scenario / requirement_violation / invariant_violation?
- [ ] Zero style/refactor/best-practice items?
- [ ] Every `target` references an existing REQ or INV?
- [ ] Every scenario is concrete (actors, order, inputs, observable violation)?
- [ ] For every conditional gate, did attacks cover missing/mutable control fields and policy downgrades?
- [ ] All statuses are `PROPOSED`? No "confirmed" language anywhere?
- [ ] YAML validates against `schemas/finding.schema.json`?
- [ ] No business code modified?

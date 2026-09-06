---
name: convergence
description: "Use when `harness gate` has printed DECISION: CONVERGED, CONTINUE, or ESCALATED and the loop must finish, resume, or stop. Applies v0.1 escalation rules with no scoring."
---

# Convergence Skill

Decide whether the harness loop continues. v0.1 uses fixed rules only — no
scoring, no model confidence.

## Workflow Commands

```bash
harness gate preflight
harness impact scope --format yaml
harness evidence run --type unit_test --command "pytest"
harness evidence attach --type build --file external-proof.json
harness finding resume-review FND-001
```

## Rules

### PASS

```text
harness gate prints DECISION: CONVERGED
→ harness transition DONE
→ report to user with gate output attached
```

Never `harness transition CONVERGED`. Only `harness gate` may enter CONVERGED.

### Continue

All three hold:

```text
Gate BLOCKED
+ 存在明确可处理 blocker（每个 blocker 有明确的下一状态）
+ iteration < max_iterations
→ increment iteration, leave BLOCKED / return to appropriate state
```

Blocker dispatch:

- open finding → REPRODUCING (via reproduce-finding)
- unverified requirement / red verification → IMPLEMENTING

### Escalate

Any one holds → transition to ESCALATED:

```text
iteration >= max_iterations                          -> detected by harness gate
same finding VERIFIED then open again (regression)   -> detected by harness gate
same invariant repeatedly violated                   -> human/skill declares
test suite unstable                                  -> human/skill declares
architecture defect suspected                        -> human/skill declares
spec ambiguity blocks verification                   -> human/skill declares
```

Output exactly one reason code:

```text
SPEC_AMBIGUITY | ARCHITECTURE_DEFECT | REPEATED_REGRESSION |
UNSTABLE_TEST  | REVIEW_DISAGREEMENT  | MAX_ITERATIONS
```

Code-detected codes (MAX_ITERATIONS, REPEATED_REGRESSION) are emitted by
`harness gate`. For the others YOU must declare them explicitly to the
user with evidence - never silently retry past a judgment-call blocker.

## Hard Boundaries

1. DONE only via CONVERGED → DONE, and CONVERGED only after `DECISION: CONVERGED`.
2. ESCALATED ends the autonomous loop. Report reason + full status to user;
   do not silently retry.
3. Never reset `iteration` to dodge `max_iterations`.

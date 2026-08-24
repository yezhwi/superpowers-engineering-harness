---
name: convergence
description: "Use when quality_gate.py has returned PASS or BLOCKED and the loop must decide to finish (CONVERGED/DONE), continue iterating, or escalate. Applies v0.1 escalation rules with no scoring."
---

# Convergence Skill

Decide whether the harness loop continues. v0.1 uses fixed rules only — no
scoring, no model confidence.

## Rules

### PASS

```text
Gate PASS
→ transition CONVERGED → DONE
→ report to user with gate output attached
```

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
iteration >= max_iterations
same confirmed finding repeatedly reappears
same invariant repeatedly violated
test suite unstable
architecture defect suspected
spec ambiguity blocks verification
```

Output exactly one reason code:

```text
SPEC_AMBIGUITY | ARCHITECTURE_DEFECT | REPEATED_REGRESSION |
UNSTABLE_TEST  | REVIEW_DISAGREEMENT  | MAX_ITERATIONS
```

## Hard Boundaries

1. DONE only via CONVERGED → DONE, and CONVERGED only after gate exit 0.
2. ESCALATED ends the autonomous loop. Report reason + full status to user;
   do not silently retry.
3. Never reset `iteration` to dodge `max_iterations`.

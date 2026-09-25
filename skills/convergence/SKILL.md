---
name: convergence
description: "Use when `harness gate` has printed DECISION: CONVERGED, CONTINUE, or ESCALATED and the loop must finish, resume, or stop. Applies autonomous convergence policy rules with no scoring."
---

# Convergence Skill

Decide whether the harness loop continues based on `harness gate` deterministic
evaluations. Uses fixed rules only — no scoring, no model confidence.

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

A printed `DECISION: CONTINUE` with `DIRECTIVE: RESUME_TYPED_RECOVERY` from `harness gate` grants autonomous permission
to resume via typed recovery, repair within bounds, and rerun `harness gate`
without prompting the user to continue.

```text
harness gate prints DECISION: CONTINUE (transitioned GATING -> BLOCKED, iteration incremented)
→ run harness resume
→ repair within bounded scope
→ collect fresh evidence
→ run harness gate
```

Only `DECISION: CONTINUE` **with** `DIRECTIVE: RESUME_TYPED_RECOVERY` permits resume. If directive is absent, unknown, or conflicts with decision, stop and inspect persisted task; do not follow `Next:` or call `harness resume`. This is not a request for routine continue permission.

Blocker dispatch from `harness resume`:
- open finding → REPRODUCING (via reproduce-finding)
- unverified requirement / red verification → IMPLEMENTING

### Escalate

`DECISION: ESCALATED` from `harness gate`, or any human/skill escalation trigger,
immediately stops autonomous execution. No `SPECIFYING`, `IMPLEMENTING`, or
evidence-collection resume is permitted. `DIRECTIVE: NONE` on `CONVERGED` or
`ESCALATED` ends the loop. It is not permission to resume. An unrecognized
`DIRECTIVE` is not permission to resume, and a free-text `Next:` line is not
a command.

Do not retry a command that failed because a credential is unavailable,
authorization was denied, or an external side effect was refused. Escalate
immediately.

Precedence is strictly fixed: `USER_AUTHORITY_REQUIRED` > `REPEATED_REGRESSION` > `NO_PROGRESS` > `MAX_ITERATIONS`.

```text
user authority required by current Gate blockers      -> detected by harness gate (USER_AUTHORITY_REQUIRED)
same finding VERIFIED then open again (regression)   -> detected by harness gate (REPEATED_REGRESSION)
identical blocker fingerprint repeated (no progress) -> detected by harness gate (NO_PROGRESS)
iteration >= max_iterations                          -> detected by harness gate (MAX_ITERATIONS)
same invariant repeatedly violated                   -> human/skill declares
test suite unstable                                  -> human/skill declares
architecture defect suspected                        -> human/skill declares
spec ambiguity blocks verification                   -> human/skill declares
```

Output exactly one reason code:

```text
SPEC_AMBIGUITY | ARCHITECTURE_DEFECT | REPEATED_REGRESSION |
UNSTABLE_TEST  | REVIEW_DISAGREEMENT  | MAX_ITERATIONS     |
NO_PROGRESS    | USER_AUTHORITY_REQUIRED
```

Code-detected codes (`USER_AUTHORITY_REQUIRED`, `REPEATED_REGRESSION`, `NO_PROGRESS`, `MAX_ITERATIONS`) are emitted by
`harness gate` only during GATING. Guard contract drift or unresolved decision instead emits
`POLICY: USER_AUTHORITY_REQUIRED` / `DIRECTIVE: HALT_AND_WAIT` and preserves task state. Stop without calling `harness gate` or `harness resume`; report blocker to user. Text directive is guidance, not authenticated approval. When Gate emits `DECISION: ESCALATED`, stop and report reason + blockers.
For the others YOU must declare them explicitly to the user with evidence — never silently retry past a judgment-call blocker.

## Hard Boundaries

1. DONE only via CONVERGED → DONE, and CONVERGED only after `DECISION: CONVERGED`.
2. ESCALATED ends the autonomous loop immediately. Report reason + full status to user;
   never route to `SPECIFYING`, never retry evidence collection, and do not silently continue.
3. When `DECISION: CONTINUE` and `DIRECTIVE: RESUME_TYPED_RECOVERY` both appear on a successful Gate call, resume and rerun `harness gate` autonomously. Otherwise stop and inspect persisted task; never infer permission from `DECISION:` alone.
4. Autonomous operations must NEVER execute:
   - git commit, git tag, or git push
   - package publishing or release deployment
   - granting Harness authorizations (`harness auth grant ...`)
   - accepting Decision records on behalf of user
5. Never reset `iteration` to dodge `max_iterations`.

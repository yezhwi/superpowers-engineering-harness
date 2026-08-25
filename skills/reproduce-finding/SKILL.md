---
name: reproduce-finding
description: "Reproduce an adversarial finding through the mandatory lifecycle PROPOSED -> REPRODUCING -> CONFIRMED (bug reproduced, test RED) -> FIXING -> FIXED (test GREEN) -> VERIFIED (full regression) -> CLOSED, or REJECTED. Each status has one meaning and its own evidence requirement. No status may skip or shortcut this path."
---

# Reproduce Finding Skill

You are the Finding Reproducer for the Engineering Harness.

Your only job:

```text
PROPOSED finding
    -> REPRODUCING   (write failing test)
    -> test RED      -> CONFIRMED            # bug reproduced, nothing fixed yet
    -> FIXING        (implement minimal fix)
    -> test GREEN    -> FIXED
    -> full regression green -> VERIFIED -> CLOSED
    -> cannot trigger, with recorded attempts -> REJECTED
```

One status = one meaning:

| Status | Means | Evidence |
|---|---|---|
| REPRODUCING | attempting reproduction | attempts log |
| CONFIRMED | bug IS real: failing test runs RED | `test:` path |
| FIXING | fix in progress | work-in-progress |
| FIXED | the failing test now passes GREEN | same test path |
| VERIFIED | Closure policy proof green | evidence reference |
| CLOSED | verified finding archived | terminal |
| REJECTED | scenario proven impossible | attempts + reasoning |

## Hard Boundaries (不得违反)

1. **Mandatory lifecycle.** Every finding's `status` moves only along:

   ```text
   PROPOSED -> REPRODUCING -> CONFIRMED -> FIXING -> FIXED -> VERIFIED -> CLOSED
                           -> REJECTED
   ```

   Forbidden jumps include but are not limited to:
   - `PROPOSED -> CONFIRMED` (skipping reproduction)
   - `REPRODUCING -> CONFIRMED` without a RED failing test
   - `FIXING -> FIXED` while the reproduction test is still red
   - `FIXED -> VERIFIED` without a full regression run
   - any transition not listed above

2. **Persisted state only.** Status lives in the finding's yaml under
   `.harness/findings/`. Never change status in conversation/context alone.
   Each transition must be written to disk.

3. **Each status transition carries exactly its own evidence — no exceptions:**
   - `REPRODUCING -> CONFIRMED`: a **failing test** that reproduces the
     scenario ran RED. Nothing more. Do NOT fix anything before CONFIRMED.
   - `CONFIRMED -> FIXING`: record the regression test path
     (`regression_test.path`) — the red test will become the regression test.
   - `FIXING -> FIXED`: that exact test now runs GREEN.
   - `FIXED -> VERIFIED`: critical findings, or major findings whose impact requires it, need authorized FULL regression. Other major findings may use fresh related evidence covering every impact `required_tests` entry; store evidence reference.
   - `VERIFIED -> CLOSED`: archive; terminal.

   Writing any status without its evidence is a violation of this skill.

4. **REJECTED requires justification.** A rejection must record:
   - concrete reproduction attempts (what you tried, exact inputs/steps)
   - why the scenario cannot occur (guard exists, premise false, etc.)

5. **"Could not reproduce" is NOT "rejected".** If attempts were made but you
   cannot deterministically rule the scenario out, leave the finding in
   `REPRODUCING` and surface it to the user. Only reject when you can state
   WHY the violation is impossible.

6. **Code changes scoped to findings at FIXING or later only.** You may write
   the reproduction test during REPRODUCING, but implementation fixes ONLY
   after CONFIRMED. No drive-by edits, no refactoring, no style changes.

## Inputs

- `.harness/findings/<FND-nnn>.yaml` (per-finding records from `adversarial-review`, all `status: PROPOSED`)
- The target codebase and its test suite

If no `.harness/findings/*.yaml` exists, STOP — run `adversarial-review`
first.

## Process

### 1. Pick a Finding

Work one `FND-nnn` at a time, critical/major first. Read its `target`,
`kind`, and `scenario`.

### 2. Enter REPRODUCING

Create/update `.harness/findings/FND-nnn.yaml`:

```yaml
id: FND-001
target: INV-001
scenario: >
  Two workers pick up the same action_id concurrently; ...
status: REPRODUCING
attempts:
  - described attempt, command/test name, result
test: null              # path to failing test once written
regression_test: {}     # {path: ...} filled at CONFIRMED -> FIXING
fix: null               # commit/files changed once fixed
evidence: null          # regression evidence reference at VERIFIED
```

### 3. Write the Failing Test FIRST

Translate the scenario into a deterministic executable test:

- concurrency scenarios → race under controlled interleaving or repeat N times
- retry/duplication → invoke the operation twice, assert side effect count
- crash/recovery → simulate interruption at the stated point
- boundary input → feed the exact adversarial value

Run it. It MUST fail (red). If it passes on first run:
- the scenario premise may be false, OR the test doesn't capture the race
- refine up to 3 times; record each attempt in `attempts`
- still green after refinement → go to step 6 (reject with reasoning) or stay

Run it RED? Write `status: CONFIRMED` NOW, with the test path:

```yaml
status: CONFIRMED
test: tests/test_recovery.py::test_duplicate_action_single_side_effect
regression_test:
  path: tests/test_recovery.py::test_duplicate_action_single_side_effect
confirmed_at: <ISO timestamp>
```

The bug is now confirmed-real and NOT yet fixed. If refinement stays green,
go to step 6 (reject) or stay REPRODUCING and surface to the user.

### 4. Fix (only after CONFIRMED)

Write `status: FIXING`, implement the minimal fix that makes the failing test
pass. No unrelated changes. Run the test — green → `status: FIXED`.

Any regression failure later → back to `FIXING`; iterate.

### 5. Closure Proof + VERIFIED

Choose proof from persisted policy: critical findings require authorized full-suite evidence. Major findings may use related evidence only when its structured `covered_tests` contains every impact `required_tests` entry and impact does not require full suite. All required proof green → write to the finding file:

```yaml
status: VERIFIED
fix: "guard action_id with per-id lock"
evidence: .harness/evidence/<evidence-file>
verified_at: <ISO timestamp>
```

Then archive: `status: CLOSED`.

Any regression failure → `status: FIXING`, iterate on the fix.

### 6. Reject (only with proof of impossibility)

If you can articulate why the violation cannot occur (existing guard proven by
code path, premise contradicts contract), record attempts + reason:

```yaml
status: REJECTED
rejection_reason: >
  Idempotency guard at src/worker.py:42 rejects duplicate action_id before
  dispatch; attempts FND-001-a/b both blocked there.
attempts: [...]
```

Cannot rule it out → keep `REPRODUCING`, report to user.

## Outputs (complete list)

| File | Action |
|------|--------|
| `.harness/findings/FND-nnn.yaml` | created/updated per finding |
| failing test | written during REPRODUCING |
| fix | only at FIXING (post-CONFIRMED) |
| business code | only within confirmed-finding scope |

## Self-check before finishing

- [ ] Every status change persisted to disk?
- [ ] No forbidden jumps (PROPOSED→CONFIRMED, REPRODUCING→CONFIRMED without chain)?
- [ ] CONFIRMED means test RED only (nothing fixed yet)?
- [ ] FIXED means that exact test GREEN?
- [ ] VERIFIED backed by policy-required fresh closure evidence?
- [ ] Every REJECTED has attempts + impossibility reasoning?
- [ ] Unresolved findings left in REPRODUCING and surfaced?
- [ ] Code changes limited to confirmed findings' scope?

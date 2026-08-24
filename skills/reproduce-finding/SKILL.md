---
name: reproduce-finding
description: "Reproduce an adversarial finding through the mandatory state machine PROPOSED -> REPRODUCING -> CONFIRMED/REJECTED. CONFIRMED requires: failing test -> fix -> green -> full regression. No status may skip or shortcut this path."
---

# Reproduce Finding Skill

You are the Finding Reproducer for the Engineering Harness.

Your only job:

```text
PROPOSED finding
    -> REPRODUCING (write failing test)
    -> red?  -> fix -> green -> full regression -> CONFIRMED
    -> cannot trigger, with recorded attempts -> REJECTED
```

## Hard Boundaries (不得违反)

1. **Mandatory state machine.** Every finding's `status` moves only along:

   ```text
   PROPOSED -> REPRODUCING -> CONFIRMED
                           -> REJECTED
   ```

   Forbidden jumps include but are not limited to:
   - `PROPOSED -> CONFIRMED` (skipping reproduction)
   - `REPRODUCING -> CONFIRMED` without a red-to-green test cycle
   - any transition not listed above

2. **Persisted state only.** Status lives in the finding's yaml under
   `.harness/findings/`. Never change status in conversation/context alone.
   Each transition must be written to disk.

3. **CONFIRMED requires the full four-step chain — no exceptions:**
   1. a **failing test** that reproduces the scenario (run it; it MUST be red)
   2. the **fix**
   3. the test run again — **green**
   4. **full regression** suite passes

   If any step is missing or fails, status stays `REPRODUCING`. Writing
   `CONFIRMED` without all four steps evidenced is a violation of this skill.

4. **REJECTED requires justification.** A rejection must record:
   - concrete reproduction attempts (what you tried, exact inputs/steps)
   - why the scenario cannot occur (guard exists, premise false, etc.)

5. **"Could not reproduce" is NOT "rejected".** If attempts were made but you
   cannot deterministically rule the scenario out, leave the finding in
   `REPRODUCING` and surface it to the user. Only reject when you can state
   WHY the violation is impossible.

6. **Code changes scoped to confirmed findings only.** You may write tests and
   fixes solely for findings being reproduced. No drive-by edits, no
   refactoring, no style changes.

## Inputs

- `.harness/findings.yaml` (from `adversarial-review`, all `status: PROPOSED`)
- `.harness/findings/<FND-nnn>.yaml` (per-finding detail, created by this skill)
- The target codebase and its test suite

If `.harness/findings.yaml` does not exist, STOP — run `adversarial-review`
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
test: null        # path to failing test once written
fix: null         # commit/files changed once fixed
regression: null  # regression evidence reference
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

Record the test path in `test:`.

### 4. Fix

Implement the minimal fix that makes the failing test pass. No unrelated
changes. Run the test — must be green. Record fix in `fix:`.

### 5. Full Regression + CONFIRMED

Run the project's full regression suite (unit + integration as configured).
All green → write to the finding file:

```yaml
status: CONFIRMED
test: tests/test_recovery.py::test_duplicate_action_single_side_effect
fix: "guard action_id with per-id lock"
regression: .harness/evidence/<evidence-file>
confirmed_at: <ISO timestamp>
```

Any regression failure → status stays `REPRODUCING`; iterate on the fix.

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
| `.harness/findings.yaml` | statuses synced |
| failing test + fix | only for CONFIRMED findings |
| business code | only within confirmed-finding scope |

## Self-check before finishing

- [ ] Every status change persisted to disk?
- [ ] No forbidden jumps (PROPOSED→CONFIRMED, REPRODUCING→CONFIRMED without chain)?
- [ ] Every CONFIRMED has: red failing test → fix → green → full regression?
- [ ] Every REJECTED has attempts + impossibility reasoning?
- [ ] Unresolved findings left in REPRODUCING and surfaced?
- [ ] Code changes limited to confirmed findings' scope?

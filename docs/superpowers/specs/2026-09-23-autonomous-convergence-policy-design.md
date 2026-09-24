# Autonomous Convergence Policy — Design

## Goal

After user confirms task scope and design, agent advances Harness lifecycle without asking for repetitive `continue` input. Agent stops only for decisions requiring user authority or when convergence cannot safely proceed.

## Policy

- `CONVERGED`: finish task and report result.
- `CONTINUE`: agent diagnoses blocker, applies bounded fix, collects fresh evidence, and reruns Gate.
- `ESCALATED`: stop and report blocker, evidence, attempted actions, and choices.
- Stop immediately for requirement ambiguity/conflict, authorization or permission boundary change, destructive or externally visible action (commit, tag, push, publish, deploy), or explicit user hold.

## Loop Guards

Existing per-task `iteration` and `max_iterations` remain routing authority.

1. Default maximum is five `CONTINUE` iterations. Exceeding budget produces `ESCALATED: MAX_ITERATIONS`.
2. A finding with `verified_at` that becomes open again produces immediate `ESCALATED: REPEATED_REGRESSION`.
3. New early-stop: two consecutive successful Gate convergence assessments with identical blocker fingerprint produce `ESCALATED: NO_PROGRESS`.
4. `CONTRACT_CHANGED`, `SCOPE_DRIFT_API`, `SCOPE_DRIFT_PERMISSION`, `SCOPE_DRIFT_PERSISTENCE`, and `DECISION_UNRESOLVED` immediately produce `ESCALATED`. The agent must not automatically resume into `SPECIFYING`, realign scope, or collect evidence while one of these blockers is present.

Fingerprint sorts all blockers by `code`, `category`, `source`, `requirement_id`, `invariant_id`, then `finding_id`; each missing value and `null` normalize to same empty value. Each sorted blocker contributes those six fields. It excludes human-readable message text, timestamps, workspace fingerprints, and iteration count. Thus cosmetic diagnostic changes do not reset budget; a materially different blocker does.

No stored fingerprint/count means no prior observation: first blocked Gate stores fingerprint with count `1`. Malformed present metadata fails validation. On changed fingerprint, replace it and set count `1`; on identical fingerprint, increment count. On `PASS`, delete both fields rather than retaining a zero count or stale fingerprint.

## State and Data Flow

`harness gate` remains single convergence authority:

```text
GATING -> PASS -> clear convergence fingerprint/count -> CONVERGED
GATING -> blocked/user-authority blocker -> ESCALATED: USER_AUTHORITY_REQUIRED
GATING -> blocked/new fingerprint -> BLOCKED, iteration += 1 -> resume/recover/fix
GATING -> blocked/same fingerprint on next successful GATING assessment -> ESCALATED: NO_PROGRESS
GATING -> blocked/iteration >= max_iterations -> ESCALATED: MAX_ITERATIONS
```

Escalation precedence is fixed: `USER_AUTHORITY_REQUIRED`, then `REPEATED_REGRESSION`, then `NO_PROGRESS`, then `MAX_ITERATIONS`, then `CONTINUE`. `USER_AUTHORITY_REQUIRED` is the reason when any blocker code is `CONTRACT_CHANGED`, `SCOPE_DRIFT_API`, `SCOPE_DRIFT_PERMISSION`, `SCOPE_DRIFT_PERSISTENCE`, or `DECISION_UNRESOLVED`. It wins even when a reopened finding, a repeated fingerprint, or an exhausted iteration budget is also present. A verification blocker in the same assessment does not select `VERIFYING` while one of these codes is present. Two consecutive observations require two successful convergence assessments from `GATING`; a repeated Gate command while state is `BLOCKED` is invalid and never increments count.

Persist previous blocker fingerprint and consecutive count in `current-task.yaml`. Persisted state survives agent/session restart and is schema-validated when fields are present.

Agent orchestration reads result only:

```text
CONVERGED: transition DONE/report
CONTINUE: use typed recovery only for bounded repair; resume, fix, collect evidence, and rerun Gate
ESCALATED: report and wait
```

No new workflow or parallel Gate is introduced.

## Errors and Safety

- Missing convergence metadata is valid legacy state and is initialized on first blocked Gate; malformed present metadata fails Harness validation.
- No automatic command may cross authorization boundary.
- `NO_PROGRESS` includes current blockers and prior fingerprint in output for diagnosis.
- Agent does not retry a command that failed due to unavailable credential, authorization denial, or external side-effect protection; it escalates immediately.

## Testing

Add control-plane tests for:

1. legacy task without convergence metadata returns `CONTINUE` and initializes fingerprint/count;
2. first blocker fingerprint returns `CONTINUE` and records count `1`;
3. second consecutive identical blocker assessment returns `ESCALATED: NO_PROGRESS`;
4. changed blocker replaces fingerprint, resets count, and may continue;
5. `PASS` deletes fingerprint/count;
6. persisted metadata survives reload and schema rejects malformed present metadata;
7. `CONTRACT_CHANGED`, every `SCOPE_DRIFT_*` code, and `DECISION_UNRESOLVED` immediately escalate as `USER_AUTHORITY_REQUIRED` without entering the repair loop, including when an evidence blocker is also present;
8. existing five-iteration and reopened-regression escalation remain unchanged, and a simultaneous user-authority blocker outranks both.

Existing Gate and state-transition tests remain regression coverage.

## Non-goals

- No interactive `y/n` prompt.
- No autonomous commit, tag, push, publish, deploy, authorization, or Decision acceptance.
- No change to existing `max_iterations` default.

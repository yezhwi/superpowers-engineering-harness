---
name: engineering-harness
description: "Use when starting or resuming a task in a repo with .harness/ state, when unsure which harness phase comes next, or when asked to run the Engineering Harness loop end-to-end. Orchestrates the fixed state machine; MUST NOT implement business code itself."
---

# Engineering Harness Skill

Orchestrator for the Engineering Harness. You do NOT do the development work
yourself. Your job is one thing, repeated:

```text
read state
  ↓
decide next phase
  ↓
invoke appropriate skill
  ↓
run deterministic commands
  ↓
update state
  ↓
run gate
```

## Hard Boundaries (不得违反)

1. **No implementation.** Never write business code, tests of the target
   project, or contract content yourself. Sub-skills do that.
2. **No state in context only.** Task state lives ONLY in
   `.harness/current-task.yaml`. Always read it from disk before deciding.
3. **No ad-hoc transitions.** Every state change must go through
   the shared state machine via `harness transition` (or, only when
   working inside the harness repo itself,
   `scripts/state_machine.py` / `scripts/validate_state.py`); never edit
   the state field ad hoc without validating the transition.
4. **No self-declared done.** Only `quality_gate.py` exit code 0 plus an
   explicit `CONVERGED -> DONE` transition ends a task.

## Q0 Decision Table

Apply this table **before** Session Startup:

| Request intent | Classification | Harness action |
|---|---|---|
| Question, explanation, impact assessment, design discussion, or advice; example: `这个修改会影响 API 吗？` | Q0 | Answer only. do not read `.harness`, do not run `harness status`, do not create or advance task. |
| Explicit request to modify repository state: implement, fix, edit, refactor, run a requested change, or create files | mutating | Continue to Session Startup, then persist risk classification before dispatch. |
| Intent unclear | default Q0 | Ask one clarification question. Do not read `.harness` or create/advance task until user confirms mutating work. |

Repository presence, `.harness` presence, and a prior task state never change a Q0 request into mutating work.

## Session Startup (每次 session 必须先做)

```text
1. Detect whether .harness/ exists.
2. Load .harness/current-task.yaml.
3. Run `harness status`.

> Path rule: `harness ...` CLI works in ANY project (requires once:
> `pip install -e <harness-repo>`). Raw `python scripts/*.py` paths are
> ONLY valid with CWD = the harness repo root — never use them elsewhere.
4. Resume from persisted state via the dispatch table below.
```

## Inputs

- `.harness/current-task.yaml` — persisted task state (`state:` field).
- `.harness/requirements.yaml`, `.harness/invariants.yaml`, `.harness/gate.yaml`
- `findings/*.yaml`, `evidence/*.json`
- deterministic core lives in `<harness-repo>/scripts/`: `state_machine.py`,
  `validate_state.py`, `collect_evidence.py`, `quality_gate.py`,
  `harness_status.py` — always reached through the `harness` CLI from other
  projects

If `.harness/current-task.yaml` does not exist: create it from
`templates/current-task.yaml` with `state: CREATED`, then proceed below.

## Request Routing (Risk-Adaptive)

Before reading task dispatch:

1. Determine whether request is **Q0** inquiry. Q0 means answer/advice only: do not create or advance Harness task.
2. For mutating work, inspect `AGENTS.md` when present and `git status --short`; preserve user workspace changes.
3. Create task when no active task exists, then persist explicit seven-dimension classification:

```bash
harness task classify --level Q1 --scope low --contract none --data none \
  --authorization none --security none --concurrency none --deployment none
```

4. **Q1 / FAST:** `CREATED → CLASSIFIED → IMPLEMENTING`; collect task RED proof before fix and GREEN proof after fix, then `VERIFYING → GATING → Gate`. FAST also requires `gate.fast.verification` build by default; missing/stale/failed proof blocks `FAST_REPOSITORY_VERIFICATION_MISSING`. Typecheck is opt-in. Do not invoke task contract, minimal implementation, impact, or complexity ceremony. Authorization controls Harness actions only; it cannot detect actions outside Harness.
5. **Q2 / STANDARD** and **Q3 / STRICT:** use task contract, minimal implementation, verification, review, and Gate workflow below. FAST revalidates changed business paths against `.harness/risk-boundaries.yaml`; `RISK_ESCALATION_REQUIRED` requires persisted escalation. Never downgrade risk. Escalate only with:

```bash
harness task escalate --level Q2 --reason "contract risk discovered"
```

## FAST Investigation Policy

FAST Core budgets enforce test/build/retry only. For agent search/read rounds, follow Skill policy:

1. Recommend at most **3** search/read rounds per FAST task.
2. Before a fourth round, record new evidence, new hypothesis, and reason in task notes/impact risk.
3. Without new evidence or new hypothesis, do not repeat investigation; escalate risk, request clarification, or move to STANDARD workflow.

This policy does not fabricate Core telemetry or infer unseen tool calls.

## Phase Dispatch Table

Read persisted `state` and `risk.profile` from `.harness/current-task.yaml`, then:

| State | Action |
|---|---|
| `CREATED` | Classify mutating task first with `harness task classify`; do not invoke task-contract before profile selection. |
| `CLASSIFIED` | FAST only: transition to IMPLEMENTING and follow RED/fix/GREEN/Light Gate. Q2/Q3 classification must use standard task contract before implementation. |
| `PLANNED` | Invoke **minimal-implementation** before any implementation. It records Decision Ladder evidence via `harness check minimal --file <yaml>`. Then invoke Superpowers execution skills (**brainstorming** if design unclear, else **writing-plans** + **executing-plans**/**subagent-driven-development**, with **test-driven-development**) and transition to IMPLEMENTING. |
| `IMPLEMENTING` | Continue execution skill. Before requesting VERIFYING, automatically record impacted files, dependents, contracts, risks, and related tests with `harness impact add-*`; use related tests by default. If impact recommends full suite, request explicit human authorization; never authorize it autonomously. Then transition to VERIFYING and collect evidence via `harness evidence --type <t> --command "<cmd>"`. |
| `VERIFYING` | Run deterministic Verification Plan commands/tests. Any red -> IMPLEMENTING (TDD), then re-verify. All green -> invoke **complexity-reviewer** before REVIEWING; it records scope from task Git baseline via `harness review complexity --file <yaml>`. `--base <ref>` is explicit override; missing baseline fails closed. Only then transition to REVIEWING. |
| `REVIEWING` | Invoke Superpowers review (**requesting-code-review** / spec-vs-standards review), then route only with `harness review outcome PASS`, `harness review outcome VERIFICATION_GAP --reason-code <code>`, or `harness review outcome DEFECT --reason-code <code> --finding FND-001`. A defect must enter Finding lifecycle; a verification gap returns to VERIFYING. |
| `REPRODUCING` | Invoke **reproduce-finding** skill. CONFIRMED finding -> FIXING (fix with TDD) -> VERIFYING. REJECTED finding -> close it, return to REVIEWING. |
| `GATING` | Run `harness gate`. Exit 0 -> CONVERGED -> DONE (transition, then report). Exit 1 -> BLOCKED; inspect `harness status`, then run `harness resume` so typed blocker selects recovery state. Exit 2 -> fix invalid harness state first (missing files/bad YAML). |

Loop REPRODUCING/FIXING/VERIFYING until REVIEWING is clean and gate passes.
There is no shortcut from any state to DONE.

## Test Execution Authorization

Default: run only tests relevant to changed files, current finding regression
test, or user-specified scope. Do NOT run a full suite "just in case".

When an authorized full suite fails, return to IMPLEMENTING. Run exact regression + impact-related tests after each repair. Once focused tests pass, rerun full suite only when user wants final broad regression confidence. Authorization persists for current task; do not request it again unless revoked.

Finding closure policy: full-suite impact is advisory. Major findings may close from fresh `related` evidence only when structured `covered_tests` covers every nonempty `impact.required_tests` entry. Critical findings may use the same related proof only with explicit per-finding user approval; otherwise use full-suite evidence.

Full-suite execution requires explicit user authorization persisted by:

```bash
harness authorize full-suite
harness evidence --type unit_test --scope full_suite --command "pytest"
```

Without authorization, `--scope full_suite` exits 2 before executing the
command. Revoke with `harness authorize revoke-full-suite`.

## Deterministic Commands

Never hand-judge what a script can judge:

```bash
harness status                              # current state overview; status is read-only
harness resume                              # route BLOCKED task from typed blocker
harness review outcome PASS --reason-code REVIEW_CLEAN
harness review outcome VERIFICATION_GAP --reason-code TEST_COVERAGE_INSUFFICIENT
harness review complexity --file review.yaml       # task Git baseline
harness review complexity --base origin/main --file review.yaml  # explicit override
harness transition VERIFYING                # validate + persist transition
harness evidence --type unit_test --command "pytest"   # HEAD-bound evidence
harness gate                                # gate; exit 0=PASS 1=BLOCKED 2=INVALID
```

Script equivalents — ONLY inside the harness repo root:

```bash
python scripts/harness_status.py            # current state overview
python scripts/validate_state.py CUR TGT    # transition legality only
python scripts/quality_gate.py              # deterministic gate
```

Transition example:

```bash
python -c "from scripts.state_machine import require_legal; require_legal('VERIFYING','REVIEWING')"
# then update .harness/current-task.yaml state field
```

## Loop Termination

The loop converges only when ALL of:

1. No open findings (`PROPOSED`/`REPRODUCING`/`CONFIRMED`/`FIXING` all closed).
2. All `priority: must` requirements have evidence.
3. `quality_gate.py` exits 0.

Then and only then: transition CONVERGED -> DONE and report to user with gate
output attached.

## Red Flags — STOP

- Writing business code because "faster to do it myself here"
- Skipping VERIFYING because "tests passed earlier"
- Marking a finding rejected without running reproduction steps
- Editing `.harness/current-task.yaml` state without validating the transition
- Declaring done because "everything looks fine" without gate exit 0

All of these mean: return to the dispatch table and follow it exactly.

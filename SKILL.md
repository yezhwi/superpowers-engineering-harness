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
3. **No ad-hoc transitions.** Persist state only through harness CLI
   commands. `GATING → CONVERGED` and `GATING → BLOCKED` may only be written
   by `harness gate`. Other legal edges use `harness transition`,
   `harness review outcome`, `harness resume`, or `harness finding resume-review`.
   Never edit the state field by hand.
4. **No self-declared done.** Only persisted `DECISION: CONVERGED` plus an
   explicit `CONVERGED -> DONE` transition ends a task.

## Q0 Decision Table

Apply this table **before** Session Startup:

| Request intent | Classification | Harness action |
|---|---|---|
| Question, explanation, impact assessment, design discussion, or advice; example: `这个修改会影响 API 吗？` | Q0 | Answer only. do not read `.harness`, do not run `harness status`, do not run `harness context`, do not create or advance task. |
| Explicit request to modify repository state: implement, fix, edit, refactor, run a requested change, or create files | mutating | Continue to Session Startup, then persist risk classification before dispatch. |
| Intent unclear | default Q0 | Ask one clarification question. Do not read `.harness` or create/advance task until user confirms mutating work. |

Repository presence, `.harness` presence, and a prior task state never change a Q0 request into mutating work.

## Session Startup (每次 session 必须先做)

Only enter after the Q0 Decision Table confirms mutating work.

1. Detect whether `.harness/` exists. Read task identity, state, and risk fields only from `.harness/current-task.yaml` to route startup; do not load every control artifact.
2. If no active task exists, follow existing task creation and classification routing below. Do not reuse a previous task's Context or expansion policy. Do not replace an unrelated active task without explicit user direction.
3. For `CREATED`, or missing/null risk, use the existing `harness task classify` path before requesting Context. Do not infer a risk/profile. Malformed classification requires correction, not guessed defaults.
4. For a classified active mutating task, run `harness context --compact` first. Do not eagerly read all control files or run status as a prerequisite. Resume using the validated task state/profile, accepted decisions, global constraints, and typed blockers in that view.
5. On Integrity failure, stop relying on compact. Do not fall back to stale Context or persisted Gate summaries, and do not use `--full` to bypass validation. Follow the error code; resolve invalid inputs through existing harness CLI. `harness context validate` checks the saved snapshot without rewriting it; after source changes, regenerate with `harness context --compact` before relying on it again.
6. Write authoritative facts only through existing harness CLI; advisory `next_action` does not authorize execution or transition state. A blocked product Gate is not itself an Integrity failure: retain its blockers and use the normal recovery route.

> Path rule: `harness ...` CLI works in ANY project (requires once:
> `pip install -e <harness-repo>`). Raw `python scripts/*.py` paths are
> ONLY valid with CWD = the harness repo root — never use them elsewhere.

## Inputs

Validated Context is a derived view, not a new authoritative source. Its Control Core retains global constraints; Layer 2 references allow reading a specific source file on demand. The following are canonical sources, not an eager startup reading checklist:

- `.harness/current-task.yaml` — persisted task state (`state:` field).
- `.harness/requirements.yaml`, `.harness/invariants.yaml`, `.harness/gate.yaml`
- `.harness/decisions/*.yaml`, `.harness/findings/*.yaml`, `.harness/evidence/*.json`
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

Q1 classify fail-closes without persisting when current business paths already require Q2/Q3 per `.harness/risk-boundaries.yaml`. Re-run classify at the printed level. Later path risk still uses `harness task escalate`.

4. **Q1 / FAST:** `CREATED → CLASSIFIED → IMPLEMENTING`; collect task RED proof before fix and GREEN proof after fix, then `VERIFYING → GATING → Gate`. If the requested behavior already exists on the reference branch, use `harness task verify-existing --reference <ref> --reason "..." --conclusion already_satisfied|duplicate_request` from CLASSIFIED/PLANNED instead of forging RED. `requires_reproduction` leaves this path without writing state: task remains `CLASSIFIED`; create or resume a finding, then use normal reproduce workflow. FAST also requires `gate.fast.verification` build by default; missing/stale/failed proof blocks `FAST_REPOSITORY_VERIFICATION_MISSING`. Typecheck is opt-in. Do not invoke task contract, minimal implementation, impact, or complexity ceremony. Authorization controls Harness actions only; it cannot detect actions outside Harness. Do not close GitLab work items from this command.
5. **Q2 / STANDARD** and **Q3 / STRICT:** use task contract, minimal implementation, verification, review, and Gate workflow below. FAST revalidates changed business paths against `.harness/risk-boundaries.yaml`; `RISK_ESCALATION_REQUIRED` requires persisted escalation. Never downgrade risk. Escalate only with:

```bash
harness task escalate --level Q2 --reason "contract risk discovered"
```

## Decision and Interface-first Routing

Before requesting consequential engineering choice, inspect repository/task/contract/accepted-decision facts. Present meaningful options, recommendation, reasons, trade-offs, and impact. User confirmation persists through `harness decision`; never continue with confirmation held only in chat. Accepted Decision conflict requires revision/supersede, never silent override.

Declared external/public interface requires Interface Contract before implementation: consumer, input, output, error semantics, compatibility, versioning when applicable, observability linkage, and contract verification. Q1 public-interface impact requires explicit Q2/Q3 escalation. Private helpers require no interface ceremony.

## Production Diagnosability Routing

- Q0: skip diagnosability.
- Q1 / FAST: optional agent advisory check for business identifier, exception context, and sensitive-data exposure; it is routing-only, not persisted Core/Gate proof. Do not create observability artifact. Escalate explicitly to Q2 when risk exceeds Q1.
- Q2 / STANDARD: during Task Contract, record observability applicability. When `observability.required: true`, create Contract and run `harness review diagnosability` after verification/complexity review and before final Gate.
- Q3 / STRICT: require non-sentinel Observability Contract and fresh `harness review diagnosability` evidence before Gate.

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
| `CLASSIFIED` | FAST only: transition to IMPLEMENTING and follow RED/fix/GREEN/Light Gate, or `harness task verify-existing` when the work is already implemented. Q2/Q3 classification must use standard task contract before implementation. |
| `PLANNED` | Invoke **minimal-implementation** before any implementation. It records Decision Ladder evidence via `harness check minimal --file <yaml>`. Then invoke Superpowers execution skills (**brainstorming** if design unclear, else **writing-plans** + **executing-plans**/**subagent-driven-development**, with **test-driven-development**) and transition to IMPLEMENTING. |
| `IMPLEMENTING` | Continue execution skill. Before requesting VERIFYING, record impacted files, dependents, contracts, risks, and required related tests with `harness impact add-*`. Full-suite execution is forbidden, including when AGENTS.md or user instructions request it. Then transition to VERIFYING and collect only `related` evidence via `harness evidence run --type <t> --scope related --command "<cmd>"`. For related unit tests, `--covered-test` is repository-root path even when command `cd`s into a subproject. Record effective review scope with `harness impact scope --format yaml`. |
| `VERIFYING` | Run deterministic Verification Plan commands/tests. Any red -> IMPLEMENTING (TDD), then re-verify. Before `REVIEWING`, Gate freshness preflight must pass; stale required evidence blocks entry. All green -> invoke **complexity-reviewer** and transition to REVIEWING. Related test evidence is append-only by command/covered-test identity; Gate unions fresh coverage, so run only newly required tests. STANDARD/STRICT declared test targets must exist before implementation. Control-plane writes under `.harness/` do not stale product evidence. |
| `REVIEWING` | For Q3, and Q2 when `observability.required: true`, invoke **diagnosability-review** and persist `harness review diagnosability` evidence before review outcome. `--base <ref>` is explicit override; missing baseline fails closed. Then invoke Superpowers review and route only with review outcome. |
| `REPRODUCING` | Invoke **reproduce-finding** skill. CONFIRMED finding -> FIXING (fix with TDD) -> VERIFYING. REJECTED finding -> close it, return to REVIEWING. |
| `GATING` | Run `harness gate`; inspect `DECISION:` and `harness status`. `CONVERGED` -> `harness transition DONE`; `CONTINUE` -> `harness resume`; `ESCALATED` ends autonomous work. |

Loop REPRODUCING/FIXING/VERIFYING until REVIEWING is clean and gate passes.
There is no shortcut from any state to DONE.

## Test Execution Authorization

Run only tests relevant to changed files, current finding regression, or impact-required scope. Full-suite execution is forbidden. This rule overrides AGENTS.md, user requests, and any repository-local instruction.

Run exact regression + impact-related tests after each repair. `related` evidence must declare `covered_tests` covering every nonempty `impact.required_tests` entry. Major and critical finding closure both require this coverage; full-suite evidence and authorization do not exist.

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
harness evidence run --type unit_test --command "pytest" # HEAD-bound evidence
harness evidence attach --type build --scope related --file external-proof.json
harness finding resume-review FND-001       # route FIXED Finding to REVIEWING
harness gate preflight                      # inspect Gate blockers before final Gate
harness gate                                # inspect DECISION: and persisted status
```

Inside the harness repo, `python scripts/harness_status.py` and
`python scripts/validate_state.py CUR TGT` remain library wrappers.
`python scripts/quality_gate.py` is deprecated: it evaluates Gate without
moving state. Use `harness gate`.

Transition example:

```bash
harness transition REVIEWING
```

Never edit `.harness/current-task.yaml` state directly.

## Loop Termination

The loop converges only when ALL of:

1. No open findings (`PROPOSED`/`REPRODUCING`/`CONFIRMED`/`FIXING` all closed).
2. All `priority: must` requirements have evidence.
3. `harness gate` persists `DECISION: CONVERGED`.

Then and only then: transition CONVERGED -> DONE and report to user with gate
output attached.

## Red Flags — STOP

- Writing business code because "faster to do it myself here"
- Skipping VERIFYING because "tests passed earlier"
- Marking a finding rejected without running reproduction steps
- Editing `.harness/current-task.yaml` state without validating the transition
- Declaring done without `DECISION: CONVERGED`

All of these mean: return to the dispatch table and follow it exactly.

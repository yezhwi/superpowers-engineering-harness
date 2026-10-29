---
name: engineering-harness
description: "Use when starting or resuming a task in a repo with .harness/ state, when unsure which harness phase comes next, or when asked to run the Engineering Harness loop end-to-end."
compatibility: Requires Python 3.11+, Git, and a matching superpowers-engineering-harness CLI installed separately.
---

# Engineering Harness Skill

Route the Engineering Harness workflow through the appropriate skills. The
same session may execute the implementation skill; a skill invocation is not
a requirement to start another agent or Codex process. Repeat:

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

1. **Separate workflow roles, not mandatory processes.** Use the appropriate
   implementation/contract skill to do that work, inline or delegated. Choosing
   an executor does not grant permission or waive classification, verification,
   or native state admission. Review after implementation belongs to the user,
   a model the user names, or the dedicated Reviewer bot. Do not launch Codex
   to satisfy it.
2. **No state in context only.** Task state lives ONLY in
   `.harness/current-task.yaml`. Always read it from disk before deciding.
3. **No ad-hoc transitions.** Persist state only through harness CLI
   commands. `GATING → CONVERGED` and `GATING → BLOCKED` may only be written
   by `harness gate`. Other legal edges use `harness transition`,
   `harness review outcome`, `harness resume`, or `harness finding resume-review`.
   Never edit the state field by hand.
4. **No self-declared done.** Only stdout `DECISION: CONVERGED` from
   `harness gate`, followed by an explicit `CONVERGED -> DONE` transition,
   ends a task. `DECISION:` is command output, not a field in
   `current-task.yaml`. The persisted authority is `state: CONVERGED` and
   gate metadata.
5. **No PyPI or npm publication.** The user publishes the Python package and
   the skills package manually. Do not run `npm publish`, `twine upload`,
   `uv publish`, or create a registry release. Local `python -m build` and
   `npm pack --dry-run` are packaging checks. Control-plane publication
   (`transaction.publish`, Context publication, `harness architecture publish`)
   stays. Reading an already published npm version during install is not a publish.

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
4. For a classified active mutating task, run `harness context --compact` first. Do not eagerly read all control files or run status as a prerequisite. Resume from that command's short stdout (`context_hash`, `mode`, `head`, `control`, `working`, `omitted_count`, `blocker_count`). `harness status` scans the product tree and is not a substitute for this short stdout. The dispatch table still reads it after `harness gate`. Do not pass `--json` or `--full` for session resume, and do not paste `.harness/context/current.yaml` into the session; that file stays the full validated snapshot. To see one omitted object, read that canonical source by id.
5. On Integrity failure, stop relying on compact. Do not fall back to stale Context or persisted Gate summaries, and do not use `--full` to bypass validation. Follow the error code; resolve invalid inputs through existing harness CLI. `harness context validate` checks the saved snapshot without rewriting it; after source changes, regenerate with `harness context --compact` before relying on it again.
6. Write authoritative facts only through existing harness CLI; advisory `next_action` does not authorize execution or transition state. A blocked product Gate is not itself an Integrity failure: retain its blockers and use the normal recovery route. If a Guard command prints `POLICY: USER_AUTHORITY_REQUIRED` and `DIRECTIVE: HALT_AND_WAIT`, stop autonomous work and request user decision. This is not Gate `DECISION: ESCALATED`; do not run `harness resume`, `harness gate`, or rewrite state to bypass it. Text directive alone does not authenticate user approval. An unrecognized `DIRECTIVE` is not permission to resume, and a free-text `Next:` line is not a command.

> Path rule: `harness ...` CLI works in ANY project (requires once:
> `pip install -e <harness-repo>`). Raw `python scripts/*.py` paths are
> ONLY valid with CWD = the harness repo root — never use them elsewhere.

## Executor Continuity

Default to one implementation executor for the agreed scope. Use **executing-plans** in this session when the user chooses inline execution or no subagent tool is available; use **subagent-driven-development** when per-task delegation/review is explicitly chosen. Do not start Codex, `pi --provider openai-codex`, or a Codex review subagent from either route. Existing user restrictions on delegation still apply.

Keep the same executor for checker repairs, wording edits and diagnosed retries. Stop scheduling invalid proof, not the executor: retain failures, fix the diagnosed cause, then continue within existing authority and budgets. Change executors only for an explicit user handoff, an unavailable/exhausted or unrecoverable context, or a demonstrated independent parallel scope. Do not switch executors to obtain a Codex review. Code review after implementation is done by the user, a model the user names, or the dedicated Reviewer bot. A Codex quota or billing failure is not a workflow blocker and must not be retried. Record an executor handoff reason and pass only current source identity, completed work, remaining work and exact evidence references; do not restart completed work or add nested reviewers.

Before execution, record changed paths, verification commands/selectors, required build/review/Gate obligations and the conditions that require stopping. Reuse the existing plan or one brief task note, not another planning framework. If a mandatory workflow conflicts with the scope, explain it before adding work and obtain the required decision; do not silently bypass it. After content stabilizes, perform the required closeout. Later changes require affected verification under existing freshness rules, not unconditional full workflow replay.

## Verification Failure Triage

These are diagnostic categories, not new task states, exemptions or retry grants.

| Failure | Detection and next action | Evidence |
|---|---|---|
| Setup/checker failure | Import, path, schema lookup or oracle error: diagnose and repair in the same executor; inspect a bounded diagnostic before collecting a new valid RED. | Retain original checker/baseline identity and failure; setup failure is not product RED. |
| Product regression | A valid check demonstrates the requested missing/wrong behavior: fix the product through the selected implementation skill and verify affected scope. | Keep genuine RED and qualified GREEN; never rewrite old receipts or lower the requirement to pass. |
| Authority/policy refusal | On `BUDGET_OVERRIDE_REQUIRED`, use only the existing audited policy with required evidence/reason/hypothesis; on `HALT_AND_WAIT`, stop for user authority. | Keep counters, refusal and prior evidence; do not auto-override, reset budgets or create a new task to escape limits. |

Test proof requires actual `test_execution`, not selector strings alone. On `EVIDENCE_TEST_EXECUTION_INVALID`, follow collect-evidence's Actual Test Execution rules: diagnose infrastructure, use a supported reporter and collect fresh proof; never retrofit old receipts. RED is an assertion-style call failure, not an unchecked checker exception. Unsupported runners provide measurements only; semantic correctness remains a human review obligation.

Checker stability applies to the valid RED/GREEN pair. A setup failure does not freeze a broken oracle forever: preserve it, justify the repair independently of the desired result and start a newly identified pair. If a checker changes after valid RED, retain that history and establish new valid RED before claiming GREEN. Do not relabel a diagnostic as proof or repeatedly rerun without a new cause/fix.

## Documentation Verification

For a documentation-only scope, check factual status and intended sequence by human review; check link/anchor targets, versions, declared command syntax, scope and required historical preservation mechanically. Exact matching belongs to interfaces and stable identifiers, not ordinary wording: equivalent punctuation or synonyms must not force prose edits merely to satisfy an oracle. A checker repair needs a counterexample showing the intended defect remains rejected.

Use only required related tests and builds; a prose edit does not justify Core changes, full-suite execution, new dependencies or another executor. Required RED must demonstrate an actual requested change, not an intentional import/lookup failure or arbitrary wording constraint. If meaningful RED or a mandatory build cannot be provided, surface that conflict before execution and use only an explicitly authorized existing path; do not fabricate proof or silently waive Gate. Keep one concise record pointing to original logs, not repeated reports. Static guidance/link checks are not evidence of Agent obedience, semantic correctness or measured speedup.

## Efficient Evidence Scheduling

At startup, consume the existing validated admission output and blockers; do not automatically call another preflight, regenerate Context or add a renderer. When a separate evidence-planning diagnosis is needed before scheduling tests, use `harness evidence plan --json` for the unchanged v1 view. Explicit `harness evidence plan --preflight --json --command "python -m pytest tests/example.py"` adds v2 integrity/tool/capability diagnostics; the command string is classified, not executed. NATIVE_PROFILE_SUPPORTED is only reporter syntax qualification, not actual test_execution or execution authority. v2 exits 0/1/2 for clear/blocked/error diagnosis, never Gate PASS. An explicit `--skills-package /absolute/path/to/package.json` compares that manifest, not the Agent's loaded skills.

Only on explicit user request, `harness evidence plan --preflight --json --probe-launcher /absolute/path/to/harness` runs one unsandboxed local `--help` process with inherited environment/cwd. It may write files or access network; it is not a safe/read-only sandbox or version attestation. Capture is limited to 64KiB per stream and execution to 10 seconds plus bounded cleanup. Do not add this probe to normal startup or task-contract guidance. A non-Git invocation remains stderr-only and does not probe.

For a proposed binding/scope repair, inspect `harness impact reconcile --file proposal.yaml --dry-run` first. Static diagnostics are read-only advice, not execution authority, valid Context, or Gate acceptance; malformed inputs fail closed. Pending transaction recovery must follow its explicit route, not an implicit diagnostic repair.

Apply requires a trusted scope origin and the exact selected user grant for the proposed change. MIGRATE does not authorize RETIRE or REBIND. Missing origin/authority requires the user-authority route; do not remove required tests, freeze, accept a Decision, or resume to bypass blockers.

Persist legitimate metadata changes and actual Plan proof promptly. Once metadata is stable, generate the final view with `harness context --compact`; use `harness context validate` for independent saved-snapshot validation. Do not regenerate after every intermediate metadata edit, but never rely on a snapshot made stale by those edits. Keep startup integrity checks unchanged.

Collect only related missing/stale proof. Use the existing exact evidence reuse option described in collect-evidence; preserve historical RED. Tests sharing databases, ports, workspaces, or other mutually exclusive resources must run serial, not in parallel for speed. A successful diagnostic, benchmark, or test command never completes the task by itself.

For a large or known-slow related scope, preplan bounded batches before launching any test; do not wait for a timeout. Qualify duration history to the same source and environment, and treat unknown duration conservatively. Using roughly 50–70% of the available deadline is an illustrative safety margin, not a numeric mandate, limit, exemption, or deadline extension.

Record a planned batch manifest with exact commands and repository-root `--covered-test` selectors. Each batch must preserve the original selectors, select only missing fresh related coverage, and together form the complete required-test union so no required test is skipped. Run serial unless databases, ports, workspaces, and other resources are demonstrably disjoint. This is guidance only: it adds no automated scheduler and makes no claim of Agent obedience or measured performance; existing budget accounting, authority, collector, freshness, and Gate behavior remain unchanged.

## Inputs

Validated Context is a derived view, not a new authoritative source. Its Control Core retains global constraints; Layer 2 references allow reading a specific source file on demand. Open a file under `docs/` only when the task names that file. Do not search or open `.harness/history/`, `.harness/.publication-retained/`, `.harness/context-reuse-benchmark*`, `.harness/context-original-replay*`, `.harness/release-assets-v032/`, or `.superpowers/sdd/`, including with `--no-ignore`. Do not delete those trees. The following are canonical sources, not an eager startup reading checklist:

- `.harness/current-task.yaml` — persisted task state (`state:` field).
- `.harness/requirements.yaml`, `.harness/invariants.yaml`, `.harness/gate.yaml`
- `.harness/decisions/*.yaml`, `.harness/findings/*.yaml`, `.harness/evidence/*.json`
- deterministic core lives in `<harness-repo>/scripts/`: `state_machine.py`,
  `validate_state.py`, `collect_evidence.py`, `quality_gate.py`,
  `harness_status.py` — always reached through the `harness` CLI from other
  projects

If `.harness/current-task.yaml` does not exist: run `harness init`, then
follow task creation and classification below. Do not copy task templates by hand.

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
- Q2 / STANDARD: during Task Contract, record observability applicability. When `observability.required: true`, create Contract and run `harness review diagnosability` in VERIFYING before `VERIFYING -> REVIEWING`.
- Q3 / STRICT: require non-sentinel Observability Contract and fresh `harness review diagnosability` evidence in VERIFYING before `VERIFYING -> REVIEWING`.

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
| `IMPLEMENTING` | Continue execution skill. If the transition to VERIFYING prints `POLICY: USER_AUTHORITY_REQUIRED` and `DIRECTIVE: HALT_AND_WAIT`, stop and report to the user. Do not repair the contract, call `harness gate`, or realign on your own. Otherwise, before requesting VERIFYING, record impacted files, dependents, contracts, risks, and required related tests with `harness impact add-*`. Full-suite execution is forbidden, including when AGENTS.md or user instructions request it. Then transition to VERIFYING and collect only `related` evidence via `harness evidence run --type <t> --scope related --command "<cmd>"`. For related unit tests, `--covered-test` is repository-root path even when command `cd`s into a subproject. Record effective review scope with `harness impact scope --format yaml`. |
| `VERIFYING` | Run deterministic Verification Plan commands/tests. Classify failed verification using Verification Failure Triage; a genuine product regression -> IMPLEMENTING (TDD), then re-verify. For Q3, and Q2 when `observability.required: true`, invoke **diagnosability-review** and persist evidence before `VERIFYING -> REVIEWING`; Gate freshness preflight must pass; stale required evidence blocks entry. All green -> invoke **complexity-reviewer** and transition to REVIEWING. Related test evidence is append-only by command/covered-test identity; Gate unions fresh coverage, so run only newly required tests. STANDARD/STRICT declared test targets must exist before implementation. Control-plane writes under `.harness/` do not stale product evidence. |
| `REVIEWING` | Wait for the user, a user-named model, or the dedicated Reviewer bot. Do not call Codex. Route only with `harness review outcome` after that review. Native `harness review complexity` and `harness review diagnosability` stay local and do not call Codex. |
| `REPRODUCING` | Invoke **reproduce-finding** skill. CONFIRMED finding -> FIXING (fix with TDD) -> VERIFYING. REJECTED finding -> close it, return to REVIEWING. |
| `GATING` | Run `harness gate`; inspect stdout `DECISION:` and `harness status`. `DECISION: CONVERGED` with `DIRECTIVE: NONE` -> `harness transition DONE`; `CONTINUE` with `DIRECTIVE: RESUME_TYPED_RECOVERY` -> `harness resume`; `ESCALATED` with `DIRECTIVE: NONE` ends autonomous work. |

Loop REPRODUCING/FIXING/VERIFYING until REVIEWING is clean and gate passes.
There is no shortcut from any state to DONE.

## Test Execution Authorization

Run only tests relevant to changed files, current finding regression, or impact-required scope. Full-suite execution is forbidden. This rule overrides AGENTS.md, user requests, and any repository-local instruction.

Run exact regression + impact-related tests after each repair. `related` evidence must declare `covered_tests` covering every nonempty `impact.required_tests` entry. Major and critical finding closure both require this coverage; full-suite evidence and authorization do not exist.

## Deterministic Commands

Use deterministic commands for machine-checkable facts; human semantic review supplements them and never replaces native Gate/state authority:

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
`python scripts/quality_gate.py` is disabled: it prints a deprecation notice
and exits with code `2` without evaluating Gate. Use `harness gate`.

The task loop does not run `harness converge`, `harness benchmark`, `harness review session`, `harness review batches`, or `harness plan sync-markdown`. Do not start `harness evidence plan --probe-launcher` during the task loop; its explicit-request hazards stay in Efficient Evidence Scheduling. Do not use `harness telemetry report` as a speed result: an empty `token_estimate` is not a measurement.

Transition example:

```bash
harness transition REVIEWING
```

Never edit `.harness/current-task.yaml` state directly.

## Loop Termination

The loop converges only when ALL of:

1. No open defect findings (`PROPOSED`/`REPRODUCING`/`CONFIRMED`/`FIXING`). Alignment audit findings stay on disk and do not block DONE.
2. All `priority: must` requirements have evidence.
3. `harness gate` prints stdout `DECISION: CONVERGED`. Persisted authority is `state: CONVERGED` and gate metadata.

Then and only then: transition CONVERGED -> DONE and report to user with gate
output attached.

## Red Flags — STOP

- Treating an inline implementation skill as permission to skip verification or native admission
- Skipping VERIFYING because "tests passed earlier"
- Marking a finding rejected without running reproduction steps
- Editing `.harness/current-task.yaml` state without validating the transition
- Declaring done without `DECISION: CONVERGED`

All of these mean: return to the dispatch table and follow it exactly.

# Superpowers Engineering Harness v0.3.2

[简体中文](README.zh-CN.md)

Engineering Harness is a deterministic control plane around [Superpowers](https://github.com/obra/superpowers) development workflows. It does not replace agent or worker skills. It persists task state, requires proof, and prevents an agent from declaring work done without gate approval.

[Architecture: big picture](docs/architecture.md)

## v0.3.2 compatibility and measurement status

`v0.3.2 development candidate`: version metadata is prepared, not a published release or formal Gate acceptance. Pinned installer examples below remain on v0.3.1 current release until separate release authorization; do not assume a v0.3.2 tag exists.

Context now batches automatic expansion; eligibility loss commits its legal prefix and stops, while genuine prepublication errors write no new events. `harness evidence plan --json` and `harness impact reconcile --file proposal.yaml --dry-run` are read-only diagnostics, not execution authority. Keep shared-resource tests serial; use existing exact `--reuse-if-valid` without cross-HEAD inheritance or skipping RED/finding execution.

Profiling is opt-in via `harness context --compact --profile-json /tmp/context-profile.json`. A prepublication failure is exit 2. A postpublication profile-write OSError is exit 3, `PROFILE_WRITE_FAILED_CONTEXT_PUBLISHED context_published=true`: Context already exists; inspect and independently validate it instead of retrying blindly. Stdout errors are not this exit-3 classification.

Missing legacy scope origin fails closed with `TEST_SCOPE_AUDIT_INVALID`. Trusted origin plus transactional additions and Gate replay protect required tests; apply additionally requires exact selected RETIRE/REBIND authority. MIGRATE reconstructs provenance only. No automatic scope reconstruction, freeze/resume, risk downgrade or verified/COMPLETE status. Activated metadata requires a v0.3.2 reader; old readers reject the minimum-reader marker. See [explicit scope migration](docs/test-scope-migration.md) and [approved efficiency specification](docs/2026-10-14-context-evidence-collection-efficiency-spec.md).

[Actual Context measurements](docs/superpowers/reports/v032-context-efficiency.md): user-reduced80-sample dataset for N=0/1/10/50; remaining N=100 cancelled. Batch-heavy cold cases improve; N=0 and steady medians regress. No universal speedup or full-matrix acceptance. Evidence-specific cache payoff unproven; cache deferred. Independent review/agent behavior validation and formal Gate acceptance remain pending.

## Platform and recoverable publication (macOS-only)

The v0.3.2 candidate supports macOS-only operation on local filesystems that pass
native exchange/no-replace/no-follow/synchronization checks. Linux, Windows and
other OS publication backends return `PUBLICATION_UNSUPPORTED` before opening
publication directories or creating capability probes. Network, FUSE, remote and special filesystems are not
supported by implication; a libc symbol or successful probe is not certification
of every filesystem or power-loss behavior. No unsafe replacing-rename fallback.

Publication preserves displaced inodes/bytes, **not content CAS** or permanently
fresh canonical names. An unmanaged object may be **relocated** into retained
storage during conflict; an external writer can still modify its open inode.
Shared advisory locks constrain cooperating Harness operations, not editors.
The protected batch/finalizer protocol does not upgrade standalone atomic writes,
task-directory replacement or arbitrary external readers/writers.

- `.harness/.staging/`: prepared input, not recovery authority; stages are retained.
- `.harness/.transactions/`: active recovery descriptors; unresolved/unknown entries
  block admitted Gate/transitions before canonical facts, without implicit repair.
- `.harness/.publication-retained/`: displaced objects, capability probes, journal
  frames and terminal recovery data. Terminal retention alone is not pending work.
  Task new/recover keeps the actual previous Harness tree at
  `task-replacement-*/previous` beneath this directory, preserving original inodes
  and held-FD writes rather than cloning old retention into each prepared task.
  On turnover error, inspect the current task before retry: the old tree may remain
  in sibling `..harness.backup` or its retained slot. No automatic retry or deletion;
  this is object-lifetime preservation, not task-directory atomicity or power-loss certification.
- Storage contains actual metadata bytes, not evidence-cache or execution authority.
  New private directories request `0700`, new files `0600`; displaced objects keep
  their inode/mode. Existing storage is not retroactively hardened. Treat it as
  sensitive. Retention grows indefinitely and can cause `ENOSPC`; no pruning command
  or age-based cleanup exists. Cleanup needs separate design and explicit authority;
  deleting recovery data is not a supported repair.

## Why Harness

You tell the Agent what to change. Harness keeps the task, the proof, and the Gate result in `.harness/` so a new session can continue the same work. The Agent cannot mark the task done until `harness gate` prints `DECISION: CONVERGED`.

- A small, low-risk fix stays on Q1 / FAST: failing proof, fix, passing proof, Light Gate.
- A normal delivery stays on Q2 / STANDARD: contract, related tests, review, and a final plan check.
- A high-risk change stays on Q3 / STRICT: one plan item at a time. Risk can rise. It does not silently fall.

A question is answered directly and creates no task. A code change starts only after you ask for one, for example: "Use Engineering Harness to fix this bug: cancelling an order twice issues two refunds."

## Quick start

Install Superpowers, Pi skills, and the matching deterministic CLI with one explicit bootstrap command. With no version argument, installer resolves npm `latest` and requires the matching Git tag before changing installation:

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-pi.sh | bash
```

Pin a release when needed:

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-pi.sh | bash -s -- v0.3.1
```

Installer checks whether Superpowers is configured and installs it only when missing. It reconciles pinned Harness Pi skills, installs matching Python CLI into isolated user environment, and exposes `~/.local/bin/harness`. Add `~/.local/bin` to `PATH` if installer reports it missing. Re-running same version is idempotent. Review downloaded script before execution when required by local security policy.

For source development, install repository editable environment separately with `python -m pip install -e /path/to/superpowers-engineering-harness`.

Building the v0.3.2 candidate from source requires `setuptools>=77.0.3` for its SPDX license metadata (PEP 639). Default PEP 517 build isolation installs this build dependency; `--no-build-isolation` users must provide it. Python runtime requirement remains `>=3.11`; setuptools 68 is not a supported build backend.

Initialize a repository once. After that, daily work is a request to the Agent. The Engineering Harness skill reads persisted state and runs `harness` itself. You do not type those commands.

```bash
cd your-project
harness init
```

Open a session and say what to change, for example:

```text
Use Engineering Harness to fix this bug: cancelling an order twice issues two refunds.
```

To continue interrupted work, open a new session and ask the Agent to resume the current task. For Pi, open a new session after installing skills. Skills load at session start.

### Antigravity CLI (agy)

Install Harness CLI and AGY global skills once, from any directory, with latest stable release:

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-agy.sh | bash
```

Pin a release when needed:

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-agy.sh | bash -s -- v0.3.1
```

Installer updates Harness-owned skills under `~/.gemini/antigravity-cli/skills/` and preserves unrelated global skills. It does not initialize a project. In each Git project, run `harness init` once, then start AGY with `agy`; use `/engineering-harness` to invoke Harness explicitly in first session.

## Current workflow

Choose one route before the command blocks below.

```text
question or explanation → answer directly, no task
small change            → Q1 / FAST: RED → GREEN → Light Gate
normal delivery         → Q2 / STANDARD: contract, related tests, review, final Plan
high-risk change        → Q3 / STRICT: one plan item at a time
```

You describe the change. The Agent classifies the risk, does the work, and calls Harness at each phase. Most routine Harness commands need no interaction. The Agent may still ask for requirement clarification, design approval, an accepted Decision, an explicit skip or supersede, protected-action authorization, or an escalation decision.

The blocks below are the commands the Agent runs. `harness status` is read-only and does not mutate Harness state. When Gate emits `DECISION: CONTINUE` and persists blockers, the Agent runs `harness resume`, which chooses the recovery state from the blocker code and does not trust a persisted `recover_to`.

Q2 / STANDARD and Q3 / STRICT share the contract, review, and Gate path. The Agent records `review outcome PASS`, which performs `REVIEWING → GATING`:

```bash
harness status
harness transition IMPLEMENTING
harness evidence run --type unit_test --command "pytest tests/test_cancel.py"
harness transition VERIFYING
harness review complexity --file review.yaml
harness transition REVIEWING
harness review outcome PASS --reason-code REVIEW_CLEAN
harness gate
# inspect DECISION: CONVERGED, then:
harness transition DONE
```

Blocked recovery (`harness gate` emits `DECISION: CONTINUE`; Gate persists blockers and `harness resume` derives the target):

```bash
harness gate
# after DECISION: CONTINUE
harness resume
```

Before `VERIFYING`, record impact and related tests. Harness never executes a full suite, even when repository instructions request one. Evidence scope is always `related` and must cover every required test:

```bash
harness impact add-change src/orders/cancel.py
harness impact add-test tests/test_cancel.py::test_duplicate_cancel_single_refund
harness evidence run --type unit_test --scope related --covered-test tests/test_cancel.py::test_duplicate_cancel_single_refund --command "pytest tests/test_cancel.py::test_duplicate_cancel_single_refund"
```

Related test evidence is append-only (`unit-test-<hash>.json`). Gate unions fresh records' `covered_tests`, so adding one required test needs only that test's command. `VERIFYING → REVIEWING` runs freshness preflight first; stale required evidence blocks entry. STANDARD/STRICT task plans also reject declared test targets whose file path does not exist. Review reasons are controlled: use `REVIEW_CLEAN`, `TEST_COVERAGE_INSUFFICIENT`, `EVIDENCE_INCOMPLETE`, `INVARIANT_UNPROVEN`, `TEST_SCOPE_INSUFFICIENT`, `LOGIC_ERROR`, `REGRESSION`, `CONTRACT_VIOLATION`, or `INVARIANT_VIOLATION` for the matching outcome.

### Q1 / FAST

A question or explanation is Q0: the Agent answers directly and creates no Harness task. Q1 / FAST is narrow, low-risk work only. Classify explicitly; Q1 is rejected without persisting when current business paths already match `.harness/risk-boundaries.yaml` Q2/Q3. FAST returns before reading Plan, Markdown, or automatic-evidence sources. It still needs task-level failing RED and passing GREEN evidence, then Light Gate. It skips impact, complexity review, requirements, and invariants ceremony. `harness status` Build/Unit/Integration lines use the same live evidence projection as the Evidence list. If the work item is already implemented, `harness task verify-existing` can record a valid existing-verification record without forging RED; an ordinary bugfix still requires RED→GREEN. `requires_reproduction` keeps the task `CLASSIFIED`; create or resume a finding and reproduce normally.

```bash
harness task classify --level Q1 --scope low --contract none --data none \
  --authorization none --security none --concurrency none --deployment none
harness transition IMPLEMENTING
# collect a failing regression proof before the fix, then passing proof after the fix
harness evidence run --type unit_test --phase red --covered-test tests/test_x.py::test_x --command "pytest tests/test_x.py::test_x"
harness evidence run --type unit_test --phase green --covered-test tests/test_x.py::test_x --command "pytest tests/test_x.py::test_x"
harness transition VERIFYING
harness transition GATING
harness gate
```

FAST does not grant external actions. Authorizations are independent per task; grant only the requested action. A full-suite authorization does not exist:

```bash
harness authorize commit
harness authorize push
# also: create-mr, ready-mr, merge, deploy; revoke with revoke-<action>
```

### Q2 / STANDARD

For a standard change, the Agent keeps a final-only plan and reconciles it before Gate. Q2 uses final-only Plan execution v1. `harness plan status` reports whether final reconciliation passes. `--verbose` adds a body-free item and proof-health view. `harness gate preflight` keeps its existing `READY:` and blocker lines, then appends that Plan summary from the same assessment. There is no separate Gate preview command. Q2 does not use the Q3 journal commands.

```bash
harness plan status
harness plan status --verbose
harness plan sync-markdown docs/plan.md
harness check admission  # report all implementation-entry defects at once
harness gate preflight
```

### Q3 / STRICT

For strict work, the Agent advances one plan item at a time and asks you before a skip or supersede. Q3 uses replayable execution v2 and the same independent final proof checks. Journal commands write `.harness/plan-execution.yaml` under the existing lock. `harness plan begin` starts only the canonical next nonterminal item. `block` and `plan resume` change that item only; they do not call `harness resume` and do not change the top-level task state. `refresh-proof` replaces the current COMPLETE proof. `upgrade-execution` publishes an empty v2 journal only when every existing record is still `PENDING`.

```bash
# Upgrade a legacy all-PENDING v1 execution before beginning the first item.
harness plan upgrade-execution
harness plan begin P-001
harness plan block P-001 --reason "waiting on an accepted decision"
harness plan resume P-001

# Choose one reconciliation path: derive mechanical proof automatically,
harness plan reconcile P-001 --auto
# or submit explicit proof.
harness plan reconcile P-001 --complete \
  --evidence unit-test-<digest> --surface src/example.py

# Refresh proof later only when evidence or changed surfaces have changed.
harness plan refresh-proof P-001 \
  --evidence unit-test-<new-digest> --surface src/example.py
```

`SKIPPED` and `SUPERSEDED` are explicit `reconcile` dispositions. Q3 requires an accepted Decision for those two; `--auto` cannot create them, a reason, a Decision, or execution history. Default `harness plan status` output stays compatible when `--verbose` is omitted.

Risk may only escalate, never downgrade. Evidence reuse, soft budgets, local telemetry, and fixture benchmarks are available. Remote telemetry and external-agent benchmark claims are unavailable.

## Boundaries

> **Security boundary:** `harness evidence run --command` executes shell syntax (`shell=True`) as trusted text entered directly by the local Harness operator.

Never forward remote requests, configuration values, API payloads, CI metadata, or other untrusted input to this option. Internal `_collect` is unsupported internal API, not Python access control or provenance proof.

Markdown checkboxes are a one-way projection of canonical Plan execution. They are not Gate input, not proof, and not a source of truth. `harness plan sync-markdown` changes only the checkbox character in an explicit repository path. If a Plan changed before any execution history exists, `harness plan sync-fingerprint` refreshes its semantic digest; it refuses Plans with any item or transition history.

`--auto` may establish only a mechanical `COMPLETE`. It selects a bounded evidence cover and changed surfaces, then submits an ordinary COMPLETE request through the existing locked reconciliation path. It cannot choose `SKIPPED` or `SUPERSEDED`.

### Recovery guidance

Harness errors may include `Next:` with a suggested command. This is guidance only: Harness never runs the suggested command automatically. Inspect any state-changing command before running it. For an explanation of a stable diagnostic code, use:

```bash
harness explain PLAN_STALE
harness explain CONTRACT_CHANGED
```

Before `PLANNED → IMPLEMENTING`, use the read-only aggregate checker to report independent contract, test-plan, alignment, freeze, and Plan initialization defects in one run:

```bash
harness check admission
```

**Gate and Finding contract:** Only `harness gate` evaluates or persists product Gate results; direct `python scripts/quality_gate.py` is disabled. Persisted Findings require an explicit category (`adversarial`, `diagnosability`, `complexity`, or `interface`); category-less legacy records fail with `MIGRATION_REQUIRED`. `finding.schema.json` was removed; use category-specific schemas.

### Iron laws

1. Task state lives in `.harness/current-task.yaml`, never only in model context.
2. A fixed state machine controls transitions.
3. Gate PASS is required before `CONVERGED → DONE`.
4. Confirmed bugs require regression tests.
5. Evidence is fresh and bound to the current Git HEAD and workspace.
6. Bounded iteration ends in `ESCALATED`, not an infinite repair loop.
7. Markdown is not Gate truth. Canonical Plan YAML remains authoritative.
8. `--auto` records only mechanical `COMPLETE`. Semantic skip and supersede stay explicit operator dispositions.

## Version evolution

```text
v0.1    State + Evidence + Gate
  ↓
v0.2    Minimal Implementation + Complexity Review
  ↓
v0.2.3  Q0/Q1/Q2/Q3 risk-adaptive workflow
  ↓
v0.2.4  Test Plan → executable binding → fresh evidence
  ↓
v0.2.6  Production Diagnosability Contract + DIAG Finding + Gate
  ↓
v0.2.7  Task Ownership + Review Convergence + Gate Readiness
        + product freshness / canonical covered tests
  ↓
v0.2.8  Derived Context + Integrity + Host Usage + Multi-run Benchmark
  ↓
v0.2.9  Pre-implementation Alignment closure and freeze
        + contract / boundary drift diagnostics
  ↓
v0.2.10 Canonical Plan execution reconciliation
        + Q3 journal + Context/status + mechanical projections
  ↓
v0.3.0  Architecture Scope Gate P0
        + Architecture Context Projection P1
        + Architecture Evaluation P2
  ↓
v0.3.1  Task bootstrap + protected snapshots + immutable evidence fixes
```

`v0.3.1 current release` adds task-bootstrap, protected-snapshot, and immutable-evidence fixes; earlier risk-adaptive, Context, Alignment, and Plan Reconciliation safeguards remain available. v0.3.0 adds operator-authored Architecture models, deterministic ownership and Git attribution, Alignment seal v2, required-mode scope checks, bounded declared-plus-one-hop Context projection, and separate Drift Detection and Context Recovery experiments. Benchmark results remain `PENDING` until accepted external run artifacts provide at least three runs per fixture and arm. No measured benchmark improvement is claimed. See [v0.3.0 architecture design](docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md).

**Routing:** Q0 answers without task; Q1 / FAST uses RED/fix/GREEN/Light Gate; Q2 / STANDARD and Q3 / STRICT use full contract/review/Gate workflow.

## Engineering Quality

```text
                         Requirement
                             │
                             ▼
          Contract / Invariants / Test Plan
                             │
                             ▼
                    Implementation
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
     Correctness        Maintainability    Diagnosability
       Tests         Complexity Review   Logs / Trace Context
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
                  Evidence + Review + Findings
                             │
                             ▼
                 Deterministic Quality Gate
                             │
                             ▼
                            DONE
```

Harness controls state, proof, Finding lifecycle, and Gate. The agent judges business semantics and logging quality. Harness does not provide a logger SDK, OpenTelemetry, APM, automatic log insertion, or universal source scanning.

```text
Requirement
  ↓
Risk classification (CREATED → CLASSIFIED) → Task Contract (CLASSIFIED → PLANNED)
  ↓
Minimal Implementation Check — PREVENT
  ↓
Implementation / TDD (IMPLEMENTING)
  ↓
Verification + fresh evidence (VERIFYING)
  ↓
Complexity Reviewer — DETECT
  ↓
Adversarial review / finding reproduction (REVIEWING)
  ↓
Quality Gate (GATING)
  ↓
CONVERGED → DONE
```

## Rules still in force

AI coding workflows commonly fail when context is lost, completion is self-declared, tests or evidence are stale, review findings are never reproduced, repair loops do not converge, or correct code contains unnecessary complexity. Harness turns these into persisted, checkable controls:

```text
State + Contract + Invariant + Executable Test + Evidence + Deterministic Gate
```

| Layer | Responsibility |
|---|---|
| Model | Worker that reasons and changes code |
| Superpowers | Development workflow: design, planning, TDD, review |
| Engineering Harness | Controller: state, contracts, evidence, findings, gate |
| Tests / compiler / gate | Source of truth |

Harness is suitable for agentic feature and bug-fix delivery. It is not a replacement for CI, security scanning, or human architecture decisions.

### FAST repository verification

FAST always requires RED/GREEN plus fresh build evidence by default. Configure project-specific checks under `gate.fast.verification`; typecheck is opt-in:

```yaml
fast:
  verification:
    build: required
    typecheck: optional
```

Missing, failed, or stale required evidence blocks with `FAST_REPOSITORY_VERIFICATION_MISSING` and returns to verification. Authorization grants control Harness actions only; Harness cannot detect actions executed outside Harness.

### Decision records and Interface-first contracts

Consequential user choices persist outside chat history. Agent proposes facts, options, recommendation, reasons, trade-offs, and impact; user confirmation becomes an immutable Decision Record. Review active decisions at session startup:

```bash
harness decision propose --topic cache --question "Which cache?" --context "Redis exists" --option local="in-process" --option redis="shared" --recommend redis --reason "existing infrastructure"
harness decision accept DEC-001 --option redis
harness decision list
```

External/public API, SDK, plugin, event, CLI, and cross-module service boundaries need Interface Contract before implementation. Declare consumers, input/output/error semantics, compatibility, and verification. Known breaking change needs explicit approval; private helpers need no contract.

```bash
harness interface declare --name orders-api --kind http --consumer web-client --input "request schema" --output "response schema" --error "stable codes" --compatibility compatible --rationale "additive field"
harness impact add-interface INT-001 --kind http --consumer web-client --compatibility compatible --contract-id INT-001
```

Q1 external-interface impact fails with `PUBLIC_INTERFACE_RISK_ESCALATION_REQUIRED`; escalate explicitly. Gate blocks unresolved decisions, missing interface contract/compatibility/verification, and unapproved known breaking change.

### FAST risk boundaries

FAST never infers API/security risk from keywords. Declare changed-risk paths in `.harness/risk-boundaries.yaml`:

```yaml
boundaries:
  q2: [src/**/api/**, schemas/**]
  q3: [auth/**, permissions/**, migrations/**]
```

Business changes without policy block with `RISK_REVALIDATION_POLICY_MISSING`; boundary changes above Q1 block with `RISK_ESCALATION_REQUIRED`. Escalate explicitly:

```bash
harness task escalate --level Q2 --reason "public contract changed"
```

`docs/`, `tests/`, `test/`, and root Markdown-only changes do not require policy.

### Task identity reservation

`task new`, `task recover`, and `task migrate-id` reject an ID already reserved by the current task, history archive names/documents, or persistent decision records/index. Leading-zero aliases (`TASK-5` / `TASK-005`) count as the same numeric identity. Refusal is exit 2 with `TASK_ID_ALREADY_USED`, before replacement copying or identity writes under the existing publication lock. Choose an unused ID; never delete history or decisions to bypass the refusal.

When assigning a different identity, unreadable, malformed or symlinked reservation sources refuse with `TASK_ID_RESERVATION_INVALID`; diagnose the source rather than treating it as an empty set. Only the legacy `migrate-id` branch with every scope artifact absent may repair a malformed current ID string; the valid target must still be unused, and history/Decision/index validation is not skipped. A current `task.id: null` remains a valid unassigned identity, not a malformed string; its existing legacy assignment and genesis scope binding remain supported. Other non-string current IDs or missing task structure are still rejected. Reservation checks for `new`/`recover` and the existing scope-binding restrictions are unchanged. Existing historical duplicates are not rewritten and do not prevent a genuinely unused ID. Existing explicit publication recovery still runs before migration admission.

Exception: legacy migration to the exact current ID creates no new identity and does not re-scan reservation sources. It does not validate or repair damaged history/decisions, certify integrity, create scope, accept decisions or grant Gate approval; the task/telemetry may still be rewritten by the existing legacy save path. Use `harness explain TASK_ID_ALREADY_USED` or `harness explain TASK_ID_RESERVATION_INVALID` for read-only guidance; neither command changes state or runs recovery.

The guard reads only current identity, immediate history names/task documents and decision ownership, not probe/acceptance/retained trees. It is not a permanent all-time registry after every authoritative trace has been removed. A surviving decision still reserves its task ID when its archive has been pruned.

### Evidence reuse

Reuse is explicit and same-task only:

```bash
harness evidence run --type build --command "python -m pip wheel . --no-deps" --reuse-if-valid
```

`EVIDENCE_REUSED` means no command ran. Reuse needs prior success plus exact command/proof identity, unchanged HEAD and product workspace fingerprint, and exact runtime. Any mismatch runs command normally.

Collection uses short owned preflight and persistence phases; the external command runs **without** the root lock so nested Harness commands can complete. Persistence checks root/task identity, merges budget increments into the latest task, and publishes immutable receipts with task/telemetry as a bounded native bundle. Preflight budgets remain soft: overlapping runs are not hard-cap reservations.

If post-command admission or publication fails, collection returns `2` without rerunning or implicitly recovering. `EVIDENCE_RESULT_RETAINED: <path>` identifies a noncanonical, permission-restricted `result.json` under the system temporary directory (`harness-evidence-attempt-*`); this measured result is **not accepted/reusable proof**. A completed publication followed by output/lock teardown failure reports `EVIDENCE_PERSISTENCE_UNCERTAIN`: inspect canonical state before retrying. Cancellation remains `130`; ordinary command failure/timeout is recorded in `exit_code`, not collection success. Retention failure is explicitly reported. Retained attempts may contain command/output data, consume disk indefinitely, and have no automatic pruning; temporary-directory retention is not a power-loss or OS-cleanup survival guarantee.

### Actual test execution proof

Test receipts now need a fresh `test_execution` summary from the actual pytest child, not only a matching command string. File/function claims include all collected parameterizations: deselected, skipped or unexecuted members do not prove the whole target. Claim explicit executed nodes for a filtered run.

RED requires an actual assertion-style call failure (including pytest expectation failures) for each declared target, exit 1 and no collection/setup/teardown/internal errors. An unchecked checker exception such as `KeyError`, timeout, cancellation or collect-only run is not RED; express the intended product behavior as an assertion and diagnose infrastructure separately. Human review still decides whether the assertion represents the requested behavior.

The collector adds a private standalone pytest reporter, not the Harness source tree, to the child environment. Nested pytest sessions inside a test are not independent proof runs. The qualified command profile is one serial native pytest invocation preserving this reporter, with optional literal environment assignments (`env` allowed), `cd ... &&` prefixes and transparent `sh/bash/zsh -c/-lc` wrappers. Compound sequences, pipelines, OR/background commands, redirection, substitutions and arbitrary wrapper programs remain measurements only, even if the last pytest passes; hidden preceding failures must not become proof. Within this profile, parsing remote/Vitest selectors is not execution attestation. Unreported/unsupported runners, including unqualified worker/transport adapters, still produce measurements, but cannot prove test coverage, RED/GREEN or reuse. Legacy receipts remain unchanged historical data; missing actual execution blocks with `EVIDENCE_TEST_EXECUTION_INVALID`, never an automatic upgrade. Collector exit 0 means stored, not qualified. Local trusted execution is not an OS sandbox or executable identity attestation: executable/module/plugin/conftest code is trusted. A custom program named `pytest` or `python` can swallow internal prerequisite errors; basename classification cannot detect this. Use known test executables and collect prerequisites separately. Explicit worker/transport flags (`-n`, `--numprocesses`, `--dist`, `--tx`, `-d`) are measurement-only; effective worker configuration from ini/environment is also rejected by the reporter. These guards do not qualify xdist.

Wheel builds use a fresh source snapshot and validate payloads against that snapshot, leaving any old `build/` cache untouched.

### Product evidence freshness and covered-test paths

Test/build evidence is fresh against the **product workspace fingerprint** (product code, tests, dependencies, and non-control-plane config). A separate **control-plane fingerprint** covers `.harness/` task state, evidence files, review outcomes, and requirement/invariant verification metadata.

Writing control-plane records does not stale product proof. After collecting related tests, `harness requirement verify`, `harness invariant verify`, complexity/diagnosability review, and `harness review outcome` may update `.harness/` without forcing a product-test rerun. Editing product code, product tests, or in-scope non-control-plane config still marks evidence `EVIDENCE_WORKSPACE_STALE`. Tampered evidence payload, invalid bindings, and invalid control-plane schema still block Gate; those failures are not reported as product-test stale.

Covered tests store repository-root canonical paths. A command that `cd`s into a subproject still binds to the test-plan path:

```bash
harness evidence run --type unit_test --scope related \
  --covered-test backend/tests/foo.py \
  --command "sh -lc 'cd backend && pytest tests/foo.py'"

harness evidence run --type unit_test --scope related \
  --covered-test agents-frontend/src/__tests__/foo.spec.ts \
  --command "sh -lc 'cd agents-frontend && npx vitest run src/__tests__/foo.spec.ts'"

harness evidence run --type unit_test --scope related \
  --covered-test agents-frontend/src/__tests__/foo.spec.ts \
  --command "sh -lc 'cd agents-frontend && npm run test:unit -- --run src/__tests__/foo.spec.ts'"
```

The same test run from repo root or the subproject directory stores the same canonical covered-test path. Collection rejects a canonical path that does not exist, escapes the repository, uses an invalid relative `cd`, or was not selected by the command (`COVERED_TEST_NOT_EXECUTED`, `COVERED_TEST_PATH_INVALID`). When binding `--covered-test`, `npm run <script>` must statically resolve to pytest or `vitest run` or collection fails with `TEST_RUNNER_UNRESOLVED`. Build/lint `npm run` commands without covered tests are not treated as missing test runners. Older evidence that stored a cwd-relative selector still binds; the next collection migrates it to the canonical path.

### Adaptive operations

Evidence blockers recover through `harness resume`; review test gaps use `harness review outcome VERIFICATION_GAP --reason-code TEST_COVERAGE_INSUFFICIENT`. Do not use direct state shortcuts.

FAST evidence budgets are soft: test 2, build 1, repeated retry 1. Over budget requires all override fields:

```bash
harness evidence run --type build --command "python -m pip wheel ." --budget-override-reason "new evidence" --budget-override-evidence build.json --budget-override-hypothesis "packaging path"
```

For classified mutating tasks, generate a validated derived Context:

```bash
harness context                   # compact YAML, complete Control Core
harness context --full --json
harness context validate           # read-only; does not regenerate stale Context
harness context explain --json     # explain the saved selection
```

Latest successful snapshot lives in `.harness/context/{current,manifest,evidence}.yaml`, linked by `context_hash`. Integrity failures exit 2 without Context stdout. Publication uses a shared lock and exception rollback; this is not crash-atomic recovery from process termination. Context Evidence records what Harness generated, not what an Agent consumed, and is never product evidence for Gate. No task is created or advanced. Q0 remains outside this flow. Explicit expansion is available: `harness context expand --trigger INSUFFICIENT_CONTEXT --reason "Need dependency context"`. It records a task-bound event, increments `budget.context_expansions`, and advances LOCAL → BOUNDED → EXPANDED without changing risk or authorization. Run `harness context` again to refresh the now-stale snapshot. Generation automatically records out-of-scope open findings and ACCEPTED decisions, deduplicated by task, trigger, object ID, and relevant path/scope fingerprint. Control events persist before the derived snapshot is rebuilt. Failed evidence with `covered_tests` outside the Working Set also triggers expansion. Existing risk escalation history produces `RISK_ESCALATED` events without adding an extra policy step. Integrity failures remain fail-closed; no expansion bypasses validation.

Local-only telemetry: `harness telemetry show`. It measures `elapsed_seconds`, `harness_command_calls`, and evidence counts. Host usage can be reported with `harness telemetry report --usage-file <path>` (JSON or YAML; relative to the invocation directory):

```json
{"task_id":"TASK-101","usage":{"total_tokens":1234,"source":"runtime","tool_calls":12}}
```

Report a cumulative snapshot for the current task, not a delta. Repeated snapshots are idempotent; omitted fields become null. `save_task` preserves reported usage; new tasks do not inherit it. Counts must be nonnegative integers or null. Any token count requires `source: runtime|provider|estimated`; when all token counts are supplied, input + output must equal total. Missing task, mismatched task ID, or invalid usage exits 2. Usage is local host input, not independently authenticated provider evidence; Harness does not count unseen agent actions or call a tokenizer. Unreported usage stays null; legacy `token_estimate: null` remains unchanged. Reporting does not itself prove efficiency improvements. Run fixture validation: `harness benchmark run --fixtures benchmarks/fixtures`.

Compare recorded baseline/adaptive artifacts:

```bash
harness benchmark compare --fixtures benchmarks/fixtures --baseline baseline-artifacts --adaptive adaptive-artifacts

# v0.2.9 Alignment metrics from explicit persisted records
harness benchmark alignment --records alignment-records.yaml
```

Stdout lists historical `overall:` separately from v0.2.9 `experiment:`. Missing usage or incomplete runs make experiment `INCONCLUSIVE`; that is not an efficiency pass even when overall is `CORRECTNESS_PRESERVED`. Comparison requires every fixture-required correctness field to be true in both artifacts. Missing proof is `INCONCLUSIVE`, not correctness preserved. Harness does not run or attest external agent runs, tokens, or tool calls.

### Automatic orchestration

When Engineering Harness Skill controls a task, it automatically invokes Minimal Implementation Check in `PLANNED`, records impact analysis before `VERIFYING`, and invokes Complexity Reviewer after green verification but before `REVIEWING`. State guards reject skipped records. Full-suite execution remains forbidden; run only explicitly listed impact-related tests.

## v0.2: necessary complexity

Before implementation, Minimal Implementation Check records Decision Ladder result. Search in order: existence, repository reuse, stdlib, platform-native capability, installed dependency, local implementation, then minimum new abstraction.

```bash
harness check minimal --file minimal-implementation.yaml
```

After verification, Complexity Reviewer inspects changed diff and may create evidence-backed `CPLX-*` findings only for DELETE, REUSE, STDLIB, NATIVE, YAGNI, or SHRINK.

```bash
harness review complexity --file complexity-review.yaml
# Optional override: harness review complexity --base origin/main --file complexity-review.yaml
```

Open HIGH complexity findings block gate. MEDIUM and LOW findings are advisory. Necessary security, authorization, audit, compatibility, migration, accessibility, and NFR complexity is not automatically over-engineering. Complexity review defaults to task Git baseline, covering committed, staged, unstaged, and relevant untracked changes; `--base` is an explicit override.

## Production diagnosability (v0.2.6)

Q0 skips diagnosability. Q1 may perform an agent advisory business-ID, exception-context, and sensitive-data check; it is routing-only, not persisted Core/Gate proof. Q2 requires `.harness/observability.yaml` and `harness review diagnosability` only when the Contract is required. Q3 always requires valid applicability and fresh review evidence. Harness validates artifacts and Gate state; it does not provide a logging SDK, OpenTelemetry, automatic log insertion, or universal source scanning.

## Dependencies and token use

Harness depends on Superpowers worker skills, especially brainstorming, writing-plans, TDD, review, and verification. Harness controls their delivery loop; it does not duplicate them.

Caveman Mode is recommended to reduce agent output tokens. Keep code, commands, errors, evidence, and state technically complete.

## Docs and development

- [Architecture: big picture](docs/architecture.md)
- [Evidence freshness and test path binding](docs/2026-09-07-evidence-freshness-and-test-path-binding-issues.md)
- [v0.2.2 flow hardening design](docs/superpowers/specs/2026-08-26-v022-flow-hardening-design.md)
- [v0.2 design](docs/superpowers/specs/2026-08-25-v02-minimal-complexity-design.md)
- [Worked lifecycle example](docs/worked-example.md)
- [Historical v0.1 implementation guide](docs/engineering-harness-v0.1.md)

Run only impact-related tests, listed explicitly. For this package metadata area:

```bash
python -m pytest tests/test_version_consistency.py tests/test_readme_docs.py -q
```

## License

Apache-2.0 © 2026 Yezhiwei

# Superpowers Engineering Harness v0.2.4

[简体中文](README.zh-CN.md)

`v0.2.4 current release`; risk-adaptive behavior and Test Plan Gate are included in this release.

**Routing:** Q0 answers without task; Q1 / FAST uses RED/fix/GREEN/Light Gate; Q2 / STANDARD and Q3 / STRICT use full contract/review/Gate workflow.

Engineering Harness is deterministic control plane around [Superpowers](https://github.com/obra/superpowers) development workflows. It does not replace agent or worker skills. It persists task state, requires proof, and prevents an agent from declaring work done without gate approval.

## Why

AI coding workflows commonly fail when context is lost, completion is self-declared, tests/evidence are stale, review findings are never reproduced, repair loops do not converge, or correct code contains unnecessary complexity.

Harness turns these into persisted, checkable controls:

```text
State + Contract + Invariant + Executable Test + Evidence + Deterministic Gate
```

## Design model

| Layer | Responsibility |
|---|---|
| Model | Worker that reasons and changes code |
| Superpowers | Development workflow: design, planning, TDD, review |
| Engineering Harness | Controller: state, contracts, evidence, findings, gate |
| Tests / compiler / gate | Source of truth |

Harness is suitable for agentic feature and bug-fix delivery. It is not a replacement for CI, security scanning, or human architecture decisions.

## Workflow

```text
Requirement
  ↓
Task Contract (CREATED → PLANNED)
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

Iron laws:

1. Task state lives in `.harness/current-task.yaml`, never only model context.
2. Fixed state machine controls transitions.
3. Gate PASS is required before `CONVERGED → DONE`.
4. Confirmed bugs require regression tests.
5. Evidence is fresh and bound to current Git HEAD/workspace.
6. Bounded iteration ends in `ESCALATED`, not infinite repair.

## Quick start

Install worker workflows, Harness skills, and deterministic CLI:

```bash
pi install git:github.com/obra/superpowers
pi install git:github.com/yezhwi/superpowers-engineering-harness
pip install -e /path/to/superpowers-engineering-harness
```

Initialize target repository, then start each session from persisted state:

```bash
cd your-project
harness init
harness status
```

Ask agent to work through Harness, for example:

```text
Use Engineering Harness to fix this bug: cancelling an order twice issues two refunds.
```

For Pi, open new session after installing skills. Skills load at session start.

## Daily operations

Normal success path (`review outcome PASS` performs `REVIEWING → GATING`):

```bash
harness status
harness transition IMPLEMENTING
harness evidence --type unit_test --command "pytest tests/test_cancel.py"
harness transition VERIFYING
harness review complexity --file review.yaml
harness transition REVIEWING
harness review outcome PASS --reason-code REVIEW_CLEAN
harness gate
harness transition DONE
```

Blocked recovery path (`harness gate` performs `GATING → BLOCKED`; `harness resume` derives target from blocker code):

```bash
harness gate
harness resume
```

Before `VERIFYING`, record impact and related tests. Full suite needs explicit authorization:

```bash
harness impact add-change src/orders/cancel.py
harness impact add-test tests/test_cancel.py::test_duplicate_cancel_single_refund
harness authorize full-suite
harness evidence --type unit_test --scope full_suite --command "pytest"
```

Recover interrupted work with `harness status`; Harness resumes from `.harness/current-task.yaml`. Gate recovery derives target from blocker code, not persisted `recover_to`. Review reasons are controlled: use `REVIEW_CLEAN`, `TEST_COVERAGE_INSUFFICIENT`, `EVIDENCE_INCOMPLETE`, `INVARIANT_UNPROVEN`, `TEST_SCOPE_INSUFFICIENT`, `LOGIC_ERROR`, `REGRESSION`, `CONTRACT_VIOLATION`, or `INVARIANT_VIOLATION` for matching outcome.

### Risk-adaptive workflow (v0.2.3)

- **Q0:** direct answer; no Harness task.
- **Q1 / FAST:** narrow, low-risk work only. Classify explicitly; FAST still needs task-level failing RED and passing GREEN evidence, then Light Gate. It skips impact, complexity review, requirements, and invariants ceremony.
- **Q2 / STANDARD** and **Q3 / STRICT:** use current full Harness workflow. Risk may only escalate, never downgrade.

```bash
harness task classify --level Q1 --scope low --contract none --data none \
  --authorization none --security none --concurrency none --deployment none
harness transition IMPLEMENTING
# collect a failing regression proof before fix, then passing proof after fix
harness evidence --type unit_test --phase red --covered-test tests/test_x.py::test_x --command "pytest tests/test_x.py::test_x"
harness evidence --type unit_test --phase green --covered-test tests/test_x.py::test_x --command "pytest tests/test_x.py::test_x"
harness transition VERIFYING
harness transition GATING
harness gate
```

FAST does not grant external actions. Authorizations are independent per task; grant only requested action:

```bash
harness authorize commit
harness authorize full-suite
harness authorize push
# also: create-mr, ready-mr, merge, deploy; revoke with revoke-<action>
```

Evidence reuse, soft budgets, local telemetry, and fixture benchmarks are available. Remote telemetry and external-agent benchmark claims are unavailable.

### FAST repository verification

FAST always requires RED/GREEN plus fresh build evidence by default. Configure project-specific checks under `gate.fast.verification`; typecheck is opt-in:

```yaml
fast:
  verification:
    build: required
    typecheck: optional
```

Missing, failed, or stale required evidence blocks with `FAST_REPOSITORY_VERIFICATION_MISSING` and returns to verification. Authorization grants control Harness actions only; Harness cannot detect actions executed outside Harness.

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

### Evidence reuse

Reuse is explicit and same-task only:

```bash
harness evidence --type build --command "python -m pip wheel . --no-deps" --reuse-if-valid
```

`EVIDENCE_REUSED` means no command ran. Reuse needs prior success plus exact command/proof identity, unchanged HEAD/workspace, and exact runtime. Any mismatch runs command normally.

### Adaptive operations

Evidence blockers recover through `harness resume`; review test gaps use `harness review outcome VERIFICATION_GAP --reason-code TEST_COVERAGE_INSUFFICIENT`. Do not use direct state shortcuts.

FAST evidence budgets are soft: test 2, build 1, repeated retry 1. Over budget requires all override fields:

```bash
harness evidence --type build --command "python -m pip wheel ." --budget-override-reason "new evidence" --budget-override-evidence build.json --budget-override-hypothesis "packaging path"
```

Local-only telemetry: `harness telemetry show`. It measures `elapsed_seconds`, `harness_command_calls`, and evidence counts. Agent metrics remain unavailable: `token_estimate: null`, tool calls/search rounds null. Run fixture validation: `harness benchmark run --fixtures benchmarks/fixtures`.

Compare recorded baseline/adaptive artifacts:

```bash
harness benchmark compare --fixtures benchmarks/fixtures --baseline baseline-artifacts --adaptive adaptive-artifacts
```

Comparison requires every fixture-required correctness field to be true in both artifacts. Missing proof is `INCONCLUSIVE`, not correctness preserved. Harness does not run or attest external agent runs, tokens, or tool calls.

### Automatic orchestration

When Engineering Harness Skill controls a task, it automatically invokes Minimal Implementation Check in `PLANNED`, records impact analysis before `VERIFYING`, and invokes Complexity Reviewer after green verification but before `REVIEWING`. State guards reject skipped records. Full-suite authorization remains an explicit human decision.

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

## Production diagnosability (v0.2.5)

Q0 skips diagnosability. Q1 performs a lightweight business-ID, exception-context, and sensitive-data check. Q2 requires `.harness/observability.yaml` and `harness review diagnosability` only when the Contract is required. Q3 always requires valid applicability and fresh review evidence. Harness validates artifacts and Gate state; it does not provide a logging SDK, OpenTelemetry, automatic log insertion, or universal source scanning.

## Dependencies and token use

Harness depends on Superpowers worker skills, especially brainstorming, writing-plans, TDD, review, and verification. Harness controls their delivery loop; it does not duplicate them.

Caveman Mode is recommended to reduce agent output tokens. Keep code, commands, errors, evidence, and state technically complete.

## Docs and development

- [v0.2.2 flow hardening design](docs/superpowers/specs/2026-08-26-v022-flow-hardening-design.md)
- [v0.2 design](docs/superpowers/specs/2026-08-25-v02-minimal-complexity-design.md)
- [Worked lifecycle example](docs/worked-example.md)
- [Historical v0.1 implementation guide](docs/engineering-harness-v0.1.md)

```bash
python -m pytest tests/ -q
```

## License

Apache-2.0 © 2026 Yezhiwei

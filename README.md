# Superpowers Engineering Harness v0.2.1

[简体中文](README.zh-CN.md)

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

```bash
harness status
harness transition IMPLEMENTING
harness evidence --type unit_test --command "pytest tests/test_cancel.py"
harness transition VERIFYING
harness gate
harness converge
```

Before `VERIFYING`, record impact and related tests. Full suite needs explicit authorization:

```bash
harness impact add-change src/orders/cancel.py
harness impact add-test tests/test_cancel.py::test_duplicate_cancel_single_refund
harness authorize full-suite
harness evidence --type unit_test --scope full_suite --command "pytest"
```

Recover interrupted work with `harness status`; Harness resumes from `.harness/current-task.yaml`.

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
```

Open HIGH complexity findings block gate. MEDIUM and LOW findings are advisory. Necessary security, authorization, audit, compatibility, migration, accessibility, and NFR complexity is not automatically over-engineering.

## Dependencies and token use

Harness depends on Superpowers worker skills, especially brainstorming, writing-plans, TDD, review, and verification. Harness controls their delivery loop; it does not duplicate them.

Caveman Mode is recommended to reduce agent output tokens. Keep code, commands, errors, evidence, and state technically complete.

## Docs and development

- [v0.2 design](docs/superpowers/specs/2026-08-25-v02-minimal-complexity-design.md)
- [Worked lifecycle example](docs/worked-example.md)
- [Historical v0.1 implementation guide](docs/engineering-harness-v0.1.md)

```bash
python -m pytest tests/ -q
```

## License

Apache-2.0 © 2026 Yezhiwei

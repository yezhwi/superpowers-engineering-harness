# Superpowers Engineering Harness v0.1

> Turn agent development into deterministic state, evidence, and
> gate-controlled delivery for humans and AI.

Deterministic controller that wraps Superpowers development workflows.
Correctness judgment migrates from the model to:

```text
State + Contract + Invariant + Executable Test + Evidence + Deterministic Gate
```

Model = Worker · Superpowers = Development Workflow · Harness = Controller ·
Tests / Compiler / Gate = Truth.

## Iron Laws (v0.1)

1. State persisted outside LLM context (`​.harness/current-task.yaml`).
2. Transitions only via the fixed state machine.
3. DONE only through `CONVERGED -> DONE`, and CONVERGED only after
   `quality_gate.py` exit 0.
4. CONFIRMED bugs require regression tests.
5. Evidence is fresh, bound to git HEAD, produced by real commands.
6. Convergence loop bounded by `max_iterations`, then ESCALATED.

## Layout

```text
SKILL.md                  main orchestration skill (start here)
skills/
  task-contract/          requirement -> contract (CREATED -> PLANNED)
  adversarial-review/     attack the diff, emit PROPOSED findings
  reproduce-finding/      PROPOSED -> REPRODUCING -> CONFIRMED/REJECTED
  collect-evidence/       decide required evidence types
  quality-gate/           run gate, map exit codes to transitions
  convergence/            PASS / Continue / Escalate decision
schemas/                  JSON schemas for all harness files
scripts/
  state_machine.py        states + transition table (single source of truth)
  validate_state.py       CLI transition check
  collect_evidence.py     run command, bind HEAD, save evidence
  harness_status.py       unified status view
  quality_gate.py         deterministic gate (exit 0/1/2)
templates/                starting points for .harness/ files
tests/                    harness self-tests (pytest)
docs/engineering-harness-v0.1.md   implementation spec
```

Business projects adopt a `.harness/` directory at their root:

```text
.harness/
├── config.yaml          max_iterations etc.
├── current-task.yaml    persisted task state
├── requirements.yaml    REQ-nnn contract
├── invariants.yaml      INV-nnn invariants
├── gate.yaml            gate policy
├── findings/*.yaml      FND-nnn lifecycle records
├── evidence/*.json      fresh, HEAD-bound evidence
└── history/TASK-xxxx/
```

## Usage

One-time setup in the business project:

```bash
pip install -e <path-to-this-repo>   # provides the `harness` command
harness init                         # scaffold .harness/
```

New session, always first (works in any project):

```bash
harness status
```

Then follow `SKILL.md`'s dispatch table:

```text
CREATED -> task-contract
PLANNED -> Superpowers execution (TDD)
VERIFYING -> deterministic verification + collect_evidence.py
REVIEWING -> review + adversarial-review
REPRODUCING -> reproduce-finding
GATING -> harness gate
PASS -> CONVERGED -> DONE
```

## Development

```bash
python -m pytest tests/ -q
```

Spec: `docs/engineering-harness-v0.1.md`. Definition of Done for v0.1 is in
section 34 — including one real dogfooded project.

## Using with Pi

This repo is a [pi package](https://pi.dev/packages) (`package.json`
declares `pi.skills`). Skills are auto-discovered by description matching —
no slash-commands to memorize.

### 1. Install (once)

```bash
# skills for the agent
pi install git:github.com/yezhwi/superpowers-engineering-harness

# deterministic CLI for the shell (editable, so scripts/ stays resolvable)
pip install -e /path/to/superpowers-engineering-harness
```

Installed skills:

| Skill | Trigger example |
|---|---|
| engineering-harness (orchestrator) | "用 Engineering Harness 修这个 bug：…" |
| task-contract | "把这个需求变成合同" |
| adversarial-review | "审查这次改动能不能被打破" |
| reproduce-finding | "先复现这个 bug 再修" |
| collect-evidence / quality-gate / convergence | 进入对应阶段自动触发 |

### 2. Prepare a target project (once per project)

```bash
cd your-project
harness init          # scaffolds .harness/, idempotent
```

### 3. Run a task in a pi session

Just talk to the agent:

```text
在当前项目里，用 Engineering Harness 修复这个 bug：<描述>
```

The orchestrator skill takes over: reads `.harness/current-task.yaml`,
dispatches the right sub-skill per state, runs deterministic commands,
and only declares DONE after `harness gate` exits 0 followed by
`CONVERGED -> DONE`. Session interrupted? Next session starts with
`harness status` and resumes from disk.

Manual control at any time:

```bash
harness status                      # where am I?
harness transition VERIFYING        # push phase manually
harness gate                        # run the gate yourself
```

## License

Apache-2.0 © 2026 Yezhiwei — see [LICENSE](LICENSE).

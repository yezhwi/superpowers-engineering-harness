# Superpowers Engineering Harness v0.1

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

New session, always first:

```bash
python scripts/harness_status.py
```

Then follow `SKILL.md`'s dispatch table:

```text
CREATED -> task-contract
PLANNED -> Superpowers execution (TDD)
VERIFYING -> deterministic verification + collect_evidence.py
REVIEWING -> review + adversarial-review
REPRODUCING -> reproduce-finding
GATING -> python scripts/quality_gate.py
PASS -> CONVERGED -> DONE
```

## Development

```bash
python -m pytest tests/ -q
```

Spec: `docs/engineering-harness-v0.1.md`. Definition of Done for v0.1 is in
section 34 — including one real dogfooded project.

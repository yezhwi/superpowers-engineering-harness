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

Two SEPARATE installs with different jobs — you need BOTH:

```bash
# 1a) skills for the agent (this is what makes the trigger phrases work)
pi install git:github.com/yezhwi/superpowers-engineering-harness

# 1b) deterministic CLI for the shell (editable, so scripts/ stays resolvable)
pip install -e /path/to/superpowers-engineering-harness
```

| 安装 | 提供什么 | 没装的后果 |
|---|---|---|
| `pi install` | SKILL.md 技能包 → Agent 会话内自动触发 | 说触发语无反应，Agent 不知道 harness 存在 |
| `pip install -e .` | 终端里的 `harness` 命令 | Agent 会话内技能能触发，但确定性命令全部失败 |

Verify:

```bash
pi list | grep harness     # must show the package
harness status             # in a project: renders state or INVALID error, not "command not found"
```

NOTE: skills load at session start. After installing, OPEN A NEW PI SESSION —
an already-running session will not see them.

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

### 4. Trigger phrases（说什么会触发什么）

Skills match by description — phrase your request around the intent, not
the tool:

| 你说 | Agent 做什么 |
|---|---|
| "用 Engineering Harness 实现这个需求：…" | 完整循环：合同 → TDD → gate → DONE |
| "修一下这个 bug：…" / "复现这个问题" | finding → 复现 → 修复 → 回归 |
| "这个任务现在到哪一步了？继续推进" | 读 `.harness/` 状态，从断点续跑 |
| "审查这次改动有没有漏洞" | adversarial-review，产出 PROPOSED findings |
| "这个 finding 是真的吗？先别修" | 只做 reproduce，CONFIRMED 或 REJECTED |
| "跑一下门禁" / "能收工了吗？" | `harness gate` + converge 决策 |

### 5. Worked example: fixing a real bug end-to-end

Setup (shell):

```bash
cd ~/code/orders-service          # any git repo
pip install -e ~/code/superpowers-engineering-harness   # if not installed yet
harness init
```

Then in a pi session, you type:

> 用 Engineering Harness 修复这个 bug：订单取消后重试取消请求，退款被执行两次。

What the agent does (you watch; no need to drive each step):

```text
[harness] .harness/current-task.yaml 不存在 -> 从 CREATED 开始
[harness] state: CREATED -> SPECIFYING (task-contract)
          REQ-001: 重复取消请求只执行一次退款 (must)
          INV-001: refund 对同一 order_id 幂等 (critical)
[harness] state: PLANNED -> IMPLEMENTING (TDD)
          先写失败测试 test_duplicate_cancel_single_refund ... RED
          实现 per-order_id 退款锁 ... GREEN
[harness] state: VERIFYING
          harness evidence --type unit_test --command pytest   # 绑定 HEAD
[harness] state: REVIEWING (adversarial-review)
          FND-001 PROPOSED: 并发取消仍可能双花 (target INV-001)
[harness] state: REPRODUCING (reproduce-finding)
          并发测试写好并运行 RED -> FND-001 CONFIRMED
          FIXING: 加互斥 -> FIXED (GREEN) -> VERIFIED (全量回归) -> CLOSED
[harness] state: GATING
$ harness gate
QUALITY GATE: PASS
[harness] CONVERGED -> DONE
```

You verify from another terminal whenever you like:

```bash
harness status                    # State DONE, Gate PASS
harness finding list              # FND-001 CLOSED
ls .harness/evidence/             # HEAD-bound evidence json files
```

### 6. What you should (and should not) do as the human

DO:
- Interrupt and ask questions anytime — state is on disk, nothing is lost
- Treat `ESCALATED` as your queue: reason codes
  (`SPEC_AMBIGUITY`, `ARCHITECTURE_DEFECT`, …) mean human decision required
- Re-run a rejected plan by editing requirements and starting a new iteration

DON'T:
- Hand-edit `status:` fields in `.harness/current-task.yaml` to skip phases —
  transitions must go through `harness transition` (validated) or the agent
- Mark requirements/invariants `verified` yourself — the gate now demands
  evidence files bound to git HEAD; empty-evidence claims are blockers
- Argue with exit code 1. Fix what stdout says is blocking.

### 7. Session recovery（中断恢复）

All state lives in `.harness/`. If the pi session dies mid-task:

```text
新会话第一句: "继续上一个 harness 任务"
# or explicitly:
harness status     # e.g. State REVIEWING, Iteration 2/5
> 继续             # agent reads status and resumes from REVIEWING
```

## License

Apache-2.0 © 2026 Yezhiwei — see [LICENSE](LICENSE).

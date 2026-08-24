# Superpowers → Engineering Harness v0.1 实施手册

> 版本：v0.1  
> 目标：在 Superpowers 之上增加一层 Project Engineering Harness，使 Coding Agent 的“完成”由状态、证据、质量门禁和收敛条件决定，而不是由模型自行宣布。  
> 适用对象：Codex / Grok / Claude Code 等本地 Coding Agent。  
> 实施原则：**State → Evidence → Gate → Convergence**

---

## 1. 项目目标

本项目不是重新实现 Coding Agent，也不是替代 Superpowers。

目标是在 Superpowers 现有开发工作流之上增加一层项目级控制平面：

```text
Requirement
    ↓
Task Contract
    ↓
Superpowers Brainstorm / Plan / TDD / Development
    ↓
Deterministic Verification
    ↓
Adversarial Review
    ↓
Finding
    ↓
Reproduce
    ↓
Regression Test
    ↓
Fix
    ↓
Fresh Evidence
    ↓
Quality Gate
    ↓
PASS → CONVERGED → DONE
BLOCKED → 继续修复
```

核心区别：

```text
Superpowers:
How to build software well.

Engineering Harness:
How to prove the task is acceptable.
```

---

## 2. v0.1 非目标

v0.1 暂时不要实现：

- Web 控制台
- 数据库
- 独立 Agent Runtime
- 模型 Router
- 多模型自动调度
- 企业规则中心
- PR Dashboard
- 多项目管理
- 复杂评分算法
- LLM 自动质量评分
- 自研 Coding Agent

v0.1 只使用：

```text
Markdown
YAML
JSON
Python
Git
Skills
Existing Superpowers
```

---

## 3. v0.1 六条 Iron Laws

### LAW 1

**NO DONE WITHOUT QUALITY GATE PASS.**

没有 Quality Gate PASS，不允许进入 DONE。

### LAW 2

**NO QUALITY GATE PASS WITHOUT FRESH EVIDENCE.**

所有 Evidence 必须基于当前 Git HEAD。

### LAW 3

**NO FINDING IS A BUG UNTIL REPRODUCED.**

Reviewer 的发现只能是 PROPOSED Finding，必须经过 Reproduce 才能成为 CONFIRMED。

### LAW 4

**NO CONFIRMED BUG IS CLOSED WITHOUT A REGRESSION TEST.**

确认的 Bug 必须增加 Regression Test。

### LAW 5

**NO TASK STATE EXISTS ONLY IN MODEL CONTEXT.**

所有任务状态必须持久化在 `.harness/` 中。

### LAW 6

**NO INFINITE FIX LOOP.**

达到最大迭代次数或长期不收敛时，必须进入 ESCALATED / CONVERGENCE_FAILED。

---

# 4. 总体架构

```text
                    User Requirement
                           │
                           ▼
                   Task Contract Skill
                           │
                           ▼
                Superpowers Brainstorming
                           │
                           ▼
                     Design / Spec
                           │
                           ▼
                 Invariants / Risks
                           │
                           ▼
                 Superpowers Planning
                           │
                           ▼
           Superpowers Implementation / TDD
                           │
                           ▼
              Deterministic Verification
                           │
                           ▼
                  Adversarial Review
                           │
                           ▼
                       Finding
                           │
                           ▼
                       Reproduce
                      /         \
                 REJECTED     CONFIRMED
                                  │
                                  ▼
                         Regression Test
                                  │
                                  ▼
                                 Fix
                                  │
                                  └───────┐
                                          │
                                          ▼
                                  Verification
                                          │
                                          ▼
                                     Evidence
                                          │
                                          ▼
                                    Quality Gate
                                    /          \
                               BLOCKED         PASS
                                  │              │
                                  └──── loop     ▼
                                             CONVERGED
                                                 │
                                                 ▼
                                                DONE
```

---

# 5. Repository 结构

建议创建独立项目：

```text
superpowers-engineering-harness/
├── SKILL.md
│
├── skills/
│   ├── task-contract/
│   │   └── SKILL.md
│   │
│   ├── adversarial-review/
│   │   └── SKILL.md
│   │
│   ├── reproduce-finding/
│   │   └── SKILL.md
│   │
│   ├── collect-evidence/
│   │   └── SKILL.md
│   │
│   ├── quality-gate/
│   │   └── SKILL.md
│   │
│   └── convergence/
│       └── SKILL.md
│
├── schemas/
│   ├── task.schema.json
│   ├── requirement.schema.json
│   ├── invariant.schema.json
│   ├── finding.schema.json
│   └── evidence.schema.json
│
├── scripts/
│   ├── harness_status.py
│   ├── collect_evidence.py
│   ├── quality_gate.py
│   └── validate_state.py
│
├── templates/
│   ├── current-task.yaml
│   ├── requirements.yaml
│   ├── invariants.yaml
│   └── gate.yaml
│
├── tests/
│   ├── test_state_machine.py
│   ├── test_quality_gate.py
│   ├── test_evidence.py
│   └── fixtures/
│
└── README.md
```

接入业务项目后，在项目根目录增加：

```text
.harness/
├── config.yaml
├── current-task.yaml
├── requirements.yaml
├── invariants.yaml
├── gate.yaml
│
├── findings/
│   ├── F-0001.yaml
│   └── ...
│
├── evidence/
│   ├── build.json
│   ├── unit-test.json
│   ├── integration-test.json
│   └── review.json
│
└── history/
    └── TASK-xxxx/
```

---

# 6. 状态机

## 6.1 状态定义

v0.1 仅允许以下状态：

```text
CREATED
SPECIFYING
PLANNED
IMPLEMENTING
VERIFYING
REVIEWING
REPRODUCING
FIXING
GATING
BLOCKED
CONVERGED
DONE
ESCALATED
```

## 6.2 合法转换

```text
CREATED → SPECIFYING

SPECIFYING → PLANNED

PLANNED → IMPLEMENTING

IMPLEMENTING → VERIFYING

VERIFYING → IMPLEMENTING
VERIFYING → REVIEWING

REVIEWING → REPRODUCING
REVIEWING → GATING

REPRODUCING → REVIEWING
REPRODUCING → FIXING

FIXING → VERIFYING

GATING → BLOCKED
GATING → CONVERGED

BLOCKED → IMPLEMENTING
BLOCKED → REPRODUCING
BLOCKED → ESCALATED

CONVERGED → DONE
```

## 6.3 禁止转换

至少显式禁止：

```text
IMPLEMENTING → DONE
VERIFYING → DONE
REVIEWING → DONE
FIXING → DONE
BLOCKED → DONE
```

唯一允许进入 DONE 的路径：

```text
CONVERGED → DONE
```

---

# 7. current-task.yaml

建议模板：

```yaml
task:
  id: TASK-001
  title: ""
  description: ""

state: CREATED

iteration: 0
max_iterations: 5

spec:
  design: null
  plan: null

requirements:
  total: 0
  verified: 0
  uncovered: []

invariants:
  total: 0
  verified: 0
  violated: []

verification:
  build: unknown
  unit_test: unknown
  integration_test: unknown

findings:
  critical: 0
  major: 0
  minor: 0
  confirmed: 0
  proposed: 0

gate:
  status: unknown
  blocked_by: []

git:
  head: null

timestamps:
  created_at: null
  updated_at: null
```

要求：

1. 所有状态切换必须更新该文件。
2. 每次执行 Gate 前刷新 `git.head`。
3. Task 不允许只存在于 Agent Conversation Context 中。
4. Session 重启后必须先读取 `current-task.yaml`。

---

# 8. requirements.yaml

```yaml
requirements:
  - id: REQ-001
    statement: ""
    source: user
    priority: must
    status: pending
    evidence: []

  - id: REQ-002
    statement: ""
    source: spec
    priority: should
    status: pending
    evidence: []
```

status：

```text
pending
implemented
verified
blocked
```

Quality Gate 默认要求：

```text
priority=must 的 Requirement 必须全部 verified
```

---

# 9. invariants.yaml

```yaml
invariants:
  - id: INV-001
    statement: ""
    category: correctness
    severity: major
    status: pending
    verification: []

  - id: INV-002
    statement: ""
    category: concurrency
    severity: critical
    status: pending
    verification: []
```

推荐 category：

```text
correctness
transaction
concurrency
idempotency
security
authorization
state_machine
recovery
data_consistency
architecture
```

status：

```text
pending
verified
violated
```

---

# 10. Finding Schema

每个 Reviewer Finding 单独保存：

```text
.harness/findings/F-xxxx.yaml
```

格式：

```yaml
id: F-0001

type: suspected_defect

severity: major

category: concurrency

status: PROPOSED

title: ""

claim: ""

related_requirements: []

related_invariants:
  - INV-001

location:
  file: null
  line: null

failure_scenario:
  - ""

expected_behavior: ""

possible_actual_behavior: ""

recommended_reproducer:
  type: unit_test
  description: ""

reproduction:
  command: null
  exit_code: null
  evidence: null

regression_test:
  path: null

fix:
  commit: null

verification:
  regression: unknown
  full_suite: unknown
```

Finding 状态：

```text
PROPOSED
REPRODUCING
CONFIRMED
REJECTED
FIXING
FIXED
VERIFIED
CLOSED
```

原则：

```text
PROPOSED ≠ BUG
CONFIRMED = BUG
```

---

# 11. Evidence Schema

Evidence 必须绑定 Git HEAD。

示例：

```json
{
  "type": "unit_test",
  "timestamp": "2026-08-24T14:30:00+08:00",
  "command": "pytest",
  "exit_code": 0,
  "passed": 142,
  "failed": 0,
  "skipped": 2,
  "commit": "abc123",
  "stdout_tail": "..."
}
```

最小必填字段：

```text
type
timestamp
command
exit_code
commit
```

Evidence 类型：

```text
build
lint
typecheck
unit_test
integration_test
contract_test
security
review
custom
```

---

# 12. Fresh Evidence 规则

Quality Gate 必须检查：

```text
evidence.commit == git HEAD
```

如果不一致：

```text
Evidence = STALE
```

STALE Evidence 不可用于 Gate。

示例：

```text
commit A
↓
pytest PASS
↓
生成 evidence(commit=A)

代码修改
↓
commit B / HEAD=B

Gate 检查：
A != B
↓
unit_test evidence = STALE
↓
BLOCKED
```

---

# 13. gate.yaml

默认模板：

```yaml
gate:

  requirements:
    must_verified: true
    uncovered_allowed: 0

  invariants:
    violated_allowed: 0

  verification:
    build: required
    unit_test: required
    integration_test: optional

  findings:
    critical_allowed: 0
    major_allowed: 0

  regression:
    confirmed_finding_without_test: 0

  evidence:
    must_match_head: true

  convergence:
    max_iterations: 5
```

---

# 14. quality_gate.py

这是 v0.1 的核心模块。

不要让 LLM 判断 Gate。

## 14.1 输入

读取：

```text
.harness/current-task.yaml
.harness/requirements.yaml
.harness/invariants.yaml
.harness/gate.yaml
.harness/findings/*
.harness/evidence/*
git HEAD
```

## 14.2 检查项

依次检查：

1. Harness 文件是否合法。
2. 当前状态是否允许执行 Gate。
3. Requirement 是否全部满足。
4. Invariant 是否存在 violated。
5. Required verification 是否有 Evidence。
6. Evidence 是否属于当前 HEAD。
7. Critical Finding 是否为 0。
8. Major Finding 是否为 0。
9. Confirmed Finding 是否全部有 Regression Test。
10. Regression Test 是否 verified。

## 14.3 输出

PASS：

```text
QUALITY GATE: PASS

Requirements      PASS
Invariants        PASS
Build             PASS
Unit Tests        PASS
Critical Findings 0
Major Findings    0
Regression Debt   0
Evidence HEAD     MATCH
```

BLOCKED：

```text
QUALITY GATE: BLOCKED

Blocking:
- REQ-004 not verified
- INV-002 violated
- Major finding F-0012 is open
- Unit-test evidence is stale
```

## 14.4 Exit Code

```text
0 = PASS
1 = BLOCKED
2 = INVALID_HARNESS_STATE
```

## 14.5 约束

只有 `quality_gate.py exit=0` 才允许：

```text
GATING → CONVERGED
```

---

# 15. collect_evidence.py

作用：

```text
执行确定性命令
→ 记录 exit code
→ 绑定当前 Git HEAD
→ 保存 Evidence
```

期望调用：

```bash
python scripts/collect_evidence.py \
  --type unit_test \
  --command "pytest"
```

生成：

```text
.harness/evidence/unit-test.json
```

v0.1 暂时不要求解析所有测试框架报告。

至少保存：

```text
command
exit_code
timestamp
commit
stdout_tail
stderr_tail
```

命令失败时仍然需要保存 Evidence。

---

# 16. harness_status.py

提供统一状态视图。

调用：

```bash
python scripts/harness_status.py
```

输出：

```text
TASK-001  Add resumable tool execution

State        REVIEWING
Iteration    2 / 5

Requirements 8 / 8
Invariants   5 / 6

Build        PASS
Unit Tests   PASS
Integration  PASS

Findings
  Critical   0
  Major      1
  Minor      2

Gate         BLOCKED

Blocking
  INV-004
  F-0021
```

每次新的 Agent Session 开始必须优先执行：

```bash
python scripts/harness_status.py
```

---

# 17. validate_state.py

作用：

```text
validate_state.py CURRENT TARGET
```

例如：

```bash
python scripts/validate_state.py REVIEWING GATING
```

合法：

```text
exit 0
```

非法：

```text
INVALID TRANSITION:
IMPLEMENTING → DONE

exit 1
```

建议所有状态更新都统一经过该脚本或内部公共模块。

---

# 18. task-contract Skill

路径：

```text
skills/task-contract/SKILL.md
```

职责：

```text
User Requirement
→ Acceptance Criteria
→ Requirements
→ Invariants
→ Risks
→ Verification Plan
```

不负责写业务代码。

必须产生：

```text
.harness/requirements.yaml
.harness/invariants.yaml
```

并更新：

```text
current-task.state:
CREATED → SPECIFYING → PLANNED
```

输出示例：

```yaml
requirements:
  - id: REQ-001
    statement: interrupted execution can resume
    priority: must

  - id: REQ-002
    statement: duplicated recovery must not duplicate side effects
    priority: must
```

```yaml
invariants:
  - id: INV-001
    statement: one action_id can produce at most one side effect
    category: idempotency
    severity: critical

  - id: INV-002
    statement: terminal state cannot transition back to running
    category: state_machine
    severity: major
```

---

# 19. Superpowers Integration

v0.1 不复制现有 Superpowers Skills。

复用：

```text
brainstorming
writing-plans
test-driven-development
systematic-debugging
subagent-driven-development
requesting-code-review
receiving-code-review
verification-before-completion
finishing-a-development-branch
```

Harness 的定位：

```text
Superpowers = Worker Workflow
Harness = Controller
```

主 SKILL.md 只做 orchestration。

伪流程：

```text
1. Load .harness/current-task.yaml

2. CREATED:
   run task-contract

3. Use Superpowers brainstorming

4. Use Superpowers writing-plans

5. state → IMPLEMENTING

6. Use Superpowers TDD / subagent-driven-development

7. state → VERIFYING

8. Run deterministic verification

9. If verification fails:
      state → IMPLEMENTING
      fix
      repeat

10. state → REVIEWING

11. Run normal Superpowers review

12. Run adversarial-review

13. If blocking finding exists:
      state → REPRODUCING

14. reproduce-finding

15. Confirmed:
      regression test
      state → FIXING
      fix
      state → VERIFYING

16. No blocking finding:
      collect fresh evidence
      state → GATING

17. Run quality_gate.py

18. PASS:
      state → CONVERGED
      state → DONE

19. BLOCKED:
      continue loop

20. max_iterations reached:
      state → ESCALATED
```

---

# 20. adversarial-review Skill

路径：

```text
skills/adversarial-review/SKILL.md
```

目标：

**不是检查代码风格，而是主动构造失败场景。**

输入：

```text
Task Contract
Requirements
Invariants
Diff
Public API
Relevant State Machine
Existing Tests
```

Reviewer 指令核心：

```text
Assume the implementation contains defects.

Do not optimize the implementation.
Do not rewrite the code.
Do not produce generic style feedback.

Try to construct concrete scenarios that violate:
- requirements
- invariants
- failure guarantees
- state transitions
- concurrency guarantees
- idempotency guarantees
- recovery guarantees

Every issue must be emitted as a structured PROPOSED finding.
```

必须输出 Finding Schema。

Reviewer 不允许直接修改代码。

---

# 21. reproduce-finding Skill

路径：

```text
skills/reproduce-finding/SKILL.md
```

流程：

```text
PROPOSED
    ↓
REPRODUCING
    ↓
construct minimal reproducer
    ↓
run
   / \
 FAIL  cannot reproduce
  │       │
  ▼       ▼
CONFIRMED REJECTED
```

CONFIRMED 后必须：

```text
1. 保留 failing test
2. 更新 finding.status = CONFIRMED
3. 写 regression_test.path
4. state → FIXING
5. 修复
6. regression test GREEN
7. full suite GREEN
8. finding → VERIFIED / CLOSED
```

禁止：

```text
Finding → 直接修改代码
```

必须先 Reproduce。

---

# 22. collect-evidence Skill

Skill 只负责决定需要哪些 Evidence。

真正执行由：

```text
collect_evidence.py
```

完成。

例如：

```text
task modifies backend API
↓
required:
- build
- unit_test
- integration_test
```

Skill 不允许自己写：

```text
“测试应该通过”
```

---

# 23. quality-gate Skill

该 Skill 只是调用：

```bash
python scripts/quality_gate.py
```

并根据 Exit Code 更新状态。

禁止 Skill 自己评估：

```text
“综合来看质量足够好”
```

---

# 24. convergence Skill

职责：

```text
判断是否继续循环
```

v0.1 不做复杂评分。

规则：

### PASS

```text
Gate PASS
→ CONVERGED
```

### Continue

```text
Gate BLOCKED
+
存在明确可处理 blocker
+
iteration < max_iterations
→ continue
```

### Escalate

以下任一成立：

```text
iteration >= max_iterations
same confirmed finding repeatedly reappears
same invariant repeatedly violated
test suite unstable
architecture defect suspected
spec ambiguity blocks verification
```

则：

```text
state → ESCALATED
```

并输出原因：

```text
SPEC_AMBIGUITY
ARCHITECTURE_DEFECT
REPEATED_REGRESSION
UNSTABLE_TEST
REVIEW_DISAGREEMENT
MAX_ITERATIONS
```

---

# 25. 主 SKILL.md

主 Skill 的核心角色：

```text
You are the Engineering Harness Controller.

You do not determine completion from model confidence.

You control:
- task state
- workflow transitions
- evidence requirements
- findings lifecycle
- quality gate execution
- convergence

Use Superpowers for development execution.

The task may reach DONE only through:

GATING
→ quality_gate.py exit 0
→ CONVERGED
→ DONE
```

启动时必须：

```text
1. Detect whether .harness exists.
2. Load current-task.yaml.
3. Run harness_status.py.
4. Resume from persisted state.
```

---

# 26. v0.1 开发顺序

不要先实现全部 Skills。

按照以下顺序开发。

## Milestone 1：State Core

实现：

```text
schemas/task.schema.json
templates/current-task.yaml
scripts/validate_state.py
scripts/harness_status.py
```

测试：

```text
合法状态转换
非法状态转换
IMPLEMENTING → DONE 被拒绝
CONVERGED → DONE 被允许
```

验收：

```text
Harness 状态可以持久化
Session 重启后可以恢复
非法状态不能绕过
```

---

## Milestone 2：Evidence + Quality Gate

实现：

```text
schemas/evidence.schema.json
scripts/collect_evidence.py
templates/gate.yaml
scripts/quality_gate.py
```

测试：

```text
fresh PASS evidence → Gate PASS

stale evidence → Gate BLOCKED

missing evidence → Gate BLOCKED

major finding exists → Gate BLOCKED

unverified requirement → Gate BLOCKED

violated invariant → Gate BLOCKED
```

验收：

```text
错误状态绝对不能 Gate PASS
```

这是 v0.1 最重要的 Milestone。

---

## Milestone 3：Finding Lifecycle

实现：

```text
schemas/finding.schema.json
skills/adversarial-review/
skills/reproduce-finding/
```

测试：

```text
PROPOSED 不算 confirmed bug

PROPOSED → REPRODUCING

reproducer fail → CONFIRMED

cannot reproduce → REJECTED

confirmed bug without regression test → Gate BLOCKED
```

---

## Milestone 4：Task Contract

实现：

```text
schemas/requirement.schema.json
schemas/invariant.schema.json
skills/task-contract/
```

测试一个真实 Feature：

```text
requirement
→ acceptance
→ invariant
→ verification plan
```

---

## Milestone 5：Superpowers Integration

实现：

```text
root SKILL.md
skills/collect-evidence/
skills/quality-gate/
skills/convergence/
```

接入：

```text
brainstorming
writing-plans
test-driven-development
subagent-driven-development
verification-before-completion
finishing-a-development-branch
```

验收：

一个真实任务可以完整跑：

```text
CREATED
→ SPECIFYING
→ PLANNED
→ IMPLEMENTING
→ VERIFYING
→ REVIEWING
→ GATING
→ CONVERGED
→ DONE
```

---

# 27. 推荐首个真实 Dogfooding Task

不要使用 Hello World。

建议选一个包含以下特性的 Feature：

```text
API
Database
State
Error Handling
Idempotency
Tests
```

例如：

```text
Implement resumable task execution with idempotent action execution.
```

至少测试：

```text
happy path
duplicate request
timeout
retry
process restart
duplicate recovery
invalid state transition
```

---

# 28. 测试要求

Harness 自身必须测试。

至少：

```text
tests/
├── test_state_machine.py
├── test_quality_gate.py
├── test_evidence.py
├── test_finding_lifecycle.py
└── test_convergence.py
```

禁止只依赖 LLM 验证 Harness 自身。

---

# 29. v0.1 成功指标

Dogfooding 10～20 个真实任务后统计：

## False Done Rate

```text
任务被宣布 DONE 后，
又发现 blocking defect 的比例。
```

目标：

```text
显著下降。
```

## Finding Confirmation Rate

```text
CONFIRMED / PROPOSED
```

用于衡量 Reviewer 噪声。

## Regression Capture Rate

```text
confirmed bug with regression test
/
all confirmed bugs
```

目标：

```text
≈ 100%
```

## Gate Bypass Rate

```text
未 PASS Gate 却进入 DONE
```

目标：

```text
0
```

## Convergence Rate

```text
在 max_iterations 内成功 Gate PASS 的任务比例
```

---

# 30. Codex 实施规则

Codex 在实现本项目时必须遵守：

1. 不一次性实现所有模块。
2. 按 Milestone 顺序提交。
3. 每个 Milestone 必须先有测试。
4. 不修改 Superpowers 核心 Skill，除非 Milestone 5 明确需要。
5. v0.1 不引入数据库。
6. v0.1 不引入 Web UI。
7. v0.1 不引入新的 Agent Runtime。
8. 所有 Gate 判断必须是确定性的 Python 逻辑。
9. 所有状态转换必须验证。
10. 所有关键行为必须有测试。

---

# 31. 建议 Git Commit 顺序

```text
feat: bootstrap harness project structure

feat: add harness task state schema

feat: add deterministic state transition validation

feat: add harness status command

feat: add evidence collection

feat: add deterministic quality gate

feat: add finding lifecycle schema

feat: add adversarial review skill

feat: add finding reproduction workflow

feat: add task contract skill

feat: add convergence controller

feat: integrate superpowers workflow

test: add end-to-end harness scenario

docs: document harness v0.1 usage
```

---

# 32. 第一阶段立即开始的任务

Codex 首先只实现以下内容：

```text
schemas/task.schema.json

templates/current-task.yaml

templates/gate.yaml

scripts/validate_state.py

scripts/harness_status.py

scripts/quality_gate.py

tests/test_state_machine.py

tests/test_quality_gate.py
```

暂时不要实现：

```text
adversarial-review
reproduce-finding
Superpowers integration
multi-agent
```

第一阶段验收条件：

```text
1. CREATED → SPECIFYING 合法

2. IMPLEMENTING → DONE 非法

3. CONVERGED → DONE 合法

4. Requirement 未 verified 时 Gate BLOCKED

5. Invariant violated 时 Gate BLOCKED

6. Major Finding 存在时 Gate BLOCKED

7. Required Evidence 缺失时 Gate BLOCKED

8. Evidence.commit != HEAD 时 Gate BLOCKED

9. 所有条件满足时 Gate PASS

10. Gate PASS exit code = 0
```

---

# 33. Codex 首轮执行 Prompt

可以直接把下面这段交给本地 Codex：

```text
请按照仓库中的《Superpowers → Engineering Harness v0.1 实施手册》进行实现。

当前只执行 Milestone 1 和 Milestone 2，不要提前实现后续 Skill。

目标：

1. 建立 Harness 状态模型。
2. 实现确定性状态转换验证。
3. 实现 Evidence 数据模型。
4. 实现 collect_evidence。
5. 实现 deterministic quality_gate。
6. 为上述能力补齐自动化测试。

约束：

- 不修改 Superpowers 核心代码。
- 不实现 Web UI。
- 不引入数据库。
- 不实现新的 Agent Runtime。
- Gate 判断不得依赖 LLM。
- 状态转换必须由代码验证。
- Evidence 必须绑定当前 Git HEAD。
- IMPLEMENTING/VERIFYING/REVIEWING/FIXING 不允许直接进入 DONE。
- 只有 CONVERGED → DONE 合法。
- 所有实现遵循 TDD。
- 每完成一个 Milestone，运行完整测试并提供实际命令结果。
- 不要仅汇报计划，必须实际修改代码和运行测试。

完成标准：

Milestone 1 和 Milestone 2 的所有测试通过，且 quality_gate.py 能正确区分 PASS、BLOCKED 和 INVALID_HARNESS_STATE。

开始前先：
1. 阅读实施手册。
2. 检查当前仓库结构。
3. 输出不超过 10 行的实施计划。
4. 立即开始修改代码。
```

---

# 34. v0.1 Definition of Done

只有全部满足时，v0.1 才算完成：

```text
State persisted outside LLM context

State transitions deterministic

Evidence collected from real commands

Evidence bound to Git HEAD

Findings structured

Finding reproduction supported

Confirmed bugs require regression tests

Quality Gate deterministic

Gate controls DONE

Convergence loop bounded

Superpowers reused rather than reimplemented

One real project successfully dogfooded
```

---

# 35. 最终原则

Engineering Harness v0.1 的核心不是增加更多 Prompt。

而是把开发过程中的“正确性判断”逐步从模型迁移到：

```text
State
+
Contract
+
Invariant
+
Executable Test
+
Evidence
+
Deterministic Gate
```

最终模型的角色应当是：

```text
Model = Worker

Superpowers = Development Workflow

Engineering Harness = Controller

Tests / Compiler / Gate = Truth
```

**允许 Agent 犯错，但不允许错误轻易穿过 Harness。**

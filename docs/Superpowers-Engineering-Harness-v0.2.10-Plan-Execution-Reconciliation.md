# Superpowers Engineering Harness v0.2.10
## Plan Execution Reconciliation 开发规格

> 版本：v0.2.10
> 状态：Concept Specification；P0 已实现，P1/P2 待实现
> 权威说明：canonical artifacts、字段、blocker code 与 P0/P1/P2 边界以 `docs/Superpowers-Engineering-Harness-v0.2.10-Implementation-Contract.md` 为准；本文示例仅表达产品意图。
> 核心能力：Plan Execution Reconciliation
> 目标：确保 Implementation Plan 中承诺的工作被逐项执行、核对和证明，避免 Agent 在长任务、上下文压缩、异常恢复过程中遗漏计划项。
> 原则：**Plan completion must be reconciled, not asserted.**

---

# 1. 背景

Superpowers Engineering Harness 当前已经形成较完整的工程闭环：

```text
Requirement
    ↓
Specification
    ↓
Alignment / Freeze
    ↓
Implementation
    ↓
Verification
    ↓
Evidence
    ↓
Review
    ↓
Gate
    ↓
DONE
```

v0.2.9 进一步强化：

```text
REQ
 ↓
AC
 ↓
SURFACE
 ↓
VERIFICATION
 ↓
EXPECTED_EVIDENCE
```

并通过 Alignment Freeze / Drift Detection 防止开发过程中需求、边界和验收标准发生未经确认的变化。

但当前仍存在一个执行层缺口：

```text
Requirement
    ↓
Implementation Plan
    ↓
Agent Execute
    ↓
???
    ↓
Verification / Evidence
```

Harness 能较好判断“最终结果是否满足 Requirement”，但不能充分回答“Plan 中承诺的工作是否真正逐项执行”。

---

# 2. 问题定义

假设 Plan 中定义：

```markdown
### Task P-03: Cache invalidation

- Modify `src/cache.py`
- Add `tests/test_cache.py`
- Update `docs/cache.md`
- Run cache regression tests
```

Agent 最终可能只完成代码、测试和测试执行，却遗漏文档更新。如果文档更新没有进入 Requirement / Test Plan / Invariant，现有 Gate 仍可能允许任务完成。

```text
Requirement Coverage = PASS
但：
Plan Execution Coverage < 100%
```

这种问题尤其容易发生在长任务、多阶段开发、上下文压缩、Agent 重启、BLOCKED 恢复、多 Agent / 多模型协作、Review 后重新 Implementation、Plan 较长以及 Q3 / STRICT 工作流。

因此 v0.2.10 引入 **Plan Execution Reconciliation**：

```text
Plan
 ↓
Execution
 ↓
Reconciliation
 ↓
Evidence
 ↓
Gate
```

---

# 3. 核心设计原则

## 3.1 Plan 不是第二套 Requirement

必须严格区分：

```text
requirements.yaml → WHAT：最终必须实现什么
plans/*.md        → HOW：准备如何实现
plan_execution    → EXECUTION：计划实际执行情况
evidence          → PROOF：完成结果的客观证据
gate              → DECISION：是否允许 DONE
```

权威关系：

```text
Requirement > Plan
```

Plan 不允许覆盖 Requirement。如果 Plan 与 Requirement 冲突，Requirement wins。

---

# 4. Reconciliation > Checkbox

以下实现不能作为完成证明：

```markdown
- [x] Add tests
```

因为这仍然属于 Agent Self Assertion。Harness 的基本原则是：

```text
Evidence > Assertion
```

Markdown checkbox 只能作为 Human-readable projection，不能成为 Gate 的唯一事实来源。

真正的状态必须来自：

```text
Plan Item
   +
Execution State
   +
Evidence / Reason
   =
Reconciled State
```

---

# 5. Plan Item

每一个可执行计划项应该具有稳定 ID：

```markdown
### P-001 Implement cache invalidation
- Modify cache implementation
- Add regression tests

### P-002 Update documentation
- Update cache architecture documentation

### P-003 Verify
- Run cache regression tests
```

推荐使用 `P-001`、`P-002`、`P-003`。Plan Item ID 在一个 Task 生命周期内必须保持稳定。

---

# 6. Plan Item 状态模型

至少支持：

```text
PENDING
IN_PROGRESS
COMPLETE
SKIPPED
SUPERSEDED
BLOCKED
```

`COMPLETE` 必须存在足够依据；`SKIPPED` 必须包含 reason；`SUPERSEDED` 必须记录替代项或 Decision；`BLOCKED` 不允许 Final Reconciliation PASS。

示例：

```yaml
status: superseded
reason: "Cache invalidation moved to event-driven implementation."
superseded_by:
  - P-007
decision: DEC-004
```

---

# 7. Plan Execution 数据模型

建议增加：

```text
.harness/
├── current-task.yaml
├── requirements.yaml
├── invariants.yaml
├── gate.yaml
├── plan-execution.yaml
├── findings/
└── evidence/
```

示例：

```yaml
schema_version: "1"

plan:
  path: docs/plans/2026-09-25-cache.md
  fingerprint: sha256:xxxx

execution:
  P-001:
    status: complete
    surfaces:
      - src/cache.py
    evidence:
      - EV-001
      - EV-002

  P-002:
    status: skipped
    reason: >
      Documentation update is no longer required because
      the public behavior did not change.
    decision: DEC-004

  P-003:
    status: complete
    evidence:
      - EV-003
```

---

# 8. Plan Fingerprint

`plan-execution.yaml` 必须绑定 Plan fingerprint：

```yaml
plan:
  path: docs/plans/example.md
  fingerprint: sha256:xxxx
```

当当前 fingerprint 与 stored fingerprint 不一致时：

```text
PLAN_STALE
```

必须重新 reconciliation。

---

# 9. Task-Level Reconciliation

高风险任务推荐：

```text
P-001 → Execute → Reconcile P-001
P-002 → Execute → Reconcile P-002
P-003 → Execute → Reconcile P-003
```

每完成一个 Plan Item：

1. 检查实际改动；
2. 检查 verification；
3. 关联 evidence；
4. 更新 execution state；
5. 再进入下一个 item。

用于降低 Long Task Drift 风险。

---

# 10. Final Plan Reconciliation

进入 Verification / Review / Gate 前进行最终核对：

```text
Implementation Complete
        ↓
Final Plan Reconciliation
        ↓
Verification
        ↓
Review
        ↓
Gate
```

Final Reconciliation 必须遍历所有 Plan Item。

允许状态：

```text
COMPLETE
SKIPPED
SUPERSEDED
```

不允许：

```text
PENDING
IN_PROGRESS
BLOCKED
```

同时要求：

```text
COMPLETE   → evidence exists
SKIPPED    → reason exists
SUPERSEDED → reason + replacement/decision exists
```

---

# 11. Evidence Binding

Plan Item COMPLETE 不应仅依赖文本声明：

```yaml
P-003:
  status: complete
  evidence:
    - EV-003
```

Evidence 应继续绑定实际命令结果与 workspace/HEAD，从而形成：

```text
Plan Item
    ↓
Evidence
    ↓
Workspace / HEAD
```

不是所有 Plan Item 都需要测试证据。代码修改可绑定 CHANGE evidence，测试执行应绑定 VERIFICATION evidence。

---

# 12. Plan Drift

执行过程中允许发现 Plan 不合理，但不能偷偷修改执行方案。

首先判断：

```text
是否改变 Requirement / AC / Contract / Scope？
```

如果没有，则属于 Plan-level adjustment，可以更新 Plan，并重新 fingerprint / reconcile。

如果改变 Requirement、AC、Contract、Scope 或 Architecture boundary，则必须进入已有 Drift / Realignment 流程：

```text
Plan Drift
   ↓
Contract affected?
   ├── NO → Plan Update → Reconcile
   └── YES → Realignment → Re-Freeze → New Plan
```

---

# 13. Markdown Checkbox 同步

Plans 可以继续使用：

```markdown
- [ ] P-001 Implement cache
- [x] P-002 Add tests
```

但：

```text
checkbox != source of truth
```

Source of Truth 是：

```text
plan-execution.yaml
```

推荐由结构化状态向 Markdown checkbox 同步，而不是让 checkbox 成为 Gate truth。

---

# 14. Gate 集成

v0.2.10 新增 Plan Reconciliation Gate，至少检查：

```text
PLAN_PRESENT
PLAN_FINGERPRINT_VALID
PLAN_ITEMS_RECONCILED
PLAN_COMPLETE_EVIDENCE_VALID
PLAN_SKIP_JUSTIFIED
PLAN_SUPERSEDE_JUSTIFIED
```

新增 Findings / Blockers：

```text
PLAN_ITEM_INCOMPLETE
PLAN_ITEM_UNRECONCILED
PLAN_EVIDENCE_MISSING
PLAN_SKIP_UNJUSTIFIED
PLAN_SUPERSEDE_UNJUSTIFIED
PLAN_STALE
PLAN_DRIFT_UNRESOLVED
PLAN_EXECUTION_MISMATCH
```

对于启用了 Plan Reconciliation 的任务，Plan state unknown 必须 fail-closed。

---

# 15. Risk-Adaptive Enforcement

Plan Reconciliation 不应该无条件作用于所有任务：

| Task Class | Plan | Reconciliation |
|---|---|---|
| Q0 | 不需要 | 不需要 |
| Q1 / FAST | 可选 | 默认不强制 |
| Q2 | 必须 | Final Reconciliation |
| Q3 / STRICT | 必须 | Task-Level + Final |

Q1 不应因为轻量修改产生额外 Plan/Reconciliation 成本。

Q2：

```text
Plan → Implementation → Final Reconciliation → Verification → Review → Gate
```

Q3：

```text
Plan
 ↓
P1 Execute → P1 Reconcile
 ↓
P2 Execute → P2 Reconcile
 ↓
...
 ↓
Final Reconciliation
 ↓
Verification → Review → Gate
```

---

# 16. Context Compression Recovery

当发生 Context Compression、Agent Restart、Model Switch、Session Recovery 时，不应依赖聊天历史判断执行进度，而应读取：

```text
current-task.yaml
requirements.yaml
plan-execution.yaml
gate.yaml
```

例如：

```yaml
execution:
  P-001:
    status: complete
  P-002:
    status: complete
  P-003:
    status: in_progress
  P-004:
    status: pending
```

恢复后：

```text
resume_from = P-003
```

---

# 17. Token Optimization

v0.2.10 不能为了 Plan Reconciliation 破坏已有 Context Efficiency 目标。

禁止每完成一个小动作就重新读取整个 Plan、全部 Requirement 和全部 Evidence。

推荐：

```text
Plan Parse Once
      ↓
Plan Index
      ↓
P-ID based lookup
```

---

# 18. CLI 建议

建议增加：

```bash
harness plan init
harness plan status
harness plan reconcile P-003
harness plan reconcile --final
harness plan check
```

`harness plan status` 示例：

```text
Plan Execution

Plan:
docs/plans/cache.md

Progress:
7 / 9 reconciled

COMPLETE     6
SKIPPED      1
PENDING      1
BLOCKED      1
```

Gate Preview 也应显示 Plan Execution 状态。

---

# 19. 自动 Reconciliation 边界

Harness 可以自动判断文件是否修改、测试是否执行、Evidence 是否存在等 mechanical facts。

Harness 不能擅自决定为什么跳过一个任务、为什么改变架构、为什么 Requirement 不再需要。

```text
Mechanical facts → AUTO
Semantic decisions → DECISION / explicit reason
```

重要 SKIPPED / SUPERSEDED 应与 Decision 集成。

---

# 20. 与其他 Gate 的关系

Implementation Plan 与 Test Plan 必须区分：

```text
Implementation Plan → HOW TO BUILD
Test Plan           → HOW TO VERIFY
```

完整关系：

```text
Requirement
      ↓
Acceptance Criteria
      ↓
Alignment
      ↓
Freeze
      ↓
Implementation Plan
      ↓
Execution
      ↓
Plan Reconciliation
      ↓
Verification / Test Plan
      ↓
Evidence
      ↓
Review
      ↓
Gate
      ↓
DONE
```

Alignment 解决：Are we building the right thing?

Plan Reconciliation 解决：Did we execute what we planned?

Verification 解决：Does it actually work?

Evidence 解决：Can we prove it?

Gate 解决：Can we declare DONE?

---

# 21. 状态机集成

不要为每个 Plan Item 增加 Harness 顶层状态，避免状态机爆炸。

正确方式是在 `IMPLEMENTING` 内部维护 `plan_execution`：

```text
Harness State: IMPLEMENTING

Plan Sub-State:
P-001 COMPLETE
P-002 IN_PROGRESS
P-003 PENDING
```

---

# 22. DONE 条件扩展

对于启用了 Plan Reconciliation 的任务：

```text
Requirements PASS
Alignment PASS
Plan Reconciliation PASS
Verification PASS
Evidence PASS
Review PASS
Gate PASS
DECISION CONVERGED
        ↓
       DONE
```

---

# 23. Benchmark 要求

至少覆盖：

1. Plan 全部执行 → PASS。
2. 遗漏一个 Plan Item → `PLAN_ITEM_INCOMPLETE`。
3. Agent 手工 `[x]` 但没有 Evidence → `PLAN_EVIDENCE_MISSING`。
4. 合法 SKIPPED → PASS。
5. SKIPPED 无 reason → `PLAN_SKIP_UNJUSTIFIED`。
6. Plan 修改 → `PLAN_STALE`。
7. Context Compression 后恢复 → 正确恢复当前 Plan Item。
8. Q1 FAST → 不增加强制 Reconciliation 开销。

---

# 24. 测试要求

至少增加：

```text
test_plan_execution_schema
test_plan_item_complete
test_plan_item_pending
test_plan_skip_requires_reason
test_plan_superseded_requires_reason
test_plan_evidence_binding
test_plan_fingerprint
test_plan_stale_detection
test_final_reconciliation
test_gate_blocks_incomplete_plan
test_q1_does_not_require_plan_reconciliation
test_q2_requires_final_reconciliation
test_q3_requires_task_reconciliation
test_context_recovery_from_plan_execution
```

同时增加完整集成测试：

```text
Plan
 ↓
Implementation
 ↓
Reconciliation
 ↓
Verification
 ↓
Gate
 ↓
DONE
```

---

# 25. 向后兼容与 Migration

v0.2.10 不允许导致旧项目升级后所有任务突然 BLOCKED。

旧任务没有 `plan-execution.yaml` 时，应根据 task classification、workflow version、feature enablement 决定是否强制。

建议 v0.2.9 已有任务默认：

```yaml
plan_reconciliation:
  enabled: false
```

新建 Q2/Q3 任务根据 classification 自动启用。

---

# 26. 非目标

v0.2.10 不负责：

- 自动生成最佳 Implementation Plan；
- 判断 Plan 技术方案一定正确；
- 替代 Requirement；
- 替代 Test Plan；
- 替代 Review。

本版本只解决：

> **Implementation Plan 是否被完整、可解释、可验证地执行。**

---

# 27. Definition of Done

v0.2.10 只有同时满足以下条件才能认为完成：

- Plan Item 有稳定 ID；
- 存在结构化 Plan Execution 状态；
- Plan Execution 与 Plan fingerprint 绑定；
- COMPLETE 可以关联实际 Evidence；
- SKIPPED 必须有明确 reason；
- SUPERSEDED 必须可追溯原因/替代项/Decision；
- Q2 支持 Final Reconciliation；
- Q3 支持 Task-Level + Final Reconciliation；
- Gate 能阻止未完成 Plan；
- Markdown checkbox 不作为唯一 Source of Truth；
- Context Compression 后可以从结构化状态恢复执行位置；
- Plan Drift 与 v0.2.9 Alignment/Realignment 正确衔接；
- 不破坏 Q0/Q1 FAST Path；
- 不明显增加低风险任务 Token/Tool Call 成本；
- Benchmark 覆盖 Plan omission / stale / fake completion / recovery；
- 原有测试全部通过；
- 新增 Plan Reconciliation 测试全部通过。

---

# 28. 实施优先级

```text
P0
├─ Plan Item stable ID
├─ plan-execution.yaml schema
├─ Plan fingerprint
├─ Final Reconciliation
├─ Gate integration
└─ fail-closed blockers

P1
├─ Task-Level Reconciliation
├─ Evidence binding
├─ Plan status CLI
├─ Gate Preview
└─ Context Recovery

P2
├─ Markdown checkbox sync
├─ richer reconciliation report
├─ automatic mechanical reconciliation
└─ token/context optimization
```

P0 完成后即可形成 v0.2.10 的最小闭环。

---

# 29. 核心不变量

```text
INV-PLAN-001
Requirement remains authoritative over Plan.

INV-PLAN-002
Checkbox is never sufficient proof of completion.

INV-PLAN-003
COMPLETE must be reconcilable with actual execution/evidence.

INV-PLAN-004
SKIPPED must be explicitly justified.

INV-PLAN-005
SUPERSEDED must remain traceable.

INV-PLAN-006
Plan changes invalidate stale reconciliation.

INV-PLAN-007
Contract-changing Plan Drift must trigger Realignment.

INV-PLAN-008
Unknown Plan state fails closed when reconciliation is required.

INV-PLAN-009
Plan Reconciliation must not unnecessarily penalize Q0/Q1 tasks.

INV-PLAN-010
Persistent Harness state, not conversation history, determines recovery.
```

---

# 30. 最终工程闭环

```text
Requirement
    ↓
Acceptance Criteria
    ↓
Alignment / Freeze
    ↓
Implementation Plan
    ↓
P-001 → Execute → Reconcile
P-002 → Execute → Reconcile
...
    ↓
Final Plan Reconciliation
    ↓
Verification
    ↓
Evidence
    ↓
Review
    ↓
Gate
    ↓
DECISION: CONVERGED
    ↓
DONE
```

> **v0.2.9 确保“开发前，我们对要做什么达成一致”；v0.2.10 确保“开发后，我们能够证明计划中的工作确实被逐项处理”。**

核心目标：

```text
Plan
 ↓
Execute
 ↓
Reconcile
 ↓
Verify
 ↓
Evidence
 ↓
Gate
 ↓
DONE
```

从：

```text
AI: "计划里的任务我都完成了。"
```

升级为：

```text
Harness:
"每一个 Plan Item 都有明确状态；
完成项有执行依据；
跳过项有原因；
变更项可追溯；
未完成项不能进入 DONE。"
```

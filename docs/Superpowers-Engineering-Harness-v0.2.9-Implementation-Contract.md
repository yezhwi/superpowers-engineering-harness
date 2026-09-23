# Superpowers Engineering Harness v0.2.9 实施契约

> 版本：v0.2.9  
> 状态：Implementation Contract（对实现有约束力）  
> 愿景规格：[Pre-Implementation Alignment & Scope Freeze 开发规格](./v0.2.9—Pre-Implementation-Alignment-Scope-Freeze-开发规格.md)  
> 基线：v0.2.8 / `ca687c5`  

本契约冻结 v0.2.9 实际实现范围。愿景规格保留产品意图；二者冲突时，代码、测试、CLI 和发版验收以本契约为准。

## Scope

v0.2.9 增加 Intent Closure：进入实现前，结构化证明 Goal、范围、决策、验收映射和验证策略已闭环；冻结后，合同输入变更不得静默继续实现。

本版本不实现：自动推断所有语义 drift、强制证明 Agent 从未询问可由代码回答的 Fact、独立 workflow engine、独立 Gate、`CONTEXT.md`、`decisions.yaml`。

## Binding Decisions

| Concern | Binding decision | Reason |
| --- | --- | --- |
| Lifecycle | v1 不新增 `DISCOVERING` 或 `ALIGNING` 持久状态。 | Discovery 是 Agent 行为；现有状态机保持唯一。 |
| Q2/Q3 entry | Alignment Gate 挂 `PLANNED -> IMPLEMENTING`。 | Requirements 与 Test Plan 在 `SPECIFYING` 产生；在此前检查会制造第二份规格。 |
| Q1 entry | `CLASSIFIED -> IMPLEMENTING` 前执行 lightweight alignment。 | 保留 FAST 路径；无未决 Decision 不提问。 |
| Decisions | 复用 `decisions/DEC-*.yaml` 与 `decisions/index.yaml`。 | 已有 schema、事务发布、哈希与 Context 恢复。不得创建 `decisions.yaml`。 |
| Alignment | 新增薄 `alignment.yaml`，只保存 Intent Closure 映射和 Freeze；不复制 REQ、DEC、INT 正文。 | 每个领域保持单一权威。 |
| Drift | 既持久化 Finding 审计记录，也生成 GateBlocker。 | Finding 保留原因/影响/审批历史；Blocker 提供 fail-closed 路由。 |
| Realignment | 复用受控 `IMPLEMENTING -> SPECIFYING` 边，要求明确 drift reason。 | 不新增任意回退通道。 |

## Data Ownership

| Data | Authoritative source | Notes |
| --- | --- | --- |
| Task title/description、路径所有权 | `current-task.yaml` | 不是产品 Scope 合同。 |
| Requirement statement、priority、test-plan cases | `requirements.yaml` | 不复制到 alignment。 |
| User decision | `decisions/DEC-*.yaml` | `index.yaml` 是成员索引，不是第二权威正文。 |
| External boundary | `interface-contracts/INT-*.yaml` | 保持现有 interface lifecycle。 |
| Intent Closure 与 Freeze | `alignment.yaml` | 新增薄 envelope。 |
| Runtime proof | `evidence/*.json` | 只在 Verification 后产生。 |
| Drift audit | `findings/FND-*.yaml` 的新增 alignment finding variant | 复用 Finding ID、存储和命令基础设施。 |

`alignment.yaml` v1 必含：`task_id`、`goal.summary`、`scope.in`、`scope.out`、`non_goals`、`boundaries`、`constraints`、`assumptions`、AC、surface、verification、`decision_ids`、`open_questions`、`open_decisions`、`open_loops`、`freeze`。

AC、surface 与 verification 仅在此文件存映射：

```text
REQ -> AC -> SURFACE -> VERIFICATION -> EXPECTED_EVIDENCE
```

每个 AC 必须引用至少一个 REQ；每个 REQ 必须至少映射一个 AC；每个 AC 必须有 verification 和 non-empty `expected_evidence`。Critical REQ 还必须有 surface/seam。实际 evidence 仍只写入 `evidence/*.json` 与现有 REQ evidence 引用。

## Lifecycle and Gates

### Q0

问答和分析不创建 task，不运行 Alignment Gate。

### Q1 / FAST

`CLASSIFIED -> IMPLEMENTING` 前生成最小 alignment：Goal、scope in/out、至少一个 AC、verification、expected evidence。无 `PROPOSED` DEC 时自动完成；有 `PROPOSED` DEC 时停止并走既有 Decision CLI。Q1 不要求 Full Alignment。

### Q2 / Q3

保留：

```text
CREATED -> CLASSIFIED -> SPECIFYING -> PLANNED -> IMPLEMENTING
```

`PLANNED -> IMPLEMENTING` 依序检查 minimal implementation、现有 Test Plan Gate、Alignment Gate。任一失败，拒绝 transition。Q3 额外要求明确用户确认的 high-impact Decision；Q2 沿用现有 Decision policy。

Alignment Gate 返回 `ALIGNMENT_READY` 或 `ALIGNMENT_BLOCKED`，并列出缺字段、未决 Decision、open loops 与下一动作。以下 blocker 均 fail-closed：

```text
ALIGNMENT_INCOMPLETE
OPEN_DECISION
OPEN_LOOP
CONTRACT_CHANGED
```

现有 `TEST_PLAN_*` 不迁移。Alignment 判断“实现什么、期望什么证据”；Test Plan 判断 strategy、case、测试绑定和最终覆盖是否充分。

## Freeze and Drift

Gate PASS 后设置：

```yaml
freeze:
  frozen: true
  frozen_at: <UTC ISO-8601>
  contract_hash: sha256:<digest>
```

哈希输入是 canonical JSON，键排序、UTF-8、无 YAML 格式噪声。输入包含 Goal、scope in/out、non-goals、boundaries、constraints、assumptions、AC 映射、critical decision IDs 与其 accepted selected option、verification 的 expected evidence、相关 INT IDs；不包含 timestamps、实际 evidence、测试文件路径或 private helper 名称。

发现 frozen input 的当前哈希不匹配时，产生 `CONTRACT_CHANGED` blocker。Agent 检测到 API、数据合同、权限、持久化、AC、用户可见行为或关键边界的拟议变更时，创建 blocking alignment Finding；不得先修改合同或继续受影响实现。

唯一 realign 路线：

```text
IMPLEMENTING
  -> SPECIFYING  (reason: SCOPE_DRIFT | CONTRACT_CHANGED | NEW_REQUIRED_DECISION)
  -> PLANNED     (closure 与 Test Plan 重算)
  -> IMPLEMENTING (new freeze required)
```

`controlplane.cmd_transition` 必须拒绝缺失 reason 的该回退；现有 FAST risk escalation 继续可用，不能被 drift 路径绕过。rename private helper、fixture 组织、局部算法替换与等价内部重构不是 drift，除非改变冻结输入。

## Context Recovery

Context Layer 0 新增 alignment 摘要与 freeze reference/hash；完整 envelope 作为按需 Layer 2 reference。继续内联当前 task 的 ACCEPTED `DEC-*`。Context 恢复不得重新询问已 ACCEPTED Decision；hash/reference 校验失败必须报完整性错误或 `CONTRACT_CHANGED`，不得使用旧摘要继续实现。

## Acceptance Mapping

| v0.2.9 AC | v1 proof |
| --- | --- |
| AC-01, AC-06 | Q2/Q3 transition tests：不完整或 open loop 拒绝 IMPLEMENTING。 |
| AC-02 | Agent skill/fixture protocol；控制面仅强制 unresolved Decision 不可进入实现。 |
| AC-03, AC-04 | 现有 Decision schema/CLI/Context 回归；不引入汇总 decisions 文件。 |
| AC-05 | closure calculator tests 覆盖 REQ/AC/surface/verification/expected-evidence 双向缺边。 |
| AC-07, AC-08 | canonical hash、freeze 和 changed-input blocker tests。 |
| AC-09, AC-10 | controlled realign transition tests，含 reason code 和新 freeze。 |
| AC-11 | private rename / equivalent refactor fixture 不产生 drift。 |
| AC-12, AC-13 | Q1 lightweight fixture；Context/tool-call benchmark 不要求 full alignment。 |
| AC-14 | compact Context restore 测试含 envelope hash 与 accepted decisions。 |
| AC-15 | 既有 state machine、Gate、Test Plan、Review、Context suites回归。 |

## Phased Delivery

1. **Data model**：新增 alignment schema、alignment Finding variant；扩 Context schema 与 source access。测试 schema、单一权威和 Context reference。
2. **Closure**：实现纯函数 closure calculator 与 blocker projection。测试每条缺边和完整图。
3. **Entry Gate**：在 `cmd_transition` 的 `PLANNED -> IMPLEMENTING` 接入 Alignment Gate；Q1 接入 lightweight 检查。测试 fail-closed 与现有 Test Plan 顺序。
4. **Freeze**：实现 canonical hash、freeze、diff。测试格式无关 hash、合同字段变更与非合同字段不变。
5. **Drift and realign**：实现 alignment Finding、reason-code 回退和 re-freeze 要求。测试 API/AC/permission drift 与 private rename 非 drift。
6. **Context and CLI**：增加 `harness align`、`align status`、`align check`、`align diff`，并进入 compact Context。CLI 只编排既有 domain 模块。
7. **Benchmark**：为 drift、无谓提问、返工增加可观测输入；无宿主数据时报告 `INCONCLUSIVE`，不得伪造 agent 行为指标。

每阶段先写失败测试，再写最小实现；完成阶段后运行相关旧回归。不得把阶段 4–7 与 schema/closure 变更混成单个大改动。

## Definition of Done

v0.2.9 Product Done 要求：全部 AC 对应可执行或确定性 fixture；Alignment Gate 与现有 Gate 均 fail-closed；完整 Freeze/realign/Context evidence；v0.2.8 回归通过；Benchmark 对缺失宿主指标保持 `INCONCLUSIVE`。不以自然语言“已对齐”代替结构化检查。

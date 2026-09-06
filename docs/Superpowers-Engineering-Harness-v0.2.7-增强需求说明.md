# Superpowers Engineering Harness v0.2.7 增强需求说明

> 版本：v0.2.7 Enhancement  
> 日期：2026-09-02  
> 状态：Implementation Requirement  
> 面向：Engineering Harness 实现者 / AI Coding Agent  
> 范围：Harness 控制面、Skill、Schema、CLI、Review/Gate；不直接修改业务项目架构  
>
> 新增能力：
>
> 1. Recommendation-aware Decision Record
> 2. Interface-first Engineering Contract

---

# 1. 背景

Engineering Harness 当前已经能够通过：

```text
State
+ Contract
+ Invariant
+ Test Plan
+ Evidence
+ Review
+ Finding
+ Gate
```

控制 AI Coding 任务从需求到完成。

但实际开发过程中仍存在两个重要缺口。

## 1.1 用户决策缺乏工程化记录

开发过程中经常出现：

```text
Agent:
数据库字段应该使用 JSON 还是独立表？

用户：
你推荐哪个？

Agent：
推荐独立表，因为……

用户：
可以，就这么做。
```

当前这类信息通常只存在于模型上下文。

随着：

- Session 切换；
- Context 压缩；
- 子 Agent 执行；
- 长任务执行；
- Review / Fix 循环；

后续 Agent 可能：

- 再次询问已经决定的问题；
- 使用不同方案；
- 忘记用户明确限制；
- 无法解释为什么采用当前实现。

因此：

> 用户已经确认的工程决策必须成为 Harness 的持久化任务事实，而不能只存在于对话历史。

---

## 1.2 对外接口容易被实现细节驱动

AI Coding 常见模式是：

```text
先实现
 ↓
发现需要 API
 ↓
顺手定义 API
 ↓
测试围绕当前实现编写
```

结果容易出现：

- API 被内部数据结构污染；
- 不稳定字段直接暴露；
- Service 实现和接口高度耦合；
- 无法替换实现；
- Mock 困难；
- API 演进困难；
- breaking change 没有被识别；
- 重构内部实现时被迫修改调用方。

尤其对于：

- HTTP API；
- RPC；
- SDK；
- Plugin API；
- Event；
- Message；
- Service Interface；
- 公共 Python / Java / TypeScript API；

应该采用：

```text
Consumer / Contract
        ↓
    Interface
        ↓
 Implementation
```

而不是：

```text
Implementation
        ↓
    Interface
```

因此 Harness 应增加 **Interface-first Engineering Contract**。

---

# 2. 目标

本次增强必须实现：

```text
用户决策
    ↓
Agent 基于现状给出候选方案
    ↓
给出 Recommendation + Reason
    ↓
用户确认 / 覆盖
    ↓
Decision Record
    ↓
后续 Agent 自动读取
    ↓
Implementation / Review / Gate
```

以及：

```text
Requirement
    ↓
识别 External/Public Contract
    ↓
先定义 Interface Contract
    ↓
验证兼容性和测试策略
    ↓
Implementation
    ↓
Review
    ↓
Gate
```

最终形成：

```text
Requirement
    ↓
Decision
    ↓
Contract
    ↓
Interface
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
```

---

# 3. 非目标

本版本不要求：

1. 自动替用户作最终业务决策；
2. 用户没有授权时自动接受 Agent 推荐；
3. 使用 LLM 自动推断所有 API breaking change；
4. 实现完整 OpenAPI / Protobuf / GraphQL diff 引擎；
5. 强制所有内部函数创建 interface；
6. 为简单 CRUD 制造额外抽象层；
7. 强制 Dependency Injection Framework；
8. 自动生成企业级 API Governance 平台；
9. 将 ADR 完整替代；
10. 将所有聊天内容永久保存。

本功能关注：

> **真正影响任务执行的用户决策和公开契约。**

---

# 4. 核心原则

必须遵循以下原则。

### Principle 1 — Recommend, don't decide

当需要用户决策时：

```text
Agent 可以推荐
Agent 不可以代替用户确认
```

---

### Principle 2 — Recommendation 必须有依据

不得输出：

```text
推荐 A，因为 A 更好。
```

必须基于：

- 当前代码；
- 当前架构；
- 当前依赖；
- 当前任务目标；
- 当前风险；
- 已有 Convention；
- 已确认 Decision；
- 已知兼容性要求；

进行推荐。

---

### Principle 3 — Accepted Decision 必须持久化

用户确认之后：

```text
Decision != conversation memory
Decision = persisted harness state
```

---

### Principle 4 — Decision 是约束，不是建议

一旦用户确认：

```text
ACCEPTED Decision
```

后续 Agent 默认必须遵守。

需要改变时必须：

```text
重新向用户提出 Decision Revision
```

不得静默修改。

---

### Principle 5 — Public interface before implementation

对于新增或修改公开接口：

```text
Contract before Implementation
```

必须先明确：

- consumer；
- request/input；
- response/output；
- error semantics；
- compatibility；
- versioning；
- observable behavior；

再实现内部逻辑。

---

### Principle 6 — Interface-first ≠ Interface everywhere

禁止为了满足规则产生：

```text
IUserService
UserServiceImpl
UserServiceFactory
UserServiceProvider
```

而没有实际架构价值。

Interface-first 只针对具有稳定边界意义的 contract。

---

# 5. 功能一：Recommendation-aware Decision Record

## 5.1 什么情况下属于 Decision

以下场景 SHOULD 创建 Decision：

### Architecture

例如：

```text
REST vs RPC
同步 vs 异步
Repository vs Direct DB
Redis vs local cache
```

### Public Contract

例如：

```text
API endpoint
response schema
event schema
SDK public method
兼容策略
```

### Scope

例如：

```text
本次顺带重构吗？
是否迁移历史数据？
是否支持 legacy 行为？
```

### Risk / Cost

例如：

```text
只跑相关测试还是 full suite？
是否引入新依赖？
是否执行 migration？
```

### Requirement ambiguity

例如：

```text
删除还是软删除？
失败时重试还是直接返回？
```

---

# 6. 不应创建 Decision 的情况

以下行为不应该频繁打断用户：

```text
变量名选择
private helper 名称
明显的 bug 修复方式
formatter 选择
已有项目 convention 已经明确的问题
```

原则：

> 能由 Requirement、已有 Decision、Repository Convention 或确定性事实直接回答的问题，不应询问用户。

---

# 7. Decision Proposal

需要用户决定时，Agent 必须至少提供：

```text
Decision
Options
Recommendation
Reason
Trade-offs
Impact
```

推荐展示形式：

```text
需要确认：缓存策略

A. 本地缓存
B. Redis
C. 不增加缓存

推荐：B — Redis

理由：
当前服务已有 Redis 基础设施，并且该服务运行多个实例。
如果使用本地缓存，各实例可能产生数据不一致。

代价：
增加一次网络访问，但不需要新增基础设施。

影响：
涉及 service 和 cache adapter，不修改外部 API。
```

---

# 8. 基于现状进行 Recommendation

Recommendation MUST 使用当前可观察事实。

允许依据：

```text
repository state
task contract
requirements
invariants
accepted decisions
existing interfaces
dependencies
risk profile
impact analysis
test plan
```

Recommendation SHOULD 明确区分：

```text
FACT
ASSUMPTION
RECOMMENDATION
```

不得把假设描述为事实。

例如：

错误：

```text
推荐 Kafka，因为项目以后肯定会有高并发。
```

正确：

```text
当前仓库没有 Kafka 依赖。

如果本需求没有明确的大规模异步吞吐要求，
推荐继续使用现有数据库事务方案，
避免仅基于未来假设引入新的基础设施。
```

---

# 9. 用户接受 Recommendation

以下表达可以视为接受：

```text
可以
按推荐来
就这么做
选 A
采用你推荐的方案
```

但必须能够明确对应当前 pending Decision。

如果同时存在多个 pending decisions：

```text
“可以”
```

不得自动应用到所有 Decision。

必须消除歧义。

---

# 10. 用户覆盖 Recommendation

例如：

```text
Agent:
推荐 A。

User:
不用，选 B。
```

必须记录：

```yaml
recommended_option: A
selected_option: B
selection_source: user_override
```

不得把用户选择篡改成推荐项。

---

# 11. Decision 持久化模型

建议新增：

```text
.harness/decisions/
```

结构：

```text
.harness/
├── current-task.yaml
├── requirements.yaml
├── invariants.yaml
├── gate.yaml
├── decisions/
│   ├── DEC-001.yaml
│   └── DEC-002.yaml
├── findings/
└── evidence/
```

不要把全部 Decision 塞进：

```text
current-task.yaml
```

原因：

- Decision 数量可能持续增加；
- 独立 schema 更容易验证；
- 可以独立审计；
- 后续可被其他任务引用；
- 避免 current-task.yaml 无限膨胀。

---

# 12. Decision Schema

新增：

```text
src/harness/schemas/decision.schema.json
```

建议结构：

```yaml
id: DEC-001

task_id: TASK-027

status: ACCEPTED

topic: cache_strategy

question: >
  Should the service use local cache or Redis?

context:
  - service runs multiple instances
  - repository already contains Redis client

options:

  - id: local-cache
    description: In-process cache

  - id: redis
    description: Existing Redis infrastructure

recommendation:
  option: redis

  reasons:
    - avoids per-instance cache inconsistency
    - reuses existing repository infrastructure

  tradeoffs:
    - adds network dependency

selected:
  option: redis

  source: accepted_recommendation

  decided_by: user

decision_reason:
  - user accepted current recommendation

scope:
  - src/service/**
  - src/cache/**

constraints:
  - do not introduce another cache technology

created_at: "..."

accepted_at: "..."

supersedes: null
superseded_by: null
```

---

# 13. Decision 状态

至少支持：

```text
PROPOSED
ACCEPTED
REJECTED
SUPERSEDED
```

状态：

```text
PROPOSED
   │
   ├──→ ACCEPTED
   │
   └──→ REJECTED

ACCEPTED
   ↓
SUPERSEDED
```

已 ACCEPTED Decision 不允许直接覆盖原文件表达新的选择。

必须：

```text
DEC-001
   ↓ superseded by
DEC-004
```

保留审计历史。

---

# 14. CLI

建议新增：

```text
harness decision
```

至少支持：

```text
harness decision propose
harness decision accept
harness decision reject
harness decision supersede
harness decision list
harness decision show
```

例如：

```bash
harness decision propose \
  --topic cache-strategy \
  --question "Which cache should be used?" \
  --option local \
  --option redis \
  --recommend redis \
  --reason "existing infrastructure"
```

用户确认后：

```bash
harness decision accept DEC-001 --option redis
```

覆盖 Recommendation：

```bash
harness decision accept DEC-001 \
  --option local \
  --source user-override
```

---

# 15. Skill 行为

Engineering Harness Skill 必须增加规则：

```text
Before asking a user to choose:

1. inspect current facts
2. enumerate meaningful options
3. identify recommendation
4. explain recommendation reason
5. explain important trade-offs
6. ask user
```

用户确认后：

```text
persist decision
    ↓
continue execution
```

不能：

```text
用户确认
    ↓
仅回复“好的”
    ↓
继续开发
```

---

# 16. Session Resume

Session Startup 时：

除读取：

```text
current-task
requirements
invariants
risk profile
```

之外，还必须读取：

```text
active accepted decisions
```

至少能够得到：

```text
Decision ID
topic
selected option
constraints
scope
```

避免重新加载大量历史文本。

---

# 17. Decision 与 Context Token

Decision Record 的目的之一是降低长任务 context 成本。

Agent 不需要重新读取完整聊天历史。

只需要读取：

```text
Active Decision Summary
```

例如：

```text
DEC-001 cache_strategy = redis
DEC-002 api_versioning = backward-compatible
DEC-003 migration = no historical migration
```

只有发现冲突时再读取完整 Decision。

---

# 18. Decision 冲突

如果实现计划与 ACCEPTED Decision 冲突：

Harness/Skill 必须阻止 Agent 静默继续。

例如：

```text
DEC-001:
selected = redis
```

Agent 准备：

```text
implement local cache
```

必须：

```text
stop
 ↓
report conflict
 ↓
request decision revision
```

---

# 19. Decision Revision

如果开发中出现新证据：

```text
原决策采用 A
但发现 A 无法满足 invariant
```

允许 Agent 建议重新决策。

必须展示：

```text
Current Decision
New Evidence
Recommended Revision
Impact
```

例如：

```text
Current:
DEC-004 chose synchronous processing.

New evidence:
processing can exceed the existing 30-second request timeout.

Recommendation:
change to asynchronous processing.

Impact:
public API changes from immediate result to job status contract.
```

只有用户明确确认后才能 supersede 原 Decision。

---

# 20. Decision 与 Gate

不要求 Gate 判断：

```text
“用户的技术选择是否正确”
```

Gate 只判断可确定事实。

例如：

```text
accepted Decision 是否存在未解决冲突
required Decision 是否仍为 PROPOSED
Decision 是否被非法覆盖
Decision references 是否有效
```

建议 blocker：

```text
DECISION_UNRESOLVED
DECISION_CONFLICT
DECISION_REFERENCE_INVALID
DECISION_SUPERSEDE_INVALID
```

---

# 21. 功能二：Interface-first Engineering Contract

## 21.1 定义

本需求中的 Interface 指：

> 调用方依赖，并且实现方应保持稳定的行为契约。

包括：

```text
HTTP REST API
GraphQL schema
RPC / gRPC
Message/Event
SDK Public API
Plugin API
CLI machine-readable contract
跨模块 Service Interface
对其他项目公开的 library API
```

不局限于语言中的：

```text
interface
abstract class
Protocol
```

---

# 22. External Interface

满足以下任一条件可视为 External/Public Interface：

```text
被仓库外 consumer 调用
被其他部署单元调用
被第三方调用
被插件调用
被其他团队依赖
属于 public SDK API
属于稳定 event/message contract
```

---

# 23. Interface-first 基本规则

对于新增 External Interface：

必须：

```text
Requirement
 ↓
Consumer
 ↓
Interface Contract
 ↓
Examples / Tests
 ↓
Implementation
```

不得默认：

```text
Implementation
 ↓
Expose implementation as API
```

---

# 24. Interface Contract 最低要求

新增或修改外部 Interface 时，必须明确：

### Consumer

```text
who calls it?
```

### Input

```text
fields
types
required / optional
validation
```

### Output

```text
fields
types
semantics
```

### Error Contract

```text
error code
exception
HTTP status
retryability
```

### Compatibility

```text
backward compatible?
breaking?
migration required?
```

### Versioning

如果需要：

```text
API version
event version
schema version
```

### Observability

需要能够定位：

```text
request
failure
dependency
correlation/trace context
```

这部分可以复用当前 diagnosability contract。

---

# 25. Implementation Dependency Direction

推荐依赖方向：

```text
Consumer
   ↓
Interface
   ↑
Implementation
```

业务核心不得依赖具体 adapter。

例如：

```text
OrderService
     ↓
PaymentGateway
     ↑
StripePaymentGateway
```

而不是：

```text
OrderService
     ↓
StripePaymentClient
```

---

# 26. Public DTO 与 Internal Model

External Interface SHOULD 避免直接暴露内部 persistence model。

不推荐：

```text
Database Entity
      ↓
Directly serialize
      ↓
Public API
```

推荐：

```text
Database Entity
      ↓
Mapper
      ↓
Public Contract DTO
```

但对于简单且明确没有独立生命周期的 Q1 修改，不要求为了形式创建无意义 DTO。

---

# 27. Public Error Contract

不得把内部异常直接当外部协议。

例如不推荐：

```text
SQLException
NullPointerException
KeyError
```

直接成为客户端 contract。

需要稳定 external error semantics。

例如：

```text
USER_NOT_FOUND
INVALID_ARGUMENT
DEPENDENCY_UNAVAILABLE
```

---

# 28. Interface Change Classification

Harness 风险分类必须考虑 public interface。

如果修改：

```text
external API
public SDK
event schema
cross-service contract
```

不能作为普通低风险 Q1 处理。

至少进入：

```text
Q2 / STANDARD
```

如果涉及：

```text
breaking compatibility
cross-system migration
authorization/security contract
deployment coordination
```

应该升级：

```text
Q3 / STRICT
```

不得为了保持 FAST 路径而忽略 interface risk。

---

# 29. Interface Impact

现有 Impact 分析应增加：

```text
public_interfaces
consumers
compatibility
```

例如：

```yaml
interfaces:

  - id: API-USER-GET

    type: http

    visibility: external

    consumers:
      - web-client
      - mobile-client

    change:
      compatible: true

    affected_contracts:
      - openapi.yaml
```

---

# 30. Interface Change Decision

如果存在多个合法 API 设计：

```text
/api/users/{id}

/api/user?id=...
```

Agent 应：

```text
分析 existing repository convention
 ↓
给出 Recommendation
 ↓
必要时让用户决定
 ↓
记录 Decision
```

因此：

```text
Interface-first
```

与：

```text
Decision Record
```

需要能够结合。

---

# 31. Breaking Change

如果检测到已知 public contract breaking change：

不得静默实现。

必须至少：

```text
report breaking change
 ↓
identify consumers
 ↓
propose migration strategy
 ↓
request user decision when necessary
```

并记录：

```text
Decision
```

---

# 32. Interface Review

Q2/Q3 Review 必须增加 Interface Review。

Reviewer 检查：

```text
Is this actually a public/stable boundary?

Was the contract defined before implementation?

Does API expose implementation details?

Are public and persistence models unnecessarily coupled?

Are error semantics stable?

Is dependency direction correct?

Is compatibility understood?

Are breaking changes explicitly authorized?

Are interface-level tests present?

Is unnecessary abstraction introduced?
```

最后一项非常重要。

Interface-first 不能演变为：

```text
interface explosion
```

---

# 33. Interface Finding

建议新增 Finding category：

```text
INTERFACE
```

例如：

```yaml
id: FND-027-05

category: INTERFACE

severity: HIGH

title: Public API exposes persistence entity

status: OPEN

evidence:
  - src/api/user.py
  - src/db/models/user.py
```

可以继续复用现有 Finding 生命周期。

---

# 34. Interface Gate

Gate 不负责通过静态分析判断所有架构质量。

Gate 应验证可确定条件。

例如：

对于声明存在 external interface change 的任务：

必须存在：

```text
interface impact
contract evidence
compatibility classification
interface verification evidence
```

缺失则 block。

建议 blocker：

```text
INTERFACE_CONTRACT_MISSING
INTERFACE_COMPATIBILITY_UNDECLARED
INTERFACE_VERIFICATION_MISSING
INTERFACE_BREAKING_CHANGE_UNAPPROVED
```

---

# 35. Interface Test

新增接口时测试 SHOULD 优先验证 contract，而不是 implementation detail。

例如：

HTTP：

```text
request
response
status
validation
error
compatibility
```

Service interface：

```text
behavior contract
```

Event：

```text
schema
required fields
consumer compatibility
```

禁止只测试：

```text
private helper 被调用几次
```

然后把它称为 Interface Test。

---

# 36. 与 Test Plan Gate 集成

当 task impact 包含：

```text
public_interface = true
```

Test Plan SHOULD 包含：

```text
contract tests
compatibility tests
error contract tests
```

如属于 breaking change，还应包含：

```text
migration / consumer validation
```

---

# 37. 与 Diagnosability 集成

External Interface 必须沿用 diagnosability 原则。

至少应考虑：

```text
operation identity
failure context
dependency failure
trace/correlation context
```

不得为了 Interface-first 再创建第二套 logging contract。

---

# 38. 与 Minimal Implementation 集成

Minimal Implementation Review 必须检查：

```text
是不是为了“面向接口编程”创建了不必要抽象？
```

例如：

```text
只有一个 private helper
未来没有替换边界
没有 consumer contract
```

却创建：

```text
Interface
AbstractFactory
FactoryImpl
DefaultProvider
```

应当被 Complexity / Minimal Implementation Review 识别。

---

# 39. 推荐的完整工作流

Q2/Q3：

```text
CREATED
   ↓
CLASSIFIED
   ↓
identify ambiguity
   ↓
Decision Proposal
   ↓
User Decision
   ↓
Decision Record
   ↓
PLANNED
   ↓
Task Contract
   ↓
Interface Contract
   ↓
Minimal Implementation Check
   ↓
IMPLEMENTING
   ↓
VERIFYING
   ↓
Interface / Contract Tests
   ↓
Complexity Review
   ↓
Interface Review
   ↓
Adversarial Review
   ↓
GATING
   ↓
DONE
```

注意：

Decision 不应该机械成为新的 state。

否则会造成：

```text
DECIDING
DECISION_PENDING
DECISION_ACCEPTED
```

等大量状态机膨胀。

Decision 应作为：

```text
task-associated persisted object
```

而不是主状态。

---

# 40. FAST / Q1 行为

Q1 不要求完整 Decision Ceremony。

如果存在简单选择：

```text
遵循已有 convention
```

即可。

但是如果发现：

```text
public interface change
```

必须重新评估风险。

例如：

```text
Q1
 ↓
发现修改 public API
 ↓
risk escalation
 ↓
Q2
```

不得继续 FAST 并绕过 contract。

---

# 41. CLI Status

`harness status` 建议增加：

```text
Decisions:
  accepted: 3
  proposed: 1
  superseded: 1

Pending decision:
  DEC-004 API pagination strategy

Interfaces:
  public changes: 1
  compatibility: compatible
```

保持简洁。

不要输出所有 Decision 详情。

---

# 42. Gate Preflight

现有 Gate preflight 应提示：

```text
Missing decision:
DEC-004 is still PROPOSED

Missing interface evidence:
API-USER-GET has no contract verification

Recommended command:
...
```

保持 v0.2.7 当前：

```text
Gate 之前提前暴露缺失项
```

的设计方向。

---

# 43. Acceptance Criteria

## AC-01

当 Agent 需要用户进行重要工程选择时：

必须：

```text
提供选项
+ Recommendation
+ Recommendation Reason
```

---

## AC-02

Recommendation 必须能够引用当前 repository / task / contract / decision 中的已知事实。

不得只输出主观偏好。

---

## AC-03

用户接受 Recommendation 后必须生成持久化 Decision Record。

---

## AC-04

新 Session 可以通过 Harness state 恢复已 ACCEPTED Decision，而不依赖聊天记录。

---

## AC-05

后续 Agent 不得静默违反 ACCEPTED Decision。

---

## AC-06

用户覆盖 Recommendation 时必须保存真实 selected option。

---

## AC-07

Decision 修改必须通过 supersede 保留历史。

---

## AC-08

新增 external/public interface 时，必须存在明确 interface contract。

---

## AC-09

External interface change 必须完成 compatibility classification。

---

## AC-10

已知 breaking change 不得在无明确授权情况下进入 DONE。

---

## AC-11

Public interface 的测试必须验证外部 contract，而不能只验证 implementation detail。

---

## AC-12

Interface-first 不得要求所有 class/function 强制创建接口。

---

## AC-13

Q1 任务发现 public contract change 后必须重新评估风险，并在需要时升级 Q2/Q3。

---

## AC-14

Gate 可以确定性检测：

```text
unresolved decision
invalid decision reference
missing interface contract
missing compatibility declaration
missing interface verification
unapproved known breaking change
```

---

## AC-15

旧项目没有：

```text
.harness/decisions/
```

时仍然可以正常运行。

升级不得破坏现有 v0.2.7 task。

---

# 44. 必须增加的测试

至少覆盖：

```text
Decision schema validation
Decision propose
Decision accept recommendation
Decision user override
Decision reject
Decision supersede
invalid supersede
pending Decision preflight
Decision session resume
Decision conflict
legacy project compatibility

public interface classification
Q1 → Q2 interface escalation
interface contract missing
compatibility missing
compatible change
breaking change without approval
breaking change with approval
interface evidence missing
interface evidence fresh
interface Finding lifecycle
```

同时增加 Skill-level scenario tests：

```text
Agent asks choice without recommendation → FAIL

Agent recommends without reason → FAIL

Agent invents repository fact → FAIL

User accepts → Decision persisted

New session → Decision reused

Agent tries to violate decision → conflict surfaced

Public API requested → contract before implementation

Private helper added → no forced interface ceremony
```

---

# 45. 推荐目录调整

建议：

```text
src/harness/
├── decision.py
├── interface_contract.py
├── schemas/
│   ├── decision.schema.json
│   └── interface-contract.schema.json
├── templates/
└── ...
```

项目运行态：

```text
.harness/
├── current-task.yaml
├── requirements.yaml
├── invariants.yaml
├── impact.yaml
├── gate.yaml
├── decisions/
│   └── DEC-*.yaml
├── interface-contracts/
│   └── INT-*.yaml
├── findings/
└── evidence/
```

如果实现评估后发现单独的：

```text
interface-contracts/
```

过重，也允许把 interface declaration 放入 task contract / impact。

但必须保证：

```text
schema 可验证
对象可引用
Gate 可确定性检查
```

不得只写在 Markdown 中。

---

# 46. 实施优先级

建议拆成：

```text
P0
Decision persistence
Recommendation Skill rule
Decision resume
Decision conflict
Public interface identification
Compatibility declaration

P1
Decision CLI
Interface Contract schema
Gate integration
Risk escalation
Interface Review

P2
Status improvements
Decision summary
automatic compatibility tooling
OpenAPI/protobuf diff adapters
```

本版本至少完成 P0 + P1。

---

# 47. 设计约束

实现过程中必须保持：

```text
Fail Closed
```

但只针对 Harness 已经知道的事实。

例如 Harness 已知：

```text
breaking = true
approved = false
```

可以 block。

但如果 Harness 不知道某接口是否 breaking：

不得伪装已经证明：

```text
compatible = true
```

应该要求明确分类或证据。

同时保持：

```text
Model judges semantics
Harness validates persisted facts
Tests verify behavior
Gate validates evidence
Human owns consequential decisions
```

---

# 48. 最终设计原则

新增功能后 Engineering Harness 应形成以下闭环：

```text
              Requirement
                   │
                   ▼
              Known Facts
                   │
                   ▼
             Need Decision?
              │         │
             No        Yes
              │         │
              │         ▼
              │    Options
              │         │
              │    Recommendation
              │         │
              │       User
              │         │
              │    Decision Record
              │         │
              └────┬────┘
                   ▼
              Task Contract
                   │
                   ▼
          Public Interface?
              │         │
             No        Yes
              │         │
              │    Interface Contract
              │         │
              │    Compatibility
              │         │
              └────┬────┘
                   ▼
             Implementation
                   │
                   ▼
              Verification
                   │
                   ▼
           Review + Findings
                   │
                   ▼
                 Gate
                   │
                   ▼
                 DONE
```

核心原则：

> **AI 不应该在需要用户判断时只把问题抛给用户，而应该基于当前事实给出有依据的推荐。**

同时：

> **用户做出的决定不能只存在于聊天记录，而必须成为后续任务可以读取、验证和遵守的工程事实。**

以及：

> **对外发布的接口不是实现的副产品，而是实现需要遵守的契约。**

最终 Engineering Harness 的工程闭环从：

```text
Requirement
→ Implementation
→ Verification
→ Evidence
→ Done
```

进一步演进为：

```text
Requirement
→ Decision
→ Contract
→ Interface
→ Implementation
→ Verification
→ Evidence
→ Review
→ Gate
→ Done
```
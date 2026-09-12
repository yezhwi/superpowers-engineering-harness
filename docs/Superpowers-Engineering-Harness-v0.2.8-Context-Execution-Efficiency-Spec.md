# Superpowers Engineering Harness v0.2.8 开发规格

> 版本：v0.2.8  
> 状态：Development Specification  
> 主题：Context & Execution Efficiency  
> 目标：在不降低 Control Fidelity、任务正确性和工程 Gate 强度的前提下，减少 AI Coding 中无效 Context、重复 Tool Calls、重复搜索和重复执行。  
> 适用范围：Engineering Harness 控制面；不要求修改业务项目代码。  
> 基线版本：v0.2.7 / commit `239dce28`  
>
> **实现以实施契约为准：** [`Superpowers-Engineering-Harness-v0.2.8-Implementation-Contract.md`](./Superpowers-Engineering-Harness-v0.2.8-Implementation-Contract.md)。本文保留愿景与长期设计；与契约冲突时，v0.2.8 实现和发版门槛以契约为准。

---

## 1. 背景

v0.2.7 已经具备以下基础能力：

- Q0/Q1/Q2/Q3 风险分层；
- FAST / STANDARD / STRICT 工作流；
- test/build/retry execution budget；
- evidence reuse；
- benchmark corpus；
- baseline / adaptive correctness comparison；
- tool calls / token estimate / elapsed time 等效率指标结构；
- telemetry 基础结构。

这些能力已经证明 Harness 可以通过风险自适应方式减少一部分无意义执行成本。

但当前“节省 token”仍然存在几个根本缺口：

1. benchmark 具备比较逻辑，但缺少真实运行期 token / agent tool calls / search rounds 的采集；
2. Harness 尚未对 Agent 上下文进行统一控制；
3. Agent 可能重复读取相同任务状态、requirements、findings、evidence、代码和测试；
4. Context 压缩如果处理不当，会造成 requirement、invariant、decision、finding、scope 等控制语义丢失；
5. 即使压缩本身无损，也可能因为错误的 relevance selection，把关键事实完全排除在 Context 外；
6. 当前缺少“什么时候必须扩大上下文”的确定性策略；
7. 缺少能够证明“Compact Context 没有损害 correctness”的 Benchmark；
8. 当前优化指标偏向 total token，而无法识别 duplicate reads、repeated search 等真正可避免成本。

因此 v0.2.8 不应继续通过减少 Gate、减少 Review、减少 Verification 来主要降低 token，而应建设 Context Control 和 Execution Efficiency 控制面。

---

# 2. 核心目标

v0.2.8 必须实现：

```text
Minimize Context + Execution Cost

subject to:

Control Fidelity = 100%
Correctness >= Baseline
```

验收顺序必须固定为：

```text
Context Integrity
      │
      │ 必须通过
      ▼
Correctness
      │
      │ >= Baseline
      ▼
Efficiency
 ┌────┼────┐
 ▼    ▼    ▼
Token Tool Time
 ↓    ↓    ↓
显著降低
```

禁止出现：

```text
token ↓
correctness ↓
```

或：

```text
token ↓
但遗漏 requirement / invariant / decision / finding
```

却被视为优化成功。

---

# 3. 非目标

v0.2.8 不包含：

- 新的业务质量 Gate；
- 删除 Review / Evidence / Test Plan / Diagnosability 等既有工程 Gate；
- 通过减少安全检查换取 token；
- 统一设置固定 token hard limit；
- embedding / vector DB / semantic cache；
- 依赖 LLM 生成式摘要作为 authoritative context；
- 为单一 Agent Runtime 或单一模型供应商绑定实现；
- 直接用 tokenizer 估算替代宿主真实 usage。

---

# 4. 设计原则

## 4.1 Correctness First

任何 Efficiency 优化都必须满足：

```text
correctness(adaptive) >= correctness(baseline)
```

一旦 correctness regression：

```text
Efficiency result = FAIL
```

无论 token 降低多少。

## 4.2 Control Context 必须无损

以下内容属于 **Lossless Control Core**：

- task id；
- task state；
- risk class；
- workflow profile；
- active MUST requirements；
- active invariants；
- accepted decisions；
- open / blocking findings；
- blockers；
- owned paths；
- protected user paths；
- authorization constraints；
- security constraints；
- contract / data / deployment 等 cross-cutting constraints；
- evidence freshness；
- Gate blocking status。

这些信息禁止由 LLM 摘要。允许压缩的是表示形式，不允许改变控制语义。

## 4.3 Context Compression 必须是 Deterministic Projection

`harness context` 必须由 Harness 根据 authoritative state 生成。

禁止：

```text
raw harness state
    ↓
LLM summary
    ↓
Agent context
```

必须采用：

```text
authoritative state
    ↓
deterministic projection
    ↓
compact context
```

## 4.4 Lossless Reference + Lossy Presentation

代码、日志、测试输出等大对象允许压缩展示，但必须保留：

- source reference；
- hash；
- source version；
- raw evidence reference；
- expand path。

即：

```text
Storage = Lossless
Presentation = May Be Compact
```

## 4.5 Authoritative State != Agent Context

`.harness/` 中的原始状态永远是 authoritative source。`harness context` 只是 derived view，任何 Context 都不得成为新的事实来源。

## 4.6 Omission 必须显式

被筛选掉的信息禁止静默消失，必须记录：

```yaml
omitted:
  - id:
    reason:
    ref:
```

## 4.7 Risk 是所有 Efficiency Policy 的上游输入

统一采用：

```text
Risk
 ├─ Workflow Policy
 ├─ Context Policy
 └─ Execution Budget
```

禁止形成互相独立的三套策略。

---

# 5. 总体架构

```text
                    Task
                     │
              Risk Classifier
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
    Workflow      Context      Execution
     Policy        Policy       Budget
        │            │            │
   FAST/STANDARD  MINIMAL/      Search/
      /STRICT     LOCAL/        Test/
                  BOUNDED/      Build/
                  EXPANDED      Retry
        │            │            │
        └────────────┼────────────┘
                     ▼
               Execution Plan
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
     Search        Evidence       Review
     Budget         Reuse         Scope
       │             │             │
       └─────────────┼─────────────┘
                     ▼
               Context Engine
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   Control Core   Working Set   References
        │            │            │
        └────────────┼────────────┘
                     ▼
             Context Integrity Gate
                     │
                     ▼
                  Agent
                     │
                     ▼
                 Telemetry
                     │
      ┌──────────────┼──────────────┐
      ▼              ▼              ▼
    Tokens       Tool Calls      Search
      │              │              │
      └──────────────┼──────────────┘
                     ▼
                  Benchmark
                     │
        Context → Correctness → Efficiency
```

---

# 6. P0 功能范围

v0.2.8 必须完成以下 P0。

## P0-1 Benchmark Runtime Metrics

### 目标

使现有 Benchmark 从：

```text
Corpus + Comparator
```

升级为：

```text
Corpus
+ Runtime Metrics Contract
+ Artifact
+ Comparator
```

### 必须采集

```yaml
agent:
  tool_calls:
  search_rounds:
  input_tokens:
  output_tokens:
  total_tokens:
```

如宿主只能提供 total token：

```yaml
agent:
  total_tokens:
  token_source: runtime
```

允许 input/output 为 null。

### 原则

Harness 不负责绑定某一个 tokenizer。宿主可通过统一接口上报 usage。

推荐数据契约：

```yaml
usage:
  provider:
  model:
  input_tokens:
  output_tokens:
  total_tokens:
  source:
    enum:
      - runtime
      - provider
      - estimated
```

`source=estimated` 时 Benchmark 必须明确标记结果可信级别。

## P0-2 Lossless Control Core

新增统一的 Control Core schema。

建议：

```yaml
control:
  task:
    id:
    state:
    risk:
    profile:

  requirements:
    - id:
      status:
      mandatory:

  invariants:
    - id:
      status:

  decisions:
    - id:
      status:
      choice:

  findings:
    - id:
      severity:
      status:
      affected_requirements:

  blockers:
    - id:
      type:

  scope:
    owned_paths:
    protected_user_paths:

  constraints:
    security:
    authorization:
    contract:
    data:
    deployment:
```

### 约束

Control Core：

- 禁止 LLM 摘要；
- 禁止 semantic compression；
- 禁止丢 ID；
- 禁止把枚举值转成自然语言近义表达；
- 禁止裁剪 open finding；
- 禁止裁剪 active invariant；
- 禁止裁剪 blocker；
- 禁止裁剪 protected_user_paths。

## P0-3 `harness context`

新增：

```bash
harness context
```

推荐子模式：

```bash
harness context --compact
harness context --full
harness context --json
```

其中：

- `--compact`：默认 Agent Context；
- `--full`：完整 derived context；
- `--json`：机器可读。

---

# 7. Context 三层结构

## Layer 0 — Control Core

必须无损。

## Layer 1 — Working Context

允许 deterministic selection。

建议包含：

```yaml
working:
  goal:
  changed_files:
  relevant_requirements:
  relevant_tests:
  relevant_findings:
  verification_summary:
  next_action:
  context_hints:
    must_read:
    read_if_needed:
```

## Layer 2 — Expandable References

```yaml
references:
  requirements:
    ref:
    sha256:

  evidence:
    ref:
    sha256:

  files:
    - path:
      sha256:

  decisions:
    ref:
    sha256:
```

---

# 8. Context Manifest

每次 Context 生成必须输出 Manifest。

例如：

```yaml
manifest:
  sources:
    current_task:
      loaded: true
      hash:

    requirements:
      loaded: true
      total: 7
      included: 3

    invariants:
      loaded: true
      total: 4
      included: 4

    decisions:
      loaded: true
      accepted_total: 2
      included: 2

    findings:
      loaded: true
      open_total: 1
      included: 1

    evidence:
      loaded: true
      total: 9
      included: 3
```

Manifest 的目的：Agent 必须知道当前 Context 是完整集还是 working subset。

---

# 9. Mandatory Global Context

必须专门防止 Selection False Negative。

以下内容不允许因为“与当前文件看起来不相关”而过滤：

```text
active invariants
accepted cross-cutting decisions
protected_user_paths
security constraints
authorization constraints
unresolved blockers
cross-cutting requirements
contract constraints
```

最终 Context 必须遵循：

```text
Context
=
Lossless Global Core
+
Relevant Working Set
+
Expandable References
```

---

# 10. Context Integrity Gate

新增：

```text
Context Integrity Gate
```

必须在 Context 被 Agent 使用前执行。

## 10.1 Context Fidelity 定义

Context Fidelity 由四部分组成：

```text
Completeness
Accuracy
Freshness
Traceability
```

## 10.2 Context Integrity Invariants

至少实现：

```text
CI-01 所有 active MUST requirements 必须存在或明确 reference
CI-02 所有 active invariants 必须完整存在
CI-03 所有 OPEN/BLOCKING findings 必须完整存在
CI-04 所有 ACCEPTED decisions 必须完整存在
CI-05 scope / protected paths 必须无损
CI-06 blockers 必须无损
CI-07 derived status 必须与 authoritative state 一致
CI-08 所有 references 必须可解析
CI-09 source hash 必须 fresh
CI-10 omitted 项必须包含 reason + reference
CI-11 context schema 必须合法
CI-12 Context risk/profile 必须与 task risk/profile 一致
```

校验失败：

```text
CONTEXT_INCOMPLETE
CONTEXT_INACCURATE
CONTEXT_STALE
CONTEXT_REFERENCE_BROKEN
```

必须 fail-closed。

---

# 11. Context Freshness

Context 必须记录：

```yaml
generated_from:
  task_hash:
  requirements_hash:
  invariants_hash:
  findings_hash:
  decisions_hash:
  evidence_hash:
  workspace_hash:
  head:

context_hash:
```

以下任一事件发生，旧 Context 自动 stale：

- requirements 修改；
- invariant 修改；
- decision accepted / revoked；
- finding opened / reopened / resolved；
- evidence freshness 变化；
- workspace 变化；
- HEAD 变化；
- risk 变化；
- task state 变化；
- scope 变化。

---

# 12. Omitted 信息

被筛选的信息必须显式记录。

例如：

```yaml
omitted:
  requirements:
    - id: REQ-027-06
      reason: unrelated_to_current_scope
      ref: ".harness/requirements.yaml#REQ-027-06"
```

禁止信息未写入 Context 且无任何记录。

---

# 13. Risk-Aware Context Policy

必须把 Q0/Q1/Q2/Q3 映射到 Context Policy。

建议：

| Risk | Workflow | Context | Search |
|---|---|---|---|
| Q0 | minimal | MINIMAL | 0~1 |
| Q1 | FAST | LOCAL | ≤2 |
| Q2 | STANDARD | BOUNDED | soft limit |
| Q3 | STRICT | EXPANDED | observable |

## 13.1 MINIMAL

适用于 Q0。包含 task、necessary global core 和必要说明信息。

## 13.2 LOCAL

适用于 Q1。默认最多包含：

```text
task
+ global control core
+ owned files
+ directly related requirements
+ directly related tests
+ open findings
```

禁止默认：

- full repo scan；
- full docs load；
- full test suite read；
- broad dependency exploration。

## 13.3 BOUNDED

适用于 Q2。允许 limited dependency exploration、contract analysis、affected module expansion、broader tests。

## 13.4 EXPANDED

适用于 Q3。允许跨模块、跨 contract 的完整探索，但仍记录 search rounds、file reads、context expansions、token cost。严格模式不等于无限制浪费。

---

# 14. Progressive Context Disclosure

默认流程：

```text
Level 0 Task Summary
      ↓
Level 1 Control Core + Owned Scope
      ↓
Level 2 Relevant Code / Tests
      ↓
Level 3 Dependencies
      ↓
Level 4 Broader Repository
```

禁止任务开始时默认加载 Level 4。

---

# 15. Automatic Context Escalation

必须定义 deterministic trigger，至少包括：

1. target symbol 无法解析；
2. requirement 与 implementation 无法建立映射；
3. test failure 原因不在 working set；
4. 发现跨模块 dependency；
5. API/schema/permission/config 变化；
6. finding 指向当前 scope 外；
7. accepted decision 指向 scope 外依赖；
8. Agent 报告 `insufficient_context`；
9. Context Integrity 无法证明；
10. risk classifier 升级。

Escalation：

```text
MINIMAL
  ↓
LOCAL
  ↓
BOUNDED
  ↓
EXPANDED
```

必须记录：

```yaml
context_expansion:
  from:
  to:
  trigger:
  reason:
```

---

# 16. Search / Context Budget

在现有 test/build/retry 基础上扩展：

```yaml
budget:
  test_runs:
  build_runs:
  retry_runs:
  search_rounds:
  file_reads:
  context_expansions:
```

原则：

- 预算是 soft budget；
- correctness 优先；
- 超预算允许继续；
- 超预算必须记录 reason / evidence / hypothesis。

禁止达到 token 数量后硬 BLOCK。

---

# 17. File Read Reuse

P1 实现 deterministic file read cache。

建议：

```yaml
context_cache:
  files:
    src/foo.py:
      sha256:
      last_read_state:
```

当文件未变化，避免 full file read，优先提供 `UNCHANGED` 或 `diff only`。禁止把缓存内容作为 authoritative source。

---

# 18. Evidence Digest

P1 将 evidence 默认输出转换为 deterministic digest。

例如 pytest：

```yaml
result:
  status: failed

  counts:
    passed: 27
    failed: 1

  failures:
    - test:
      location:
      message:

  raw:
    ref:
    sha256:
```

模型默认读取 digest，需要时再 expand raw evidence。

---

# 19. Review Context

P1 新增 review-specific Context。

建议：

```bash
harness review-context
```

Reviewer 默认只获取：

```text
task contract
+ accepted decisions
+ changed files
+ diff
+ affected requirements
+ active invariants
+ evidence digest
+ open findings
```

原则：

```text
Reviewer Context != Implementer Context
```

禁止 reviewer 默认重新探索整个仓库。

---

# 20. Finding-Scoped Re-Review

Finding 修复后默认使用：

```text
Finding
+
Fix Diff
+
RED/GREEN Evidence
+
Affected Requirement
```

只有以下情况触发 full review：

- scope changed；
- contract changed；
- risk escalated；
- new cross-cutting dependency；
- new finding outside original review scope。

---

# 21. Context Evidence

Context 本身必须成为一种 Evidence。

建议：

```yaml
context_evidence:
  id:
  task_id:
  context_hash:
  generated_at:
  policy:

  source:
    head:
    workspace_hash:

  integrity:
    completeness:
    accuracy:
    freshness:
    traceability:

  included:
    requirements:
    invariants:
    decisions:
    findings:

  omitted:

  expansions:
```

价值：未来可以回答“Agent 当时到底看到了什么？”。

---

# 22. Failure Attribution

v0.2.8 应允许区分：

```text
Implementation Failure
Agent 看到了正确信息但实现错误

Context Failure
Harness 未提供必要信息

Selection Failure
必要信息被错误过滤

Evidence Failure
验证没有捕获错误

Review Failure
证据存在但 review 未发现

Freshness Failure
Agent 使用了 stale context
```

Context Evidence 必须支持事后诊断这些问题。

---

# 23. Telemetry 扩展

当前 telemetry 应升级为：

```yaml
tokens:
  input:
  output:
  total:
  source:

agent:
  tool_calls:
  search_rounds:
  file_reads:
  context_expansions:

context:
  policy:
  generated_count:
  cache_hits:
  stale_count:

execution:
  test_runs:
  build_runs:
  retry_runs:
```

---

# 24. Token Attribution

P1 建议增加：

```yaml
tokens:
  total:

  context:
    control:
    source:
    tests:
    evidence:
    search:

  avoidable:
    duplicate_reads:
    repeated_search:
    repeated_evidence:
    redundant_review:
```

新增指标：

```text
Avoidable Token Ratio
=
avoidable_tokens / total_tokens
```

目标不是单纯 total token 最低，而是优先降低可避免成本。

---

# 25. Benchmark 设计

现有 Benchmark 必须升级成三个维度：

```text
Context Integrity
Correctness
Efficiency
```

## 25.1 Context Fidelity Benchmark

必须增加 adversarial cases，至少覆盖：

- 低优先级但 mandatory requirement；
- active invariant 位于非目标模块；
- accepted cross-cutting decision；
- protected_user_path；
- stale evidence；
- reopened finding；
- scope 外 blocker；
- API contract；
- authorization constraint；
- dependency hidden outside target file。

验收：

```text
Control Fact Recall = 100%
Control Fact Accuracy = 100%
Reference Resolution = 100%
Freshness Detection = 100%
```

## 25.2 Correctness Benchmark

只有：

```text
correctness(adaptive) >= correctness(baseline)
```

Efficiency 才允许 PASS。

## 25.3 Efficiency Benchmark

至少比较：

```text
total_tokens
tool_calls
search_rounds
file_reads
context_expansions
elapsed_seconds
```

---

# 26. Benchmark 指标

除 average 外，后续至少支持：

```text
median tokens
P90 tokens
success rate
tokens_per_success
tool_calls_per_success
elapsed_per_success
```

核心指标：

```text
Tokens Per Success
=
Total Tokens / Successful Tasks
```

禁止只看 average token per task。

---

# 27. Benchmark 多次运行

同一个 case 支持 `N runs`。v0.2.8 至少允许 `N >= 3`，推荐输出：

```text
median
P90
success rate
```

用于降低 Agent 随机性造成的误判。

---

# 28. Benchmark Corpus 分层

为避免 Benchmark Overfitting：

```text
benchmark/
├── calibration/
├── holdout/
└── adversarial/
```

### calibration

开发期可见。

### holdout

release validation。

### adversarial

专门测试 Context / Selection / Freshness 边界。

---

# 29. Acceptance Criteria

## AC-028-01 Runtime Metrics

Benchmark Artifact 能记录真实或明确标记估算来源的 token、tool calls、search rounds。

## AC-028-02 Lossless Control Core

所有 mandatory control facts：

```text
recall = 100%
accuracy = 100%
```

## AC-028-03 Context Integrity

所有 CI-01 ~ CI-12 自动校验。任一失败必须 fail-closed。

## AC-028-04 Context Freshness

authoritative state 修改后，旧 Context 必须自动 stale。

## AC-028-05 Selection Safety

Mandatory Global Context 不允许被 relevance filter 删除。

## AC-028-06 Progressive Disclosure

Q1 默认不得进入 broad repository context，除非发生合法 escalation。

## AC-028-07 Automatic Escalation

全部定义的 escalation trigger 都必须具备测试覆盖。

## AC-028-08 Context Evidence

每次 Compact Context 必须可生成 Context Evidence。

## AC-028-09 Correctness Preservation

```text
adaptive correctness >= baseline correctness
```

## AC-028-10 Efficiency Improvement

在 correctness 和 integrity 全部通过后，Q1 corpus 必须至少满足：

```text
median total_tokens(adaptive)
<
median total_tokens(baseline)
```

以及至少一个：

```text
tool_calls ↓
search_rounds ↓
file_reads ↓
elapsed_seconds ↓
```

## AC-028-11 Tokens Per Success

必须报告 `tokens_per_success`，并禁止用更低成功率换取表面 token 降低。

## AC-028-12 Omission Traceability

所有 omitted item 必须有 `reason + reference`。

---

# 30. CLI 建议

必须：

```bash
harness context
harness context --compact
harness context --full
harness context --json
```

建议：

```bash
harness context validate
harness context explain
harness context expand <ref>
```

P1：

```bash
harness review-context
```

---

# 31. `harness context explain`

建议提供：

```bash
harness context explain
```

返回：

```yaml
policy: LOCAL

included:
  - REQ-01
    reason: affects-owned-path

omitted:
  - REQ-06
    reason: unrelated_to_scope

global:
  - INV-02
    reason: mandatory-global-core

expansions:
  - from: LOCAL
    to: BOUNDED
    trigger: TEST_FAILURE_OUTSIDE_SCOPE
```

这可以显著提高 Context Selection 的可诊断性。

---

# 32. 推荐目录

可考虑：

```text
src/harness/
├── context/
│   ├── model.py
│   ├── builder.py
│   ├── selector.py
│   ├── integrity.py
│   ├── freshness.py
│   ├── policy.py
│   ├── escalation.py
│   └── evidence.py
│
├── benchmark.py
├── telemetry.py
├── budget.py
└── cli.py
```

具体结构允许根据现有项目架构调整。

原则：

- 面向接口编程；
- Context Builder 与 Selector 解耦；
- Selector 与 Risk Policy 解耦；
- Runtime Metrics Provider 使用接口；
- 不绑定单一 Agent Runtime。

---

# 33. 建议接口

例如：

```python
class ContextSource(Protocol):
    def load(self, task_id: str) -> AuthoritativeContext:
        ...


class ContextSelector(Protocol):
    def select(
        self,
        source: AuthoritativeContext,
        policy: ContextPolicy,
    ) -> ContextSelection:
        ...


class ContextIntegrityChecker(Protocol):
    def validate(
        self,
        source: AuthoritativeContext,
        context: AgentContext,
    ) -> ContextIntegrityResult:
        ...


class UsageProvider(Protocol):
    def get_usage(self) -> AgentUsage:
        ...
```

---

# 34. 测试要求

必须新增以下测试层级。

## 34.1 Unit Tests

覆盖：

- policy mapping；
- mandatory global selection；
- omitted manifest；
- context hash；
- stale detection；
- integrity checks；
- escalation trigger；
- token metrics validation；
- tokens_per_success。

## 34.2 Property / Invariant Tests

例如：

```text
所有 active invariant 永不允许从 Control Core 消失

所有 open finding 永不允许静默丢失

任何 authoritative hash 改变都必须使旧 Context stale
```

## 34.3 Integration Tests

模拟：

```text
task
→ context
→ code change
→ context stale
→ regenerate
→ evidence
→ review
```

## 34.4 Adversarial Tests

专门构造：

- hidden invariant；
- misleading scope；
- stale PASS evidence；
- reopened finding；
- cross-cutting decision；
- protected user file；
- out-of-scope failing test；
- risk escalation。

---

# 35. Benchmark 实施顺序

必须按以下顺序：

```text
Step 1
先补 Runtime Metrics

Step 2
建立 v0.2.7 baseline artifact

Step 3
实现 Context Engine

Step 4
跑 Context Fidelity Benchmark

Step 5
跑 Correctness Benchmark

Step 6
只有前两层通过后，再比较 Efficiency
```

禁止：

```text
先实现优化
→ 再临时设计 benchmark
```

---

# 36. 推荐开发阶段

## Phase 1 — Benchmark 可测

实现：

- runtime metrics contract；
- telemetry；
- artifact；
- correctness + efficiency comparator；
- baseline capture。

## Phase 2 — Context Safety

实现：

- Lossless Control Core；
- Context Manifest；
- Context Integrity Gate；
- Context Freshness；
- Mandatory Global Context；
- Context Evidence。

## Phase 3 — Context Efficiency

实现：

- `harness context --compact`；
- Risk-Aware Context；
- Progressive Disclosure；
- Automatic Escalation；
- omitted/reference；
- Context Explain。

## Phase 4 — Execution Efficiency

实现：

- search budget；
- file read reuse；
- evidence digest；
- review context；
- finding-scoped review。

## Phase 5 — Benchmark Validation

执行：

```text
Context Integrity
→ Correctness
→ Efficiency
```

生成 release benchmark report。

---

# 37. Failure Policy

所有 Context correctness 问题必须 fail-closed。

例如：

```text
CONTEXT_INCOMPLETE
CONTEXT_INACCURATE
CONTEXT_STALE
CONTEXT_REFERENCE_BROKEN
CONTEXT_POLICY_MISMATCH
```

Efficiency budget 超限不得 fail-closed。

例如：

```text
SEARCH_BUDGET_EXCEEDED
CONTEXT_EXPANSION_BUDGET_EXCEEDED
```

应要求：

```text
reason
evidence
hypothesis
```

后允许 override。

区别必须明确：

```text
Correctness Safety
→ fail closed

Efficiency Budget
→ soft guardrail
```

---

# 38. 兼容性要求

v0.2.8 必须：

- 保持 v0.2.7 task state 兼容；
- 保持现有 evidence 可读；
- 不要求旧 task 迁移后才能运行；
- 新 Context 能从旧 `.harness` state 生成；
- benchmark 新字段允许旧 artifact 缺失时标记 `INCONCLUSIVE`；
- 禁止把缺失 metrics 当作 0。

---

# 39. 文档要求

需要同步更新：

```text
README
SKILL.md
CLI help
benchmark docs
context architecture docs
migration notes
```

SKILL.md 必须明确：

```text
Agent 优先使用 harness context，
而不是逐个读取所有 .harness 文件。
```

但也必须明确：

```text
如果 Context Integrity 失败，
不得继续依赖 compact context。
```

---

# 40. 最终设计原则

v0.2.8 的目标不能表述为：

> 让 Agent 知道得更少。

必须表述为：

> 让 Agent 只获取当前决策所需的信息，并确保任何被省略的信息都可检测、可解释、可追溯、可恢复。

最终形成：

```text
State
+
Evidence
+
Gate
+
Context Control
+
Cost Observability
```

---

# 41. Done Definition

v0.2.8 只有在以下条件全部满足时才能 Done：

```text
1. Runtime token/tool/search metrics 可用
2. Baseline benchmark 已建立
3. Control Core 无损
4. Context Integrity 全部通过
5. Mandatory Global Context 无 selection false-negative
6. Context stale 可检测
7. Context Evidence 可追溯
8. Automatic Escalation 可工作
9. Adaptive correctness >= baseline
10. Context Fidelity = 100%
11. tokens_per_success 改善
12. 至少一个额外效率指标改善
13. adversarial corpus 无 regression
```

因此：

```text
Done
!=
“模型说节省了 token”
```

而必须是：

```text
Integrity Evidence
+
Correctness Evidence
+
Efficiency Evidence
=
Done
```

# Superpowers Engineering Harness v0.2.4 Test Plan Gate 实施需求文档

## 1. 文档目的

项目：

```text
https://github.com/yezhwi/superpowers-engineering-harness
```

目标版本：

```text
0.2.4
```

本版本新增：

```text
Test Plan Gate
+
Requirement / Invariant / Test / Evidence Traceability
```

目标不是：

```text
自动生成大量测试
```

而是：

> Harness 必须确保 AI 在实现功能之前明确“需要证明什么”，并在 Verification / Gate 阶段检查这些测试是否真正执行并产生有效 Evidence。

---

# 2. 核心原则

本版本必须遵守：

```text
Requirement
    ↓
Verification Strategy
    ↓
Test Case
    ↓
Executable Test
    ↓
Evidence
    ↓
Gate
```

以及：

```text
Invariant
    ↓
Verification Strategy
    ↓
Test Case
    ↓
Executable Test
    ↓
Evidence
    ↓
Gate
```

最终不能只证明：

```text
pytest passed
```

必须逐步具备：

```text
REQ-001
→ Test
→ Evidence
→ PASS
```

以及：

```text
INV-001
→ Test
→ Evidence
→ PASS
```

---

# 3. 非目标

本版本不要实现：

```text
AI 自动生成测试代码

Mutation Testing

Property-Based Testing Framework

测试覆盖率平台

复杂风险评分系统

测试结果数据库

CI SaaS 集成

LLM Judge

自动修改测试

自动修复失败测试
```

这些属于未来版本。

v0.2.4 只实现：

```text
测试设计约束
+
Traceability
+
Gate
```

---

# 4. 为什么需要 Test Plan Gate

当前 Harness 已经能够管理：

```text
Requirement
Invariant
Evidence
Review
Gate
Recovery
```

但存在一个缺口：

```text
Requirement
    ↓
Implementation
    ↓
Agent 自己决定写什么测试
```

可能导致：

```text
只测试 Happy Path

遗漏边界条件

遗漏 Critical Invariant

Bug Fix 没有 Regression Test

大量 Mock 但没有真实 Integration Verification

测试数量很多但没有覆盖核心 Requirement
```

因此需要增加：

```text
Test Plan Gate
```

---

# 5. Test Plan Gate 的位置

目标生命周期：

```text
SPECIFICATION
      ↓
PLANNED
      ↓
TEST PLAN
      ↓
IMPLEMENTING
      ↓
VERIFYING
      ↓
REVIEWING
      ↓
GATING
      ↓
CONVERGED
      ↓
DONE
```

注意：

本版本**不要求增加新的状态 `TEST_PLANNING`**。

为了避免破坏现有状态机：

```text
Test Plan
```

作为：

```text
PLANNED → IMPLEMENTING
```

之间的 Gate。

也就是说，STANDARD / STRICT Task 执行：

```bash
harness transition IMPLEMENTING
```

前必须验证 Test Plan。

Q1 / FAST 保持既有：

```text
CLASSIFIED → IMPLEMENTING
```

路径。本版本不向 FAST 引入 Test Plan Gate；FAST 仍由既有 RED/GREEN regression proof 与 Light Gate 约束。若未来要求 FAST 也在实现前设计测试，必须单独设计轻量入口，不能让它隐式绕过或复用 STANDARD / STRICT 的 `PLANNED` Gate。

---

# 6. 基本规则

## Rule 1

每一个 STANDARD / STRICT Task 中的：

```text
Requirement
```

必须声明：

```text
verification strategy
```

只要包含自动化 strategy，就必须至少声明一个 Test Case；不能以空 `cases` 通过计划 Gate。

---

## Rule 2

每一个：

```text
critical invariant
```

必须声明：

```text
verification strategy
+
至少一个 test case
```

---

## Rule 3

Bug Fix 类型 Requirement 必须包含：

```text
regression test
```

---

## Rule 4

Test Plan 阶段不要求测试文件已经存在。

允许：

```yaml
cases:
  - id: TC-001
    type: happy_path
    strategy: unit
    description: 已支付订单可以正常取消
```

而暂时没有：

```yaml
tests:
```

因为此时：

```text
Implementation
```

可能尚未开始。

---

## Rule 5

进入 VERIFYING 后：

计划中的自动化测试必须能够绑定：

```text
Executable Test
```

例如：

```text
tests/order/test_cancel.py::test_cancel_paid_order
```

---

# 7. Verification Strategy

新增受控集合：

```text
unit

integration

e2e

regression

concurrency

security

contract

manual
```

本版本不要允许任意字符串。

---

# 8. Test Case Type

新增：

```text
happy_path

negative

boundary

regression

invariant

concurrency

security

contract
```

同样使用 enum。

---

# 9. Requirement Schema 扩展

修改：

```text
src/harness/schemas/requirement.schema.json
```

根据当前实际 schema 结构进行最小扩展。

Requirement 推荐结构：

```yaml
requirements:

  - id: REQ-001

    statement: 已支付订单可以取消

    type: feature

    test_plan:

      strategies:
        - unit
        - integration

      cases:

        - id: TC-001
          type: happy_path
          strategy: unit
          description: 已支付订单取消成功

        - id: TC-002
          type: negative
          strategy: integration
          description: 未支付订单不能取消
```

---

# 10. Requirement Type

新增可选：

```text
type
```

受控集合：

```text
feature

bugfix

refactor

nonfunctional
```

默认：

```text
feature
```

为了 backward compatibility：

旧 Requirement 没有 `type` 时：

```text
视为 feature
```

不要因为旧文件缺少：

```text
type
```

直接导致 schema invalid。

---

# 11. Bug Fix Requirement

如果：

```yaml
type: bugfix
```

Test Plan Gate 必须要求：

```text
至少一个 regression case
```

例如：

```yaml
test_plan:

  strategies:
    - regression

  cases:

    - id: TC-101
      type: regression
      strategy: regression
      description: 并发取消不得重复退款
```

如果没有 regression：

```text
TEST_PLAN_REGRESSION_REQUIRED
```

并拒绝进入：

```text
IMPLEMENTING
```

---

# 12. Invariant Schema 扩展

修改：

```text
src/harness/schemas/invariant.schema.json
```

根据实际 schema 名称确认。

推荐：

```yaml
invariants:

  - id: INV-001

    statement: 同一个订单最多只能退款一次

    severity: critical

    test_plan:

      strategies:
        - integration
        - concurrency

      cases:

        - id: TC-201
          type: invariant
          strategy: integration
          description: 重复取消不得重复退款

        - id: TC-202
          type: concurrency
          strategy: concurrency
          description: 两个并发取消请求只能产生一次退款
```

---

# 13. Critical Invariant Rule

如果：

```yaml
severity: critical
```

必须满足：

```text
test_plan.strategies 非空
```

以及：

```text
test_plan.cases 至少一个
```

否则：

```text
TEST_PLAN_CRITICAL_INVARIANT_UNCOVERED
```

拒绝进入 IMPLEMENTING。

---

# 14. 普通 Invariant

当前 severity enum 为：

```text
critical
major
minor
```

本版本以此为准。

本版本可以只强制：

```text
critical
```

其他等级：

```text
推荐但不强制
```

不要一次性引入复杂 Risk Policy。

---

# 15. Test Case Schema

Test Case 至少包含：

```yaml
id: TC-001
type: happy_path
strategy: unit
description: 已支付订单可以正常取消
```

必须：

```text
id
type
strategy
description
```

`strategy` 必须属于父 Requirement / Invariant 的 `test_plan.strategies`。这样 Gate 才能判断每个计划中的自动化验证采用何种方式，避免一个 `unit + integration` Plan 只有无法归属的 Case。

---

# 16. Test Case ID

推荐：

```text
TC-001
TC-002
TC-003
```

Test Case ID 在整个 Task 的：

```text
Requirement + Invariant
```

范围内必须全局唯一。Evidence、Gate blocker、Traceability Summary 都以 `TC-*` 作为关联键；局部唯一会使关联产生歧义。

---

# 17. Executable Test Binding

Implementation 完成后，需要允许 Test Case 绑定实际测试。

例如：

```yaml
- id: TC-001

  type: happy_path

  strategy: unit

  description: 已支付订单取消成功

  tests:

    - tests/order/test_cancel.py::test_cancel_paid_order
```

也允许一个 Test Case 对应多个测试：

```yaml
tests:

  - tests/order/test_cancel.py::test_cancel_paid_order

  - tests/order/test_cancel_api.py::test_cancel_paid_order_api
```

---

# 18. Test Plan 阶段与 Verification 阶段区别

这是本版本非常重要的设计。

## PLANNED

只要求：

```text
Test Case 已设计
```

不要求：

```text
测试文件已经存在
```

所以：

```yaml
cases:
  - id: TC-001
    type: happy_path
    strategy: unit
    description: 已支付订单可以取消
```

合法。

---

## VERIFYING

必须逐步变成：

```yaml
cases:
  - id: TC-001

    type: happy_path

    description: 已支付订单可以取消

    tests:
      - tests/order/test_cancel.py::test_cancel_paid_order
```

然后 Evidence 对应实际执行结果。

---

# 19. 新增 Test Plan Validator

建议新增：

```text
src/harness/test_plan.py
```

或者：

```text
src/harness/test_plan_gate.py
```

不要把全部逻辑塞入：

```text
controlplane.py
```

推荐 API：

```python
def validate_test_plan(
    requirements: dict,
    invariants: dict,
) -> list[TestPlanIssue]:
    ...
```

---

# 20. TestPlanIssue

推荐结构：

```python
@dataclass(frozen=True)
class TestPlanIssue:
    code: str
    message: str

    requirement_id: str | None = None
    invariant_id: str | None = None
    test_case_id: str | None = None
```

---

# 21. Test Plan Issue Codes

本版本至少：

```text
TEST_PLAN_REQUIREMENT_STRATEGY_MISSING

TEST_PLAN_CRITICAL_INVARIANT_UNCOVERED

TEST_PLAN_REGRESSION_REQUIRED

TEST_PLAN_AUTOMATED_CASE_REQUIRED

TEST_PLAN_CASE_DUPLICATE

TEST_PLAN_CASE_STRATEGY_MISMATCH

TEST_PLAN_INVALID_STRATEGY

TEST_PLAN_INVALID_CASE_TYPE
```

Schema 已经可以拦截的错误：

```text
INVALID_STRATEGY
INVALID_CASE_TYPE
```

不一定需要 Runtime 重复实现。

以当前项目 schema validation 架构为准。

---

# 22. PLANNED → IMPLEMENTING Gate

修改：

```text
src/harness/controlplane.py
```

在：

```text
PLANNED → IMPLEMENTING
```

前执行：

```python
issues = validate_test_plan(...)
```

如果：

```text
issues != []
```

则：

```text
拒绝 transition
```

保持：

```text
state = PLANNED
```

---

# 23. CLI 输出

例如：

```bash
harness transition IMPLEMENTING
```

失败时：

```text
TEST_PLAN_BLOCKED

REQ-001:
  TEST_PLAN_REQUIREMENT_STRATEGY_MISSING

INV-002:
  TEST_PLAN_CRITICAL_INVARIANT_UNCOVERED
```

exit code：

```text
非 0
```

必须 fail closed。

---

# 24. 不自动修改 Test Plan

Harness 只负责：

```text
validate
```

不要：

```text
自动补 strategy

自动生成 case

自动写测试代码
```

例如发现：

```text
REQ-001 missing verification strategy
```

只输出问题。

由 Agent 自己修改：

```text
requirements.yaml
```

---

# 25. Requirement → Test Traceability

本版本开始建立：

```text
Requirement
→ Test Case
→ Executable Test
```

例如：

```text
REQ-001
 ├─ TC-001
 │    └─ test_cancel_paid_order
 │
 └─ TC-002
      └─ test_cancel_unpaid_order
```

Invariant：

```text
INV-001
 ├─ TC-201
 │    └─ test_repeated_cancel
 │
 └─ TC-202
      └─ test_concurrent_cancel
```

---

# 26. Test → Evidence Traceability

不要在本版本重新设计整个 Evidence Model。

尽量复用现有：

```text
.harness/evidence/
```

机制。

`test_plan` 只描述准备怎么证明；现有 `Requirement.evidence` 与 `Invariant.verification` 继续只保存 Evidence 引用，绝不复用为 Test Plan 字段。

如果现有 evidence 可以记录：

```text
source
command
head
status
```

则在其基础上增加最小关联。

推荐 Evidence 支持：

```yaml
test_cases:

  - TC-001

  - TC-002
```

或者：

```yaml
covers:
  requirements:
    - REQ-001

  invariants:
    - INV-001

  test_cases:
    - TC-001
    - TC-201
```

本版本确定复用现有 Evidence 的 `covered_tests`：

```yaml
covered_tests:
  - tests/order/test_cancel.py::test_cancel_paid_order
```

自动化 Test Case 的 `tests` 中每个 node ID，必须被至少一份成功、fresh Evidence 的 `covered_tests` 覆盖。Evidence 收集器必须让此字段适用于所有自动化 strategy，不只 `unit_test`。

Gate 必须扫描 `.harness/evidence/*.json` 的全部记录；不得按 Evidence `type` 建索引后覆盖同类型多份记录。这样多个 unit/integration 执行记录都可为不同 Test Case 提供证明。

---

# 27. Verification Coverage

在：

```text
VERIFYING
```

或最终 Gate 阶段，需要能够判断：

```text
计划中的 Test Case
是否有 Executable Test
是否有 Evidence
```

本版本先实现最小规则：

对于自动化 strategy：

```text
unit
integration
e2e
regression
concurrency
security
contract
```

进入最终 Gate 前：

```text
自动化 Test Case
→ 至少一个 executable test binding
→ 每个 binding 被成功、fresh Evidence.covered_tests 覆盖
```

这里的 Evidence 证明“该命令已在当前 commit/workspace 成功运行，并声明覆盖 node ID”；Harness 不解析任意测试框架命令来独立证明 node ID 实际执行。

---

# 28. Manual Strategy

如果 Test Case：

```yaml
strategy: manual
```

允许没有：

```text
tests
```

混合自动化与 manual strategy 时，豁免只适用于 `strategy: manual` 的 Case；不得因父对象含 `manual` 而豁免自动化 Case。

但是仍然必须有：

```text
Evidence
```

例如：

```text
manual verification record
```

不要允许：

```text
manual
```

成为逃避验证的方式。

---

# 29. Final Gate 新增检查

当前 Quality Gate 已经检查：

```text
Requirement
Invariant
Evidence
Finding
Review
...
```

本版本增加：

```text
Test Plan Coverage
```

至少检查：

```text
Requirement Test Cases
→ executable binding

Critical Invariant Test Cases
→ executable binding

Bug Fix
→ regression test binding

Test Case
→ Evidence
```

---

# 30. 新增 Gate Blocker Code

推荐：

```text
TEST_PLAN_INCOMPLETE

TEST_BINDING_MISSING

TEST_EVIDENCE_MISSING
```

不要为每一种小错误创建几十个 blocker code。

Test Plan Validator 可以有详细 issue code。

Gate Blocker 保持较粗粒度。

---

# 31. Recovery Policy

这些 blocker 建议：

```text
TEST_PLAN_INCOMPLETE
→ IMPLEMENTING

TEST_BINDING_MISSING
→ IMPLEMENTING

TEST_EVIDENCE_MISSING
→ VERIFYING
```

原因：

```text
测试没有设计/实现
→ 需要修改实现资产
→ IMPLEMENTING
```

而：

```text
测试已经存在，只缺执行 Evidence
→ VERIFYING
```

---

# 32. 不要混淆 Test Plan 和 Evidence

必须区分：

```text
Test Plan
=
准备怎么证明
```

```text
Executable Test
=
用什么代码证明
```

```text
Evidence
=
已经证明过什么
```

即：

```text
Plan
 ↓
Executable Verification
 ↓
Evidence
```

三者不能合并。

---

# 33. Test Plan Review

REVIEWING 阶段可以检查测试质量。

但本版本不要增加复杂 AI Judge。

只增加文档/Skill 指令：

Reviewer 必须检查：

```text
是否只测试 Happy Path

是否遗漏与风险相称的 Negative / Bad Input Case

是否遗漏 Boundary / Corner Case

状态迁移、失败恢复、重复请求或并发场景是否被遗漏

Critical Invariant 是否真正被测试

Bug Fix 是否有 Regression Test

是否过度 Mock 导致关键集成行为没有验证

Test Case 是否真正对应 Requirement
```

---

# 34. Reviewer 可以返回 VERIFICATION_GAP

如果 Reviewer 发现：

```text
测试覆盖不足
```

继续使用现有：

```text
VERIFICATION_GAP
```

例如：

```text
TEST_COVERAGE_INSUFFICIENT
```

然后：

```text
REVIEWING
    ↓
VERIFYING
```

不要新增新的 Review Outcome。

---

# 35. Test Plan 与 TDD

本版本应该鼓励：

```text
Plan Test
   ↓
Write Failing Test
   ↓
Implement
   ↓
Pass Test
```

但不要强制所有项目必须严格 TDD。

Harness 强制的是：

```text
Test Design Before Implementation
```

不是：

```text
测试代码必须先于生产代码 commit
```

---

# 36. Backward Compatibility

这是重要要求。

现有项目可能已经有：

```text
requirements.yaml
invariants.yaml
```

但没有：

```text
verification
```

不能简单导致：

```text
harness status
```

无法运行。

建议：

旧 Task：

```text
可以读取
```

但是：

```text
PLANNED → IMPLEMENTING
```

时按照新 Test Plan Gate 要求补齐。

如果当前项目已有 schema version：

```text
优先使用 schema migration/version 机制
```

不要自行创造第二套版本系统。

---

# 37. 初始化模板更新

更新：

```text
harness init
```

生成的 Requirement 示例。

例如：

```yaml
requirements:

  - id: REQ-001

    statement: Replace with requirement

    type: feature

    test_plan:

      strategies:
        - unit

      cases:

        - id: TC-001
          type: happy_path
          strategy: unit
          description: Replace with expected behavior
```

---

# 38. Invariant 模板

例如：

```yaml
invariants:

  - id: INV-001

    statement: Replace with invariant

    severity: critical

    test_plan:

      strategies:
        - integration

      cases:

        - id: TC-101
          type: invariant
          strategy: integration
          description: Verify invariant always holds
```

---

# 39. Status 输出

建议增强：

```bash
harness status
```

显示：

```text
Test Plan

Requirements:
  3 / 3 planned

Critical Invariants:
  2 / 2 planned

Executable Bindings:
  4 / 5

Evidence:
  3 / 5
```

如果实现成本明显较大：

```text
可以推迟到后续版本
```

本版本不是 P0。

---

# 40. 必须新增 Unit Tests

至少：

```text
requirement with strategy
→ PASS

requirement without strategy
→ BLOCK

critical invariant with strategy + case
→ PASS

critical invariant without case
→ BLOCK

bugfix with regression case
→ PASS

bugfix without regression case
→ BLOCK

duplicate test case id
→ BLOCK

invalid strategy
→ schema reject

invalid case type
→ schema reject
```

---

# 41. 必须新增 Transition Integration Test

测试：

```text
PLANNED
+
invalid test plan
```

执行：

```bash
harness transition IMPLEMENTING
```

必须：

```text
non-zero exit
state remains PLANNED
```

然后补齐 Test Plan：

```text
valid test plan
```

再次：

```bash
harness transition IMPLEMENTING
```

必须成功。

---

# 42. 必须新增 Bug Fix Integration Test

场景：

```yaml
type: bugfix
```

没有 regression case：

```text
PLANNED
→ IMPLEMENTING
```

必须失败。

增加：

```yaml
type: regression
```

case 后：

```text
transition succeeds
```

---

# 43. 必须新增 Critical Invariant Test

场景：

```yaml
severity: critical
```

但没有：

```text
verification.cases
```

必须：

```text
PLANNED → IMPLEMENTING
BLOCKED
```

增加 invariant case 后：

```text
PASS
```

---

# 44. 必须新增 Gate Integration Test

场景：

```text
Test Plan 已存在

Implementation 已完成

但 Test Case 没有 executable test binding
```

最终 Gate：

```text
BLOCKED
```

blocker：

```text
TEST_BINDING_MISSING
```

Recovery：

```text
IMPLEMENTING
```

---

# 45. 必须新增 Evidence Integration Test

场景：

```text
Test Case
+
Executable Test
```

都存在。

但是：

```text
没有 Evidence
```

Gate：

```text
BLOCKED
```

blocker：

```text
TEST_EVIDENCE_MISSING
```

Recovery：

```text
VERIFYING
```

---

# 46. 必须新增完整 Lifecycle Test

这是本版本最重要的测试。

场景：

```text
TASK NEW
    ↓
Define Requirement
    ↓
Define Critical Invariant
    ↓
Define Test Plan
    ↓
PLANNED
    ↓
IMPLEMENTING
    ↓
Bind Executable Tests
    ↓
VERIFYING
    ↓
Run Tests
    ↓
Record Evidence
    ↓
REVIEWING
    ↓
PASS
    ↓
GATING
    ↓
CONVERGED
    ↓
DONE
```

必须证明：

```text
Requirement
→ Test Case
→ Test
→ Evidence
```

完整可追踪。

---

# 47. 必须新增 Failure Lifecycle Test

场景：

```text
Requirement
+
Test Plan
+
Implementation
```

但是遗漏一个 Test Evidence。

Gate：

```text
BLOCKED
```

Recovery：

```text
VERIFYING
```

补 Evidence：

```text
VERIFYING
→ REVIEWING
→ GATING
→ CONVERGED
→ DONE
```

---

# 48. 不要只测试函数

测试层次按风险选择，不能为凑数量强制每个 Feature 都有全部类型：

```text
unit
  纯逻辑、分支、边界

integration
  DB / API / 文件 / 队列等真实 seam

invariant
  跨路径始终成立的性质

regression
  bugfix 或已知故障防复发

e2e
  关键用户旅程或多系统链路

lifecycle
  Harness 自身的 Plan → Binding → Evidence → Gate → Recovery
```

每个 Feature 至少有 Happy Path，外加一项与其风险有关的 Negative、Boundary、State Transition、Failure Recovery、Concurrency、Security 或 Invariant Case。关键跨 seam 路径至少有 Integration Case；用户主旅程或多系统编排才要求 E2E。

Lifecycle 是 Harness 发布条件，不替代被测 Feature 的 Integration/E2E。不要因为：

```text
validate_test_plan()
```

单元测试全部通过，就认为功能完成。

---

# 49. Adversarial Tests

至少增加：

### Case A

Agent 删除 critical invariant test case：

```text
Gate must fail
```

### Case B

Agent 写：

```yaml
strategies:
  - fake-strategy
```

Schema：

```text
reject
```

### Case C

Bugfix 使用：

```text
happy_path
```

但没有：

```text
regression
```

Test Plan Gate：

```text
reject
```

### Case D

自动化 Test Case 没有 Evidence，或 Evidence 的 `covered_tests` 未覆盖其 executable binding：

```text
Gate reject
```

### Case E

Feature 只有 Happy Path，Reviewer 发现其明显 Bad Input、Boundary、状态迁移或 Failure Recovery 风险未被计划覆盖：

```text
REVIEWING
→ VERIFICATION_GAP
→ VERIFYING
```

---

# 50. 不要使用 Code Coverage 作为 Gate

本版本禁止增加：

```text
coverage >= 80%
```

作为核心判断。

原因：

```text
Code Coverage
!=
Requirement Coverage
```

Harness 应该关注：

```text
Requirement Coverage

Invariant Coverage

Regression Coverage
```

---

# 51. 建议新增 Traceability Summary

如果实现简单，可以增加内部函数：

```python
build_traceability(...)
```

返回类似：

```python
{
    "requirements": {
        "REQ-001": {
            "cases": ["TC-001"],
            "tests": [...],
            "evidence": [...]
        }
    }
}
```

供：

```text
Gate
Status
未来 Evaluation
```

复用。

如果当前版本实现会明显扩大范围：

```text
先不提供 CLI
```

只做内部模型。

---

# 52. 文件修改建议

预计涉及：

```text
pyproject.toml
package.json
CHANGELOG.md

src/harness/controlplane.py

src/harness/quality_gate.py

src/harness/blockers.py

src/harness/test_plan.py        # new

src/harness/schemas/requirement.schema.json

src/harness/schemas/invariant.schema.json

相关 evidence schema

初始化模板

README.md

tests/test_test_plan.py

tests/test_test_plan_transition.py

tests/test_test_plan_gate.py

tests/test_test_plan_lifecycle.py
```

具体以当前仓库结构为准。

不要为了匹配这个文件列表强行创建不必要文件。

---

# 53. 版本更新

本功能完成后：

```text
Python package → 0.2.4
npm package    → 0.2.4
README         → v0.2.4
CHANGELOG      → 0.2.4
```

现有：

```text
version consistency test
```

必须继续通过。

---

# 54. CHANGELOG

新增：

```text
## 0.2.4

### Added

- Test Plan Gate before implementation.
- Verification strategies for requirements and invariants.
- Structured test cases.
- Bug-fix regression test requirements.
- Critical invariant test-plan requirements.
- Requirement → Test Case → Executable Test → Evidence traceability.
- Test-plan-aware quality gate checks.

### Changed

- PLANNED → IMPLEMENTING now fails closed when the test plan is incomplete.
```

根据最终实际实现调整。

---

# 55. 不允许破坏 0.2.2 能力

必须继续保持：

```text
Typed GateBlocker

Code-driven Recovery

Git base_commit

Complexity Review Scope

Review Outcome

Reason Code

Evidence Freshness

BLOCKED Recovery

Second Review Loop

DONE Revalidation
```

所有 0.2.2 regression tests 必须继续通过。

---

# 56. 实施顺序

小模型严格按照：

```text
Step 1
阅读当前 schema / requirement / invariant / evidence 实现

Step 2
增加 Test Plan 数据模型和 schema

Step 3
实现 validate_test_plan()

Step 4
增加 Unit Tests

Step 5
接入 PLANNED → IMPLEMENTING

Step 6
增加 Transition Integration Tests

Step 7
增加 Executable Test Binding

Step 8
接入 Quality Gate

Step 9
增加 Evidence Traceability

Step 10
增加 Gate Tests

Step 11
增加 Lifecycle Tests

Step 12
增加 Adversarial Tests

Step 13
更新 init templates

Step 14
更新 README / CHANGELOG / version

Step 15
运行完整测试

Step 16
git diff --check

Step 17
输出实施报告
```

---

# 57. Definition of Done

## Test Plan

- [ ] Requirement / Invariant 支持 `test_plan.strategies`
- [ ] Requirement / Invariant 支持 `test_plan.cases`
- [ ] Critical Invariant 强制 test plan
- [ ] Bugfix 强制 regression case
- [ ] Strategy 使用 enum
- [ ] Case type 使用 enum
- [ ] Case 声明所属 strategy
- [ ] 自动化 strategy 至少一个 case
- [ ] Duplicate case 被拒绝（Task 范围全局唯一）

## Control Plane

- [ ] PLANNED → IMPLEMENTING 检查 Test Plan
- [ ] Test Plan 不完整时 fail closed
- [ ] state 保持 PLANNED
- [ ] Test Plan 完整后 transition 成功

## Traceability

- [ ] Requirement → Test Case
- [ ] Invariant → Test Case
- [ ] Test Case → Executable Test
- [ ] Test Case → Evidence.covered_tests
- [ ] 多份同类型 Evidence 均可参与覆盖判断

## Gate

- [ ] Missing test binding → BLOCKED
- [ ] Missing test evidence 或 covered_tests 未覆盖 binding → BLOCKED
- [ ] Missing binding → IMPLEMENTING
- [ ] Missing evidence → VERIFYING

## Lifecycle

- [ ] 正常完整生命周期 PASS
- [ ] Missing Evidence recovery 生命周期 PASS
- [ ] Critical Invariant 测试 PASS
- [ ] Bug Fix Regression 测试 PASS

## Compatibility

- [ ] 0.2.2 regression tests 全部通过
- [ ] 旧 Harness 文件可以读取
- [ ] Git baseline 不受影响
- [ ] Recovery Policy 不受影响
- [ ] DONE revalidation 不受影响

## Release

- [ ] Python version = 0.2.4
- [ ] npm version = 0.2.4
- [ ] README = 0.2.4
- [ ] CHANGELOG = 0.2.4
- [ ] version consistency PASS

---

# 58. 最终验收模型

v0.2.4 完成后必须形成：

```text
             Specification
                   │
                   ▼
             Requirements
                   │
             ┌─────┴─────┐
             ▼           ▼
        Acceptance    Invariants
             │           │
             └─────┬─────┘
                   ▼
               Test Plan
                   │
          ┌────────┴────────┐
          ▼                 ▼
Verification Strategy    Test Cases
                            │
                            ▼
                     Executable Tests
                            │
                            ▼
                         Evidence
                            │
                            ▼
                         Review
                            │
                            ▼
                          Gate
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
              BLOCKED              CONVERGED
                 │                     │
                 ▼                     ▼
              Recovery                DONE
```

核心原则：

> **Harness 不负责替 Agent 写更多测试，而是负责确保 Agent 在实现之前明确“需要证明什么”，并在完成时提供“已经证明”的可验证证据。**

最终衡量的不是：

```text
写了多少测试
```

也不是：

```text
Code Coverage 有多高
```

而是：

```text
Requirement 是否被证明

Critical Invariant 是否被证明

Bug Fix 是否有 Regression Protection

这些证明是否对应当前代码
```

---

# 59. 小模型执行要求

请直接修改代码，不要只输出设计分析。

如果本文档中的示例字段与当前仓库已有 Schema 有冲突：

```text
优先复用现有数据模型
```

但必须保持本文档定义的行为语义。

不要进行与本需求无关的大规模重构。

遇到不确定设计：

```text
优先：
最小改动
→ backward compatible
→ fail closed
→ regression test
```

完成每个阶段后运行相关测试。

最后必须运行完整测试套件。

---

# 60. 最终实施报告格式

完成后输出：

```text
## Implementation Summary

## Files Changed

## Test Plan Gate

PASS / FAIL

## Requirement Traceability

PASS / FAIL

## Invariant Traceability

PASS / FAIL

## Bugfix Regression Enforcement

PASS / FAIL

## Evidence Traceability

PASS / FAIL

## Lifecycle Tests

PASS / FAIL

## Adversarial Tests

PASS / FAIL

## Backward Compatibility

PASS / FAIL

## Full Test Suite

Command:
...

Result:
...

## Git Diff Check

Command:
git diff --check

Result:
...

## Definition of Done

逐项 PASS / FAIL

## Remaining Risks

## Final Verdict

IMPLEMENTATION COMPLETE

或

IMPLEMENTATION INCOMPLETE
```

不要只输出：

```text
功能已经实现，所有测试通过。
```

必须提供实际验证证据。
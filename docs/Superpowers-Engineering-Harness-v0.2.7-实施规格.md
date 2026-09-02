# Superpowers Engineering Harness v0.2.7 实施规格

> 版本：v0.2.7  
> 主题：Task Ownership & Review Convergence  
> 日期：2026-09-02  
> 状态：Implementation Specification  
> 面向：AI Coding Agent / 小模型实现者  
> 范围：Engineering Harness 控制面  
> 基线：当前 `main` / v0.2.6  
> 原则：Fail Closed / Deterministic / Evidence Driven / Minimal Change

---

# 1. 版本目标

v0.2.7 不重新设计 Engineering Harness，也不改变现有 Q1/Q2/Q3 分级体系。

本版本解决 v0.2.6 在真实 Q3/STRICT 工作流中暴露出的两个核心控制面问题：

```text
1. 什么代码真正属于当前 Task？
2. Review 发现问题并修复后，如何确定性地重新收敛到 Gate？
```

整体闭环：

```text
Task
 │
 ├── Task Ownership
 │      │
 │      ├── owned paths
 │      ├── dependencies
 │      ├── contract paths
 │      └── protected user paths
 │
 ├── Verification
 │      │
 │      └── Evidence
 │
 ├── Review
 │      │
 │      └── Finding
 │             │
 │             ├── Repair
 │             └── Re-review
 │
 └── Gate Assessment
        │
        ├── Quality
        └── Release Readiness
```

v0.2.7 的目标不是增加更多流程，而是让已有流程：

```text
Scope
→ Evidence
→ Review
→ Finding
→ Repair
→ Re-review
→ Gate
```

形成稳定、可恢复、可审计的闭环。

---

# 2. 必须解决的问题

| ID | 问题 | 当前后果 | 优先级 |
|---|---|---|---|
| P0-1 | Finding 修复后缺少 Finding-aware review 恢复入口 | REPRODUCING / FIXED 与 REVIEWING 之间形成操作死循环 | P0 |
| P0-2 | 通用 Finding schema 同时承担多种 Finding 类型 | `oneOf` / category 错误不可操作 | P0 |
| P1-1 | review scope 自动合并全部 workspace change | 用户无关改动污染当前 Task review | P0 |
| P1-2 | Evidence reference 解析能力不统一 | 不同命令接受不同 evidence 引用方式 | P1 |
| P1-3 | Evidence 执行与既有执行结果导入职责混合 | 重型命令容易被误执行或重复执行 | P1 |
| P1-4 | 缺失 evidence 到 Gate 阶段才发现 | VERIFYING → GATING → BLOCKED 形成无价值循环 | P1 |
| P2-1 | Complexity review 可以只提交 `findings: []` | 无法证明各 complexity dimension 被实际检查 | P2 |
| P2-2 | Gate PASS 与 MR Ready 语义混合 | 用户可能把质量通过误认为允许 Ready MR | P2 |

---

# 3. 非目标

v0.2.7 不做以下事情：

- 不放宽 Q2/Q3 Gate。
- 不修改 Q1/FAST 默认最小流程。
- 不删除 evidence freshness。
- 不删除 workspace fingerprint。
- 不删除 Git binding。
- 不删除 Finding 生命周期。
- 不让 Harness 判断业务逻辑是否正确。
- 不让 Harness 自动判断日志是否“合理”。
- 不自动修改业务代码。
- 不引入新的业务层 Agent。
- 不重构整个 `controlplane.py`。
- 不为了代码整洁提前创建 `findings.py`、`impact.py` 等新模块。
- 不修改 `.harness/history/**` 历史 artifact。
- 不把用户已有无关 Git 修改纳入当前 Task。

---

# 4. 核心设计原则

## 4.1 Task Scope 与 Workspace Safety 分离

必须明确：

```text
Review Scope
    ≠
Workspace Safety Scope
```

Review Scope 回答：

> 哪些文件属于当前 Task，需要进入 impact / review / contract / verification？

Workspace Safety Scope 回答：

> 当前工作区是否发生了可能导致 evidence stale 的变化？

因此：

```text
Task-owned files
      ↓
Impact / Review / Verification

Whole protected workspace
      ↓
Fingerprint / Freshness / User change protection
```

用户原来存在的修改：

```text
docs/local-note.md
```

即使不属于当前 Task，也仍然：

```text
参与 workspace fingerprint
```

但：

```text
不得自动进入 review scope
```

---

## 4.2 Proposal、Finding、Review Evidence 是不同对象

禁止继续把三种对象混为一体：

```text
Proposal ≠ Finding ≠ Review Evidence
```

Proposal：

```text
Reviewer 提议存在一个问题
```

Finding：

```text
Harness 正式持久化的问题对象
```

Review Evidence：

```text
一次 Review 的完整审计结果
```

Harness 负责：

```text
Proposal
   ↓
validate
   ↓
deduplicate
   ↓
allocate FND-NNN
   ↓
persist Finding
   ↓
write mapping into Review Evidence
```

---

## 4.3 Finding 生命周期驱动 Task 恢复

禁止使用通用 state transition 绕过 Finding lifecycle。

正确关系：

```text
REVIEWING
    │
    │ defect
    ↓
REPRODUCING
    ↓
CONFIRMED
    ↓
FIXING
    ↓
FIXED
    │
    │ repair proof complete
    ↓
resume-review
    ↓
REVIEWING
    ↓
fresh review
    ↓
VERIFIED
    ↓
CLOSED
```

必须区分：

```text
repair proof
```

与：

```text
closure proof
```

FIXED 表示：

> 修复已经完成并有基本修复证据。

VERIFIED 表示：

> Fresh Review 已证明 Finding 不再成立。

CLOSED 表示：

> Finding 生命周期正式结束。

---

# 5. Task-owned Scope

## 5.1 Task Schema

扩展 `.harness/current-task.yaml`。

推荐结构：

```yaml
git:
  base_ref: origin/main
  base_commit: 0123456789abcdef0123456789abcdef01234567
  head_at_start: 89abcdef0123456789abcdef0123456789abcdef

scope:
  owned_paths: []
  protected_user_paths: []
```

不要把：

```text
owned_paths
protected_user_paths
```

放入 `git:`。

原因：

```text
git.*
```

表示 Git identity。

```text
scope.*
```

表示 Task ownership policy。

---

# 6. Session Startup

Task 创建或分类完成时：

1. 冻结 `base_ref`。
2. 冻结 `base_commit`。
3. 冻结 `head_at_start`。
4. 扫描 Task 开始前已有 workspace change。
5. 将这些路径记录为：

```yaml
scope:
  protected_user_paths:
```

例如：

```yaml
scope:
  protected_user_paths:
    - docs/local-note.md
```

这些文件：

```text
参与 fingerprint
不进入 Task review scope
不得被 Harness 自动 adopt
```

---

# 7. Owned Path

`owned_paths` 表示：

> 当前 Task 明确负责修改、验证和 Review 的路径。

只能通过显式控制面行为增加。

例如：

```bash
harness impact add-change backend/app/api/v1/chat.py
```

或：

```bash
harness impact adopt-path backend/app/api/v1/chat.py
```

如果当前 CLI 没有对应命令，可以在当前 control plane 中增加最小实现。

不要为了增加命令提前重构整个 impact subsystem。

---

# 8. Protected User Path

新增：

```bash
harness impact ignore-user-path docs/local-note.md
```

CLI 名称可以为了兼容用户语义保留 `ignore-user-path`。

但内部 schema 字段必须使用：

```text
protected_user_paths
```

而不是：

```text
ignored_user_paths
```

因为 Harness 并没有真正忽略这些文件。

它们仍参与：

```text
workspace fingerprint
freshness
user-change safety
```

---

# 9. Scope Projection

新增：

```bash
harness impact scope --format yaml
```

输出当前 effective task scope。

基础规则：

```text
effective_scope =
    owned_paths
  + observability.inspected_paths
  + declared direct_dependencies
  + applicable contract paths
```

禁止：

```text
effective_scope += all git status paths
```

---

# 10. Contract Scope

Contract path 不允许被 Task ownership 意外排除。

但不要简单把所有 contract path 都纳入 source review。

如果当前数据模型允许，逐步区分：

```yaml
contract:
  implementation_paths: []
  verification_paths: []
  observability_paths: []
  context_paths: []
```

自动进入 source review 的主要是：

```text
implementation_paths
observability_paths
```

如果当前 contract schema 不支持这种分类：

> v0.2.7 不要求进行大规模 contract schema 重构。

先保持当前 contract semantics，并保证真正与实现/验证相关的 contract path 不会因 owned scope 被遗漏。

---

# 11. Scope Monotonicity

Task 生命周期中：

```text
owned_paths(t+1) ⊇ owned_paths(t)
```

默认只允许增加。

禁止静默删除。

如果未来需要删除：

```bash
harness impact release-path PATH
```

必须：

- 显式调用。
- 提供 reason。
- 写入 history/evidence。
- 重新计算 scope。
- 使相关 evidence stale。

v0.2.7 如果没有实际 release-path 使用需求：

> 可以暂不实现删除能力。

但必须保证现有接口不能静默缩小 `owned_paths`。

---

# 12. Scope 验收案例

初始：

```text
docs/local-note.md      用户已有未提交修改
```

Task：

```text
TASK-001
```

Agent 修改：

```text
backend/x.py
```

结果必须：

```yaml
scope:
  owned_paths:
    - backend/x.py

  protected_user_paths:
    - docs/local-note.md
```

Review Scope：

```text
backend/x.py
```

不得包含：

```text
docs/local-note.md
```

Workspace fingerprint：

```text
必须同时感知两个文件状态
```

显式：

```bash
harness impact adopt-path docs/local-note.md
```

之后：

```text
docs/local-note.md
```

才进入 Task scope。

---

# 13. Finding Schema 分离

禁止继续让一个通用 `finding.schema.json` 通过复杂 `oneOf` 承载全部 Finding。

新增或逐步迁移为：

```text
src/harness/schemas/
  adversarial-finding.schema.json
  complexity-finding.schema.json
  diagnosability-finding.schema.json
  diagnosability-review.schema.json
```

不要为了本 Step 重构 Python module hierarchy。

---

# 14. Diagnosability Finding

正式持久化 Finding：

```yaml
id: FND-001
kind: requirement_violation
category: diagnosability

target: REQ-005

scenario: >
  Default model unavailable rejection lacks
  structured diagnostic event.

severity: major
status: PROPOSED

reason_code: DIAG_MISSING_CRITICAL_EVENT

location:
  file: backend/app/api/v1/chat.py
  line: 2899

compliance:
  evidence_kind: static_compliance
  required_checks:
    - caller_rejections
```

必须拥有正式：

```text
FND-NNN
```

ID。

---

# 15. Diagnosability Proposal

Diagnosability Review 输入不再直接要求 Reviewer 构造完整 Finding。

改成：

```yaml
proposals:
  - local_id: diag-default-unavailable-log

    target: REQ-005

    severity: major

    reason_code: DIAG_MISSING_CRITICAL_EVENT

    location:
      file: backend/app/api/v1/chat.py
      line: 2899

    required_checks:
      - caller_rejections
```

`local_id`：

- 只在本次 review 中有效。
- 不等于 Finding ID。
- 用于 review evidence mapping。

---

# 16. Proposal 发布

Review 发布时：

```text
proposal
   ↓
schema validation
   ↓
semantic validation
   ↓
deduplicate
   ↓
allocate FND-NNN
   ↓
persist Finding
   ↓
persist review evidence
```

Review Evidence 保存：

```yaml
finding_mapping:
  diag-default-unavailable-log: FND-001
```

必须原子化。

禁止：

```text
Finding 创建成功
Review Evidence 写入失败
```

后留下半完成状态。

---

# 17. Duplicate Finding

如果已经存在等价 Finding：

```text
FND-001
```

新的 proposal 与其匹配：

```text
target
reason_code
location
required_checks
```

Harness 必须返回稳定错误：

```text
DIAG_PROPOSAL_DUPLICATE
```

示例：

```text
DIAG_PROPOSAL_DUPLICATE

proposal:
  diag-default-unavailable-log

matches:
  FND-001
```

禁止直接暴露：

```text
jsonschema oneOf validation failed...
```

给 CLI 用户。

---

# 18. Finding Error Contract

所有 Finding schema / proposal validation error 必须转换为 Harness error code。

例如：

```text
DIAG_PROPOSAL_FIELD_REQUIRED
DIAG_PROPOSAL_DUPLICATE
DIAG_FINDING_INVALID
DIAG_REQUIRED_CHECK_INVALID
```

测试：

```text
断言 error code
```

禁止：

```text
断言 jsonschema 英文错误原文
```

---

# 19. Finding Resume Review

新增：

```bash
harness finding resume-review FND-001
```

用途：

> Finding 已 FIXED，需要回到 REVIEWING 进行 fresh review。

---

# 20. Resume Review Preconditions

必须校验：

```text
target Finding.status == FIXED
```

并且当前 Task 不存在：

```text
PROPOSED
REPRODUCING
CONFIRMED
FIXING
```

状态 Finding。

如果存在：

```text
FND-002 FIXING
```

拒绝：

```text
FINDING_REVIEW_RESUME_BLOCKED
```

并列出：

```text
blocking_findings:
- FND-002
```

---

# 21. Task State Transition

满足条件：

```text
task.state == REPRODUCING
```

时：

```text
REPRODUCING
   ↓
REVIEWING
```

通过：

```text
finding resume-review
```

执行。

不得直接修改：

```yaml
current-task.yaml:
  state:
```

---

# 22. 禁止通用 Transition 绕过

当：

```text
task = REPRODUCING
```

且存在：

```text
FIXED Finding
```

用户执行：

```bash
harness transition REVIEWING
```

Harness 必须拒绝。

输出类似：

```text
FINDING_REVIEW_RESUME_REQUIRED

Use:
  harness finding resume-review FND-001
```

保持当前 Harness 已存在的：

```text
specialized transition command
```

设计模式。

---

# 23. Diagnosability Verification

进入：

```text
REVIEWING
```

后重新执行：

```text
fresh diagnosability review
```

只有 fresh review 满足：

```text
required_checks == pass
```

才能：

```bash
harness finding transition FND-001 VERIFIED --evidence ...
```

之后：

```text
VERIFIED
   ↓
CLOSED
```

Finding 未 CLOSED：

```text
review outcome PASS
```

必须拒绝。

---

# 24. Unified Evidence Resolver

实现唯一公共 resolver：

```text
resolve_evidence_reference(...)
```

以下命令必须复用：

```text
requirement verify
invariant verify
finding transition
review
gate
evidence attach
```

不要每个命令各自解析。

---

# 25. Evidence Reference Forms

以下四种形式必须解析到同一 artifact：

```text
fast-green-integration-test
```

```text
fast-green-integration-test.json
```

```text
.harness/evidence/fast-green-integration-test.json
```

```text
/absolute/path/.../fast-green-integration-test.json
```

---

# 26. Evidence Resolution Failure

解析失败：

```text
EVIDENCE_REFERENCE_INVALID
```

输出：

```text
input:
  supplied-reference

accepted:
  - evidence ID
  - filename
  - relative path
  - absolute path

candidates:
  - fast-green-integration-test
  - fast-green-contract-test
```

Candidates 只能来源于当前 task 可访问 evidence。

不得扫描任意外部目录。

---

# 27. Evidence Run

新增显式执行入口：

```bash
harness evidence run \
  --type build \
  --scope related \
  --command 'npm run build'
```

只有：

```text
evidence run
```

负责执行 command。

---

# 28. Evidence Reuse

当前已有：

```text
--reuse-if-valid
```

能力必须保留。

不要重新实现另一套 cache。

`evidence run`：

```text
command
   ↓
reuse-if-valid?
   ├── yes → reuse valid evidence
   └── no  → execute once
```

同一次 command request：

```text
最多执行一次
```

---

# 29. Evidence Attach

新增：

```bash
harness evidence attach \
  --type build \
  --scope related \
  --command 'npm run build' \
  --result-file /tmp/build-result.json
```

Attach：

```text
不执行 command
```

只导入：

> 已经执行完成并具有结构化 provenance 的 execution record。

---

# 30. Attach 最低要求

Result file 至少包含：

```text
command
exit_code
started_at
finished_at
git_head
workspace_fingerprint
stdout_digest
stderr_digest
```

缺任何必需字段：

```text
EVIDENCE_ATTACH_INCOMPLETE
```

失败关闭。

---

# 31. 禁止人工 Passed

禁止：

```bash
harness evidence attach --passed
```

禁止用户提供：

```yaml
result: passed
```

作为成功依据。

Harness 必须根据：

```text
exit_code
provenance
binding
freshness
```

判断 artifact 是否有效。

---

# 32. Legacy Evidence Command

旧：

```bash
harness evidence ...
```

继续兼容一个版本。

行为等价：

```bash
harness evidence run ...
```

同时输出：

```text
DEPRECATED:
Use `harness evidence run`.
```

不得破坏 v0.2.6 使用者。

---

# 33. Gate Assessment

禁止分别实现：

```text
preflight logic
gate logic
```

新增共享 deterministic assessment：

```text
evaluate_gate_requirements(...)
```

概念结果：

```yaml
ready_for_gating: false

missing_evidence: []

blockers: []

recommendations: []

quality: {}

release_readiness: {}
```

---

# 34. Gate Preflight

新增：

```bash
harness gate preflight
```

示例：

```text
READY: no

missing:
- type: build
  reason: agents-frontend/** in task-owned scope
  command: npm run build

- type: integration_test
  reason: REQ-003 / TC-003
```

Preflight：

```text
只评估
不修改 task state
```

---

# 35. Transition GATING

执行：

```bash
harness transition GATING
```

前必须调用：

```text
evaluate_gate_requirements(...)
```

如果缺 evidence：

```text
task 保持当前状态
```

例如：

```text
VERIFYING
```

不得：

```text
VERIFYING
→ GATING
→ BLOCKED
```

仅仅为了报告缺 build evidence。

---

# 36. Preflight / Gate 一致性

以下三个入口：

```text
gate preflight
transition GATING
gate
```

必须共享：

```text
evaluate_gate_requirements(...)
```

同一 workspace / evidence / task 状态下：

```text
missing evidence reason
```

必须一致。

---

# 37. Gate 双轴结果

Gate 不再只表达一个 PASS/BLOCKED。

改为：

```yaml
quality:
  status: PASS | BLOCKED | CONTINUE

release_readiness:
  status: READY | DRAFT_ONLY | NOT_READY
  reasons: []
```

---

# 38. Quality

Quality 只回答：

> 当前 Task 所要求的工程证据是否完整并满足 Gate policy？

例如：

```yaml
quality:
  status: PASS
```

可以表示：

```text
related tests PASS
required build PASS
Finding CLOSED
review PASS
freshness valid
```

---

# 39. Release Readiness

Release Readiness 回答：

> 根据当前项目 release policy 与用户授权，是否允许声明 Ready？

例如：

```yaml
release_readiness:
  status: DRAFT_ONLY

  reasons:
    - full_suite_required_but_not_authorized
```

---

# 40. 禁止硬编码 Full Suite Policy

不得实现：

```text
Q3 + no full suite
→ 永远 DRAFT_ONLY
```

必须根据项目已有 policy / required tests / authorization 决定。

概念：

```text
required evidence policy
+
authorization
+
actual coverage
=
release readiness
```

如果 policy 只要求：

```text
related_tests
build
```

这些均满足：

```text
READY
```

可以成立。

只有 policy 要求：

```text
full_suite
```

但没有授权/没有执行时：

```text
DRAFT_ONLY
```

或：

```text
NOT_READY
```

根据当前 Harness policy semantics 决定。

---

# 41. MR Describe

`harness mr describe` 必须读取：

```text
quality
release_readiness
```

如果：

```yaml
quality:
  status: PASS

release_readiness:
  status: DRAFT_ONLY
```

则输出必须明确：

```text
Quality Gate: PASS
MR Readiness: DRAFT ONLY
```

不得生成：

```text
Ready for MR
```

或勾选 Ready checklist。

---

# 42. Complexity Review Audit

当前：

```yaml
findings: []
```

不足以证明 complexity review 真正发生。

新增：

```yaml
checks:

  delete:
    result: pass
    evidence: No obsolete snapshot helper remains.

  reuse:
    result: pass
    evidence: Reused existing reconciliation seam.

  stdlib:
    result: not_applicable
    evidence: No new parsing or collection need.

  native:
    result: pass
    evidence: Existing framework facilities reused.

  yagni:
    result: pass
    evidence: No unnecessary abstraction introduced.

  shrink:
    result: pass
    evidence: Removed obsolete helper paths.

findings: []
```

---

# 43. Complexity Check Result

允许：

```text
pass
fail
not_applicable
```

每项必须：

```text
result
evidence
```

Harness 不负责判断：

> 这个 evidence 的业务观点是不是聪明。

Harness 只负责：

```text
规定检查项是否被明确判断
判断是否持久化
是否可追溯
是否与当前 review binding
```

---

# 44. Complexity Finding

如果：

```yaml
checks:
  yagni:
    result: fail
```

则必须存在对应：

```text
proposal / finding
```

禁止：

```text
check = fail
findings = []
```

---

# 45. Backward Compatibility

v0.2.7 允许旧 complexity input：

```yaml
findings: []
```

但输出：

```text
COMPLEXITY_CHECKS_DEPRECATED
```

warning。

v0.4：

```text
缺 checks → reject
```

---

# 46. Active Task Migration

读取旧：

```text
.harness/current-task.yaml
```

如果没有：

```yaml
scope:
  owned_paths:
```

迁移规则：

优先使用：

```text
旧 impact.changed
```

初始化：

```yaml
scope:
  owned_paths:
```

禁止：

```text
扫描所有 git status
→ 全部放入 owned_paths
```

---

# 47. Old Diagnosability Finding Migration

旧 DIAG Finding：

如果可以 deterministic 推断：

```yaml
category: diagnosability
```

允许 active-task migration。

如果无法确定：

```text
MIGRATION_REQUIRED
```

不得：

```text
猜测 Finding 类型
```

---

# 48. History Migration

禁止修改：

```text
.harness/history/**
```

v0.2.7 migration：

```text
只影响 active task
```

历史 artifact 继续保持原始格式。

---

# 49. 实施策略

必须严格执行：

```text
RED
↓
minimal implementation
↓
GREEN
↓
regression
↓
next Step
```

禁止：

```text
先完成所有实现
最后补测试
```

---

# 50. Step 1 — Finding Domain / Schema Separation

目标：

```text
解决 P0-2
```

主要修改当前真实存在的相关文件：

```text
src/harness/schemas/
src/harness/diagnosability.py
src/harness/controlplane.py
tests/test_diagnosability*.py
```

不要为了本 Step 创建新的 domain module。

实现：

1. 独立 DIAG Finding schema。
2. 独立 DIAG proposal schema。
3. Review inline object 改成 proposal。
4. Proposal → persistent Finding。
5. Duplicate detection。
6. Harness-level error code。

RED：

```text
1. DIAG proposal → FND-001
2. duplicate → DIAG_PROPOSAL_DUPLICATE
3. missing field → stable error code
4. 不暴露 oneOf 英文错误
5. Finding + review evidence 原子写入
```

---

# 51. Step 2 — Finding Resume Review

目标：

```text
解决 P0-1
```

主要修改：

```text
src/harness/controlplane.py
src/harness/state_machine.py
tests/test_finding_lifecycle*.py
```

尽量复用当前已有：

```text
REPRODUCING → REVIEWING
```

primitive。

不要创建第二套状态机。

RED：

```text
FIXED DIAG
+ no active Finding
→ resume-review
→ REPRODUCING → REVIEWING
```

```text
FND-002 FIXING
→ resume-review rejected
→ blocking ID returned
```

```text
generic transition REVIEWING
+ FIXED Finding
→ FINDING_REVIEW_RESUME_REQUIRED
```

```text
fresh DIAG review
→ VERIFIED
→ CLOSED
```

---

# 52. Step 3 — Task-owned Scope

目标：

```text
解决 P1-1
```

主要修改：

```text
src/harness/workspace.py
src/harness/controlplane.py
src/harness/diagnosability.py
src/harness/schemas/task.schema.json
tests/test_review_scope*.py
```

如果当前 impact command 位于 `controlplane.py`：

> 在现有位置做最小实现。

不要因为实施文档中的概念名称创建不存在的 `impact.py`。

RED：

```text
existing unrelated dirty file
→ protected
→ not review scope
```

```text
explicit adopt
→ owned
→ review scope
```

```text
owned path cannot silently disappear
```

```text
contract-required path remains visible
```

```text
protected path still changes workspace fingerprint
```

---

# 53. Step 4 — Unified Evidence Resolver

目标：

```text
解决 P1-2
```

主要修改：

```text
src/harness/controlplane.py
src/harness/evidence_validator.py
相关 evidence helper
tests/test_evidence*.py
```

不要为了名字一致强制创建：

```text
evidence.py
```

除非当前代码已经自然需要该模块且变更范围极小。

RED：

四种引用：

```text
ID
filename
relative path
absolute path
```

必须 resolve 到同一个 artifact。

invalid：

```text
EVIDENCE_REFERENCE_INVALID
```

包含 candidates。

---

# 54. Step 5 — Evidence Run / Attach

目标：

```text
解决 P1-3
```

主要复用：

```text
src/harness/collect_evidence.py
src/harness/controlplane.py
```

保留：

```text
--reuse-if-valid
```

不要重新实现 cache。

RED：

```text
run command → exactly once
```

```text
reuse valid → command not executed
```

```text
attach → command never executed
```

```text
attach missing fingerprint
→ EVIDENCE_ATTACH_INCOMPLETE
```

```text
manual passed flag
→ unsupported
```

---

# 55. Step 6 — Gate Assessment / Preflight

目标：

```text
解决 P1-4
```

主要修改：

```text
src/harness/quality_gate.py
src/harness/controlplane.py
tests/test_quality_gate*.py
```

实现共享：

```text
evaluate_gate_requirements(...)
```

RED：

```text
frontend owned path
+ build required
+ build missing

gate preflight
→ missing build
→ recommended command
```

```text
transition GATING
→ same reason
→ state unchanged
```

```text
gate
→ same deterministic reason
```

---

# 56. Step 7 — Quality / Release Readiness

目标：

```text
解决 P2-2
```

主要修改：

```text
src/harness/quality_gate.py
src/harness/controlplane.py
src/harness/schemas/gate.schema.json
MR describe related tests
```

RED：

```text
required related evidence complete
→ quality PASS
```

```text
release policy requirement unavailable / unauthorized
→ DRAFT_ONLY
```

```text
quality PASS + DRAFT_ONLY
→ MR not Ready
```

```text
policy does not require full suite
+ required evidence complete
→ READY allowed
```

---

# 57. Step 8 — Complexity Audit Fields

目标：

```text
解决 P2-1
```

主要修改：

```text
src/harness/complexity.py
complexity schema
tests/test_complexity*.py
```

RED：

```text
checks complete
+ findings []
→ valid
```

```text
check fail
+ no proposal/finding
→ reject
```

```text
old input
→ accepted + deprecation warning
```

不要让 Harness 自动推理 complexity。

---

# 58. 每 Step 禁止事项

每次只做一个 Step。

禁止：

```text
跨 Step 顺手重构
```

禁止：

```text
顺手拆 controlplane.py
```

禁止：

```text
顺手统一全部 schema
```

禁止：

```text
顺手改 CLI naming
```

禁止：

```text
顺手修与当前 Step 无关的问题
```

发现额外问题：

```text
记录 Finding / TODO
```

不要扩大实现范围。

---

# 59. Schema 修改规则

每次修改 schema：

必须同时修改：

```text
schema
validator
fixture
RED test
migration compatibility
```

不得只修改 JSON schema。

---

# 60. Error Code 规则

所有新增用户可见失败必须有 stable code。

例如：

```text
DIAG_PROPOSAL_DUPLICATE
FINDING_REVIEW_RESUME_BLOCKED
FINDING_REVIEW_RESUME_REQUIRED
EVIDENCE_REFERENCE_INVALID
EVIDENCE_ATTACH_INCOMPLETE
GATE_PREFLIGHT_MISSING_EVIDENCE
TASK_SCOPE_SHRINK_REQUIRES_EXPLICIT_RELEASE
```

测试：

```text
assert code
```

而不是：

```text
assert JSON schema library message
```

---

# 61. Freshness Invariant

v0.2.7 不得破坏：

```text
evidence
   ↕
Git HEAD
   ↕
workspace fingerprint
   ↕
Task
```

Task Scope 缩小：

```text
不代表 workspace fingerprint 缩小
```

这是强制 invariant。

---

# 62. Finding Invariant

必须满足：

```text
Finding CLOSED
→ 必须存在 verification evidence
```

对于 Diagnosability Finding：

```text
verification evidence
→ fresh diagnosability review
```

不得：

```text
FIXED → CLOSED
```

直接关闭。

---

# 63. Gate Invariant

必须满足：

```text
Gate PASS
≠
MR READY
```

正确：

```text
Quality PASS
+
Release Readiness READY
=
MR Ready
```

---

# 64. Scope Invariant

必须满足：

```text
Task Scope
```

不能通过 Git workspace 自动扩大。

也不能通过模型行为静默缩小。

因此：

```text
Git status
≠
Task ownership
```

---

# 65. Evidence Invariant

必须满足：

```text
Evidence artifact
```

不是：

> 模型说“测试通过”。

而必须是：

```text
Execution
+
Result
+
Provenance
+
Git Binding
+
Workspace Binding
+
Freshness
```

---

# 66. 完整 Q3 Worked Example

至少增加一个完整 regression scenario。

初始：

```text
Task = Q3 / STRICT
```

状态：

```text
IMPLEMENTING
→ VERIFYING
→ REVIEWING
```

Diagnosability Review：

```text
proposal
```

Harness：

```text
proposal
→ FND-001 PROPOSED
→ review failure
→ REPRODUCING
```

Agent：

```text
reproduce
→ CONFIRMED
→ FIXING
→ modify code
→ evidence
→ FIXED
```

然后：

```bash
harness finding resume-review FND-001
```

状态：

```text
REPRODUCING
→ REVIEWING
```

执行 fresh diagnosability review：

```text
required_checks PASS
```

Finding：

```text
FIXED
→ VERIFIED
→ CLOSED
```

Review：

```text
PASS
```

Verification：

```text
required evidence complete
```

Preflight：

```text
READY
```

Gate：

```yaml
quality:
  status: PASS
```

Release：

根据 policy：

```yaml
release_readiness:
  status: READY
```

或：

```yaml
release_readiness:
  status: DRAFT_ONLY
```

整个流程不得需要：

```bash
harness transition REVIEWING
```

等人工绕过 Finding lifecycle 的命令。

---

# 67. Workspace Isolation Worked Example

初始：

```text
git status:

M docs/local-note.md
```

Task 开始。

Harness：

```yaml
scope:
  protected_user_paths:
    - docs/local-note.md
```

Agent 修改：

```text
backend/x.py
```

Harness：

```yaml
scope:
  owned_paths:
    - backend/x.py
```

Review：

```text
backend/x.py
```

不包含：

```text
docs/local-note.md
```

但是用户修改：

```text
docs/local-note.md
```

发生变化后：

```text
workspace fingerprint changes
```

相关 evidence：

```text
stale
```

这两个行为必须同时成立。

---

# 68. 回归测试要求

至少覆盖：

```text
Finding schema
Finding proposal
Finding deduplication
Finding lifecycle
resume-review
Task state transition
Task-owned scope
protected user path
contract scope
workspace fingerprint
evidence resolver
evidence run
evidence reuse
evidence attach
evidence freshness
gate assessment
gate preflight
quality gate
release readiness
complexity audit
legacy migration
```

---

# 69. Release Definition of Done

全部满足才允许发布 v0.2.7：

- [ ] Step 1～8 每个 Step 均有 RED test。
- [ ] 所有 RED 已 GREEN。
- [ ] 全量 `pytest` 通过。
- [ ] 旧 active task fixture 可读取。
- [ ] 旧 complexity review 至少兼容一个版本。
- [ ] 旧 `harness evidence` CLI 可继续运行。
- [ ] DIAG proposal 不再暴露底层 `oneOf` 错误。
- [ ] Finding 从 review failure → CLOSED 全程无需通用 transition 绕过。
- [ ] 无关 workspace change 不进入 review scope。
- [ ] protected user path 仍参与 workspace fingerprint。
- [ ] owned path 不可静默缩小。
- [ ] 四种 evidence reference 形式行为一致。
- [ ] Evidence attach 不允许人工声明 passed。
- [ ] `gate preflight` 与 Gate 使用同一个 assessment。
- [ ] 缺 evidence 不产生无意义 GATING → BLOCKED 循环。
- [ ] Quality PASS 与 Release Ready 已分离。
- [ ] Full Suite requirement 来自 policy，不由 Q3 硬编码。
- [ ] Complexity review 每个规定维度存在 auditable decision。
- [ ] Q3 worked example 完成。
- [ ] Workspace isolation worked example 完成。
- [ ] CLI help 更新。
- [ ] Architecture 文档更新。
- [ ] Migration 文档更新。

---

# 70. 文档更新

至少更新：

```text
README.md
docs/architecture.md
CLI help
Q3 worked example
migration notes
```

Architecture 文档必须增加：

```text
Task Ownership
Review Scope vs Workspace Safety Scope
Proposal / Finding / Review Evidence
Finding-driven Review Recovery
Gate Assessment
Quality vs Release Readiness
```

---

# 71. 小模型执行协议

实现者必须严格执行：

```text
读取当前 Step
↓
定位当前代码
↓
写 RED test
↓
确认 RED 原因正确
↓
写最小实现
↓
运行目标测试
↓
GREEN
↓
运行相关 regression
↓
报告修改与 evidence
↓
停止
```

等待用户明确：

```text
继续下一 Step
```

后才执行下一步。

禁止一次实现多个 Step。

---

# 72. 每 Step 输出格式

每完成一个 Step，必须输出：

```text
STEP: Step N

STATUS:
GREEN | BLOCKED

CHANGED:
- file
- file

TESTS:
- command
- result

ERROR CODES ADDED:
- CODE

INVARIANTS VERIFIED:
- invariant

REGRESSION:
- command
- result

OUT-OF-SCOPE FINDINGS:
- finding or none

NEXT:
Step N+1
```

禁止只回复：

```text
已完成。
```

必须给出可验证 evidence。

---

# 73. 实现优先级

如果开发时间有限，按以下顺序发布：

## Release Blocking

```text
Step 1 Finding schema
Step 2 Finding resume-review
Step 3 Task-owned scope
```

这是 v0.2.7 最核心部分。

它们解决：

```text
Finding convergence
+
Task ownership
```

## Strongly Recommended

```text
Step 4 Evidence resolver
Step 5 Evidence run/attach
Step 6 Gate preflight
```

解决：

```text
Evidence usability
+
unnecessary Gate loops
```

## Completion

```text
Step 7 Quality / Release Readiness
Step 8 Complexity Audit
```

解决：

```text
release semantics
+
review auditability
```

---

# 74. v0.2.7 架构定位

v0.2.x 主要解决：

```text
What evidence is required?
```

v0.2.7 进一步解决：

```text
What belongs to this task?
```

以及：

```text
How does a failed review converge
back to a valid Gate?
```

最终控制面：

```text
                TASK
                  │
          ┌───────┴───────┐
          │               │
      Ownership       Requirements
          │               │
          └───────┬───────┘
                  ↓
                Scope
                  ↓
             Implementation
                  ↓
             Verification
                  ↓
               Evidence
                  ↓
                Review
                  ↓
               Finding
                  │
          ┌───────┴───────┐
          ↓               │
        Repair            │
          ↓               │
        FIXED             │
          ↓               │
     Resume Review ───────┘
          ↓
       VERIFIED
          ↓
        CLOSED
          ↓
     Gate Assessment
          │
     ┌────┴─────────┐
     ↓              ↓
  Quality       Release
   PASS         Readiness
     │              │
     └──────┬───────┘
            ↓
        MR Decision
```

---

# 75. 最终原则

v0.2.7 不应该通过增加更多 Agent 智能来解决问题。

应该通过：

```text
更明确的对象
+
更明确的 ownership
+
更明确的状态转换
+
更明确的 evidence provenance
+
更明确的 Gate semantics
```

解决问题。

Engineering Harness 的职责仍然是：

```text
Model decides semantics.
Harness enforces process.
Evidence proves execution.
State machine prevents shortcuts.
Task ownership prevents scope pollution.
Gate assessment prevents false convergence.
```

最终目标：

> **不是让 AI 更容易宣布“完成”，而是让一个 Q3 Task 即使经历 Review Failure、Finding Repair、Workspace 并存修改和授权限制，仍然能够通过确定性的控制面路径收敛到一个可证明的工程状态。**
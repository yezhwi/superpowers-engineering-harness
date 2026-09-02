# Harness Q3 工作流优化实施指南

> 版本：v0.2.7 草案  
> 日期：2026-09-02  
> 状态：实施规格  
> 面向：小模型实现者  
> 范围：Engineering Harness 控制面；不改业务项目代码

## 1. 目标

修复 Q3/STRICT 实际执行中暴露的控制面问题，同时保持 fail-closed 原则。

必须达成：

1. Finding 修复后可合法回到 `REVIEWING`，不形成诊断复核死循环。
2. Diagnosability Finding 的持久化对象、review inline 对象和普通 Finding 不再发生 schema 歧义。
3. 无关工作区改动不进入 task review scope。
4. evidence 引用支持 ID 和路径；重型命令可避免无意重复执行。
5. Gate 进入前可预览缺失证据和推荐命令。
6. Gate 输出区分“质量通过”与“因授权不足只能 Draft”。

非目标：

- 不放宽 Q2/Q3 Gate。
- 不删除 evidence freshness、Git/workspace binding、Finding 生命周期。
- 不让 Harness 判断业务正确性或自动写业务日志。
- 不改变 Q1/FAST 的最小流程，除非接口兼容需要。

## 2. 已确认问题

| ID | 问题 | 当前后果 | 优先级 |
|---|---|---|---|
| P0-1 | Finding `FIXED` 后需 fresh diagnosability review，但 review 仅允许 `REVIEWING` | `REPRODUCING/FIXED` 与 `REVIEWING` 循环 | P0 |
| P0-2 | 通用 Finding schema 的 `oneOf` 同时承载普通、complexity、diagnosability Finding | `category` 报错互相矛盾 | P0 |
| P1-1 | review scope 合并 task diff、全部未提交改动、Contract path | 无关用户改动污染审查 | P1 |
| P1-2 | `requirement verify --evidence` 仅接受 ID，不接受文件路径 | `EVIDENCE_REFERENCE_INVALID` 无可操作提示 | P1 |
| P1-3 | `harness evidence --command` 总是重跑命令 | build 被重复执行、易超时 | P1 |
| P1-4 | Gate 到 GATING 后才报告缺 build evidence | 产生无意义 `BLOCKED` 循环 | P1 |
| P2-1 | Q3 review 可只填 `findings: []` | complexity 审查缺少可审计判断 | P2 |
| P2-2 | Gate 不显式说明 Draft-only 原因 | 用户容易误以为 Gate PASS 等于 Ready MR | P2 |

## 3. 总体设计

### 3.1 新增 task-owned scope

在 task 创建/分类完成时，冻结任务基线和归属路径：

```yaml
# .harness/current-task.yaml
git:
  base_ref: origin/main
  base_commit: 0123456789abcdef0123456789abcdef01234567
  task_head_at_start: 89abcdef0123456789abcdef0123456789abcdef
  owned_paths: []
  ignored_user_paths: []
```

规则：

- `owned_paths` 仅由 `harness impact add-change`、`harness impact adopt-path` 增加。
- Session Startup 发现的用户既有改动写入 `ignored_user_paths`，只参与 workspace 安全 fingerprint，不参与 review scope。
- review effective scope：

```text
owned_paths
+ observability.inspected_paths
+ declared direct_dependencies
```

- 任一 Contract path 不在 owned/dependency 中，直接纳入 scope。
- 不再把所有 `git status` 路径自动并入 review scope。

新增命令：

```bash
harness impact adopt-path backend/app/api/v1/chat.py
harness impact ignore-user-path docs/local-note.md
harness impact scope --format yaml
```

验收：用户先有 `docs/local-note.md` 未提交改动，TASK 仅修改 `backend/x.py`；Q3 review scope 不含 `docs/local-note.md`。

### 3.2 分离 Finding schema

禁止继续使用单个 `finding.schema.json` 的模糊 `oneOf` 承载全部类型。

新增：

```text
schemas/
  adversarial-finding.schema.json
  complexity-finding.schema.json
  diagnosability-finding.schema.json
  diagnosability-review.schema.json
```

持久化对象：

```yaml
# .harness/findings/FND-001.yaml
id: FND-001
kind: requirement_violation
category: diagnosability
target: REQ-005
scenario: Default model unavailable rejection lacks structured event.
severity: major
status: PROPOSED
reason_code: DIAG_MISSING_CRITICAL_EVENT
location:
  file: backend/app/api/v1/chat.py
  line: 2899
compliance:
  evidence_kind: static_compliance
  required_checks: [caller_rejections]
```

review inline finding 不再复用完整 Finding。改为 proposal：

```yaml
# diagnosability review input
proposals:
  - local_id: diag-default-unavailable-log
    target: REQ-005
    severity: major
    reason_code: DIAG_MISSING_CRITICAL_EVENT
    location:
      file: backend/app/api/v1/chat.py
      line: 2899
    required_checks: [caller_rejections]
```

发布 review 时，Harness 原子生成 `FND-NNN`，将 `local_id -> FND-NNN` 写入 evidence。若用户同时预建相同 Finding，报：

```text
DIAG_PROPOSAL_DUPLICATE: proposal matches existing FND-001
```

不要报 JSON schema 内部 `oneOf` 文本。

### 3.3 Finding 与 task 状态路由

新增明确规则：

```text
REVIEWING + DEFECT → REPRODUCING
REPRODUCING → CONFIRMED → FIXING → FIXED
FIXED + closure proof → REVIEWING
REJECTED → REVIEWING
```

`harness finding transition FND-001 FIXED` 后：

- Finding 仍是 `FIXED`。
- task 仍可处于 `REPRODUCING`。
- `harness finding resume-review FND-001` 校验该 task 无 `PROPOSED/REPRODUCING/CONFIRMED/FIXING` Finding，自动：

```text
REPRODUCING → REVIEWING
```

- Q3 fresh diagnosability review 在 `REVIEWING` 执行。
- `harness finding transition FND-001 VERIFIED` 对 diagnosability Finding 必须引用 fresh `diagnosability_review`，且 `required_checks` 都为 `pass`。
- Finding CLOSED 后才允许 `review outcome PASS`。

禁止用户手工用通用 `harness transition REVIEWING` 绕过 Finding 路由；若存在 FIXED Finding，提示使用 `harness finding resume-review`。

### 3.4 Evidence 引用与执行模式

Evidence resolver 必须支持：

```text
fast-green-integration-test
fast-green-integration-test.json
.harness/evidence/fast-green-integration-test.json
/abs/path/.../fast-green-integration-test.json
```

解析失败时输出：

```text
EVIDENCE_REFERENCE_INVALID
input: supplied-reference
accepted: evidence ID, filename, relative path, absolute path
candidates: fast-green-integration-test, fast-green-contract-test
```

拆分命令：

```bash
# 唯一会执行命令的入口
harness evidence run --type build --scope related --command 'npm run build'

# 仅导入既有、结构化且可验证的运行记录
harness evidence attach --type build --scope related \
  --command 'npm run build' --result-file /tmp/build-result.json
```

`attach` 最少校验：命令、exit_code、started_at、finished_at、Git HEAD、workspace fingerprint、stdout/stderr digest。缺任一项 fail closed。不得允许人工填写“passed”。

`harness evidence` 保留为 `run` 的兼容别名，并打印弃用提示。

### 3.5 Gate preflight 与 Draft-only

新增：

```bash
harness gate preflight
```

输出示例：

```text
READY: no
missing:
- type: build
  reason: agents-frontend/** in task-owned scope
  command: npm run build
- type: integration_test
  reason: REQ-003 / TC-003
```

`harness transition GATING` 先执行同一 deterministic preflight：缺证据时保持 `VERIFYING`，不先进入 `GATING/BLOCKED`。

Gate 结果改为双轴：

```yaml
quality:
  status: PASS | BLOCKED | CONTINUE
release_readiness:
  status: READY | DRAFT_ONLY | NOT_READY
  reasons:
    - full_suite_not_authorized
```

规则：

- Q2/Q3 使用 related evidence 完整覆盖 `impact.required_tests` 时，`quality: PASS` 可成立。
- `full_suite` 未授权时，`release_readiness: DRAFT_ONLY`。
- `harness mr describe` 根据此输出生成 MR Ready checklist，不得标记 Ready。

### 3.6 可审计 review 结论

complexity review input 由空 findings 扩展为每维结论：

```yaml
checks:
  delete:
    result: pass
    evidence: No obsolete snapshot helper remains.
  reuse:
    result: pass
    evidence: Reused session_model_selection reconciliation seam.
  stdlib:
    result: not_applicable
    evidence: No new parsing/collection need.
  native:
    result: pass
    evidence: Existing SQLAlchemy/logging facilities reused.
  yagni:
    result: pass
    evidence: No new abstraction or dependency.
  shrink:
    result: pass
    evidence: Removed snapshot-first capability helpers.
findings: []
```

P2 不要求模型“智能判断”；只要求审查者把判断和代码证据持久化，供 Gate/MR review 追溯。

## 4. 实施顺序

严格按下列顺序。每一步先写 RED 测试，再写最小实现。

### Step 1：建立 schema 与 fixture

修改：

```text
src/harness/schemas/
src/harness/diagnosability.py
tests/test_diagnosability*.py
```

实现：独立加载并验证 DIAG Finding/proposal；删除跨类型 `oneOf` 分支依赖。

RED：

1. DIAG proposal 生成持久 `FND-001`。
2. 已存在等价 FND 时返回 `DIAG_PROPOSAL_DUPLICATE`。
3. 不完整 proposal 返回明确字段错误。

### Step 2：Finding resume-review 路由

修改：

```text
src/harness/controlplane.py
src/harness/state_machine.py
src/harness/findings.py
tests/test_finding_lifecycle*.py
```

实现 `harness finding resume-review FND-NNN`。

RED：

1. `FIXED` DIAG Finding + 无活跃 finding：`REPRODUCING -> REVIEWING`。
2. 存在 `FIXING` Finding：拒绝并列出 ID。
3. 普通 `harness transition REVIEWING` 在 FIXED Finding 场景提示专用命令。

### Step 3：task-owned scope

修改：

```text
src/harness/workspace.py
src/harness/impact.py
src/harness/diagnosability.py
schemas/task.schema.json
tests/test_review_scope*.py
```

实现冻结基线、owned/ignored path、scope projection。

RED：无关未提交文件不进入 scope；显式 adopt 后进入；Contract path 永远进入。

### Step 4：Evidence resolver 与 run/attach

修改：

```text
src/harness/evidence.py
src/harness/controlplane.py
tests/test_evidence*.py
```

RED：四种引用形式解析到同一 artifact；attach 缺 fingerprint 拒绝；run 只执行一次。

### Step 5：Gate preflight 与双轴结果

修改：

```text
src/harness/quality_gate.py
src/harness/controlplane.py
schemas/gate.schema.json
tests/test_quality_gate*.py
```

RED：前端 owned path 缺 build 时 preflight 给命令；GATING transition 不改变状态；full suite 未授权时 `DRAFT_ONLY`。

### Step 6：review audit fields

修改 complexity schema、validator、tests。保持旧 input 兼容一个小版本：缺 `checks` 时 warning；v0.4 起拒绝。

## 5. 兼容与迁移

1. 读取旧 `.harness/current-task.yaml` 时，缺 `owned_paths`：初始化为旧 `impact.changed`，不扫描所有未提交文件。
2. 读取旧 DIAG Finding：使用迁移函数补 `category: diagnosability`；不能推断的 artifact 标记 `MIGRATION_REQUIRED`，不得静默变更。
3. 旧 `harness evidence` 命令继续运行，但输出 `Use: harness evidence run`。
4. 不修改历史 `.harness/history/**`；迁移只影响 active task。

## 6. 完成定义

全部满足才可发布：

- [ ] Step 1-6 每项存在 RED/ GREEN 回归测试。
- [ ] `pytest` 覆盖 schema、state transition、scope、evidence、gate。
- [ ] 旧 active task fixture 可读取。
- [ ] Q3 worked example：DIAG finding 从 review failure 到 CLOSED 无手工通用 transition。
- [ ] 无关工作区改动不污染 review scope。
- [ ] `gate preflight` 和最终 Gate 对缺失证据给出相同原因。
- [ ] 文档更新 `docs/architecture.md`、worked example、CLI help。

## 7. 小模型执行约束

- 一次只做一个 Step；不得跨 Step 重构。
- 每改 schema 必须同步改 validator 与最小 fixture。
- 不直接编辑 `current-task.yaml.state`；全部走 CLI/state machine。
- 不以“测试通过”替代 freshness、scope、Finding linkage 校验。
- 不把用户无关 Git 改动加入 `owned_paths`。
- 每个新 error code 在测试中断言精确 code，不断言底层 JSON schema 英文原文。

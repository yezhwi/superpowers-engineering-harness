# Engineering Harness evidence freshness 与测试路径绑定问题

- 状态：已修复（v0.2.7）
- 日期：2026-09-07
- 来源：RClaw `TASK-1144` 实测
- 范围：Harness control-plane；不是 RClaw 业务缺陷

## 摘要

Q3/STRICT 任务中，Harness 的 verification metadata、review evidence 与 workspace freshness 规则可形成自我失效循环：写入 requirement/invariant verification 或 review 结果会改变 `.harness/`，使此前刚收集的 test evidence 变为 stale；重新收集 evidence 后，再写入绑定或 review metadata 又会使该 evidence stale。

另有 covered test 路径以字符串精确匹配，不能识别同一测试在仓库根目录与子项目工作目录下的等价相对路径，导致已执行测试无法绑定到 test plan。

## 触发条件

任务同时具备以下条件：

1. Q3/STRICT profile，Gate 要求 fresh evidence 与 requirement/invariant/test-plan binding。
2. 测试在子项目目录运行，例如：
   - 后端 cwd：`backend/`，selector：`tests/knowledge/test_*.py`。
   - 前端 cwd：`agents-frontend/`，selector：`src/__tests__/*.spec.ts`。
3. test plan 使用仓库根路径，例如：
   - `backend/tests/knowledge/test_*.py`。
   - `agents-frontend/src/__tests__/*.spec.ts`。
4. 执行 `harness requirement verify`、`harness invariant verify`、complexity review、diagnosability review 或其他会写 `.harness/` control-plane metadata 的操作。

## 观察到的行为

### 1. Freshness 自我失效循环

实际顺序：

1. 收集后端、前端相关测试 evidence。
2. 执行 `harness requirement verify` 与 `harness invariant verify`。
3. 这些命令写入 `.harness/requirements.yaml`、`.harness/invariants.yaml`。
4. workspace fingerprint 改变，先前 evidence 被标记为 `EVIDENCE_WORKSPACE_STALE`。
5. 重新收集 evidence。
6. 执行 review 或 requirement/invariant binding，review 又写 `.harness/evidence/` 或 control-plane metadata。
7. fingerprint 再次改变，evidence 再次 stale。

结果：Gate 不是因测试失败阻断，而是因 Harness 自己写入的验证状态使 proof 失效。开发者被迫重复执行相同的相关测试，仍无法稳定到达 Gate。

### 2. 测试路径等价性未归一化

Harness 的 covered test 校验使用裸字符串匹配。以下路径指向同一文件，但被视为不同：

```text
backend/tests/knowledge/test_document_lifecycle_lock_concurrency.py
tests/knowledge/test_document_lifecycle_lock_concurrency.py

agents-frontend/src/__tests__/knowledgeBase-document-tree.spec.ts
src/__tests__/knowledgeBase-document-tree.spec.ts
```

前者是仓库根目录 test plan path；后者是子项目 cwd 的自然 runner selector。

结果：测试已真实执行并通过，Harness 仍报告：

```text
COVERED_TEST_NOT_EXECUTED
TEST_EVIDENCE_MISSING
```

为绕过裸字符串比较，调用者只能改变 cwd、拼接注释或构造不自然命令。这增加了 command/evidence 的脆弱性，也可能使前端 alias、Vitest root 或 pytest config 失效。

## 影响

- Gate proof 无法稳定收敛。
- 无业务变更时反复执行相同测试，浪费时间与 CI/开发资源。
- 开发者可能误判为测试或业务代码故障。
- 为满足字符串路径匹配而改变 cwd，会引入不代表正常测试环境的失败。
- harness evidence 的“fresh”语义混合了业务变更与控制面状态变更，无法回答“测试是否覆盖当前产品代码”。

## 根因判断

### A. workspace fingerprint 边界过宽

当前 freshness 计算将 Harness 自己的 control-plane 文件纳入被验证工作区。

但以下写入不改变被测产品行为：

- `.harness/evidence/**`
- `.harness/requirements.yaml` 中 verification/evidence/status 字段
- `.harness/invariants.yaml` 中 verification/status 字段
- `.harness/current-task.yaml` 中 state、gate、timestamps、统计字段
- complexity、diagnosability、review outcome 等 review metadata

将这些文件纳入 product evidence fingerprint，使“记录验证结果”变成“使验证结果失效”的操作。

### B. covered test path 缺少仓库根目录规范化

Harness 比较 test plan path 与 runner selector 时，没有将 selector 按命令 cwd 解析为仓库根目录 canonical path，也没有以 realpath/relative-to-repo 的形式比较。

## 建议修复

### 1. 分离 product fingerprint 与 control-plane fingerprint

推荐维护两个 fingerprint：

- `product_workspace_fingerprint`
  - 覆盖产品代码、测试、依赖、配置与任务显式纳入的文档。
  - 用于 test/build evidence freshness。
- `control_plane_fingerprint`
  - 覆盖 `.harness/` 的任务状态、evidence、review、requirement/invariant verification metadata。
  - 用于检测 Harness 状态是否被篡改或需要重新计算 Gate，不使产品测试 evidence stale。

最小替代方案：对 product evidence snapshot 排除 `.harness/**`，至少排除 evidence、review、finding closure、requirement/invariant verification 和 task status 文件。

要求：修改 `.harness/` 的控制面记录后，未改产品代码/测试时，已收集的相关 test evidence 仍应保持 fresh。

### 2. 将 covered test 规范化到仓库根目录

收集 evidence 时：

1. 解析命令中的 cwd，包括 `sh -lc 'cd ... && ...'`。
2. 对 pytest/Vitest selector 按该 cwd 解析。
3. 使用仓库 root-relative canonical path 存储，例如：

```text
backend/tests/knowledge/test_document_lifecycle_lock_concurrency.py
agents-frontend/src/__tests__/knowledgeBase-document-tree.spec.ts
```

4. test plan binding 也仅比较 canonical path。

兼容策略：读取旧 evidence 时，可接受已存储 selector 与 canonical path 二选一匹配，并在下一次 evidence collection 时迁移为 canonical path。

### 3. 将 evidence binding 设计为不使自身失效

requirement/invariant verification 与 test-plan coverage binding 应是 append-only control-plane 关系；其变更不得使所引用的 product test evidence 失效。

Gate 应分别验证：

1. evidence 对 product workspace fresh；
2. binding 引用的 evidence 存在、成功、类型与 scope 合法；
3. 当前 control-plane state 与 binding schema 合法。

不要用单一 workspace fingerprint 同时承担三种语义。

## 验收标准

### Freshness

1. 收集相关 test evidence 后，执行 `harness requirement verify` 与 `harness invariant verify`，evidence 仍为 fresh。
2. 写 complexity/diagnosability/review outcome 后，未改产品文件的 build/test evidence 仍为 fresh。
3. 修改产品代码、产品测试或任务纳入的非 control-plane 配置后，evidence 必须变 stale。
4. 篡改 evidence payload、binding 引用或 control-plane schema 时，Gate 必须阻断。

### Path binding

1. backend cwd 的 `tests/foo.py` 能绑定仓库根路径 `backend/tests/foo.py`。
2. frontend cwd 的 `src/foo.spec.ts` 能绑定仓库根路径 `agents-frontend/src/foo.spec.ts`。
3. canonical path 不存在、逃逸仓库 root 或 selector 未在命令中执行时，仍拒绝绑定。
4. 同一命令在仓库根目录或子项目目录执行时，产生相同 canonical covered test path。

### Gate

1. Q3 task 在所有相关测试通过、bindings 完整、findings 已关闭后，连续执行 Gate 不因仅 `.harness/` metadata 改动失败。
2. Gate 失败应区分：产品 evidence stale、coverage 缺失、control-plane schema 无效、finding 未关闭；不得把 control-plane 自更新报告为产品测试 stale。

## 建议回归用例

- 收集 evidence → requirement verify → invariant verify → review → Gate；断言无需重跑产品测试。
- 后端子项目 cwd pytest selector 与根目录 test plan path 绑定。
- 前端子项目 cwd Vitest selector 与根目录 test plan path 绑定。
- 修改 `.harness/evidence/`、`.harness/requirements.yaml` verification 字段不使 product evidence stale。
- 修改 `backend/` 或 `agents-frontend/` 被覆盖测试文件后，product evidence 变 stale。
- 伪造 covered test path、无效 cwd、仓库外路径与未执行 selector 必须被拒绝。

## 非目标

- 本文不修改 RClaw 业务代码。
- 本文不降低 Q3/STRICT 的 evidence、finding closure 或 Gate 要求。
- 本文不建议将 `.harness/` 全部排除于安全校验；control-plane 完整性仍应独立校验。

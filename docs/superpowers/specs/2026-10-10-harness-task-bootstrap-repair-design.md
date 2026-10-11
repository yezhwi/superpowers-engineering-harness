# Harness Task Bootstrap Repair Design

## Goal

让新 Q2/Q3 task 从创建、contract、alignment、plan 到 IMPLEMENTING 只走受控 Harness 边界完成；状态、seal、plan 初始化走 CLI，contract 正文由 Task Contract skill 写入；不继承前 task control artifacts。

## Scope

1. 增加受控 alignment revise/unfreeze 生命周期。
2. `harness task new` / `harness task recover` 归档并移除旧 plan artifacts；`classify` 按 profile 初始化 execution。
3. 在 `SPECIFYING -> PLANNED` 前拒绝缺 acceptance criteria、implementation surface、或 automated test node binding 的 contract。
4. v2 protected user-change snapshot 在 Context read scope 内安全计算。
5. 提供端到端 CLI/skill regression coverage。

## Non-goals

- 不改变业务代码、evidence freshness、proof digest、plan coverage 规则。
- 不允许任意删除/修改 frozen alignment state。
- 不迁移或复用前 task 的 proof receipts。

## Design

### 1. Alignment revision

新增：

```bash
harness align revise --reason "<non-empty reason>"
```

准入：current task 存在，state 不是 `DONE`/`CONVERGED`，alignment 当前 frozen，reason 非空。

原子行为：

- 在 optional `alignment.yaml.revisions[]` 追加 `{reason, timestamp, previous_contract_hash}`。
- 同一事务将 `freeze.frozen=false`、`frozen_at=null`、`contract_hash=null`。
- 同一事务删除 `alignment-freeze.yaml` seal。
- 不改变 task state，不放宽 Gate。

后续必须经：

```bash
harness align freeze
harness align check
```

`align freeze` 验证 draft completeness 并重新生成 seal；`align check` 验证 frozen seal。没有 revise 的 frozen alignment 仍返回现有 `ALIGNMENT_ALREADY_FROZEN`。`revisions` 是审计元数据，不参与 alignment `contract_hash` 投影；仅追加审计不构成 contract drift。`alignment.schema.json` 增加 optional `revisions`，旧 frozen alignment 仍合法。

### 2. New-task artifact isolation

`harness task new TASK-nnn` 和 `harness task recover` 保留现有 template reset/cleanup：requirements、invariants、gate、impact、observability 重置；活的 alignment、freeze、evidence、findings 删除或归档。两命令还必须在创建/recovery 前将旧 plan artifacts 一并 archive 到：

```text
.harness/history/<task-id>-<timestamp>/
```

至少包含：

- `plan.yaml`
- `plan-execution.yaml`
- `alignment.yaml`
- `alignment-freeze.yaml`
- evidence 与 findings

两条命令在既有 cleanup 范围内 archive 并移除旧 `plan.yaml` / `plan-execution.yaml`；`CREATED` 时尚未分类，不能预判 Q2/Q3 profile，也不写 plan/execution。

`harness task classify` 按 profile 原子初始化 empty canonical artifacts。Q2/Q3 都写：

```yaml
# plan.yaml
version: 1
items: []
```

fingerprint 使用 `plan_fingerprint(empty plan)`。

```yaml
# Q2 / final
version: 1
plan:
  path: .harness/plan.yaml
  fingerprint: <empty-plan-fingerprint>
items: {}
```

```yaml
# Q3 / task_and_final
version: 2
plan:
  path: .harness/plan.yaml
  fingerprint: <empty-plan-fingerprint>
sequence: 0
transitions: []
items: {}
```

Q1 不写 plan artifacts。新 execution 永不引用旧 item、receipt、fingerprint 或 task id。

v2 `protected_user_changes_fingerprint` 在 Context 构建时不得以未声明 protected user path 调用 `source_access.is_file/read_bytes`。它必须使用 Context-safe Git query，或 Context read scope 必须显式声明每个 protected path。`task classify Q3` 后含 untracked protected path 的 `harness context --compact` 必须成功。`harness plan upgrade-execution` 只处理同 task legacy v1 execution，不能作为 new-task reset。

### 3. Contract admission

`SPECIFYING -> PLANNED` 检查：

- 每个 requirement 至少有一个 alignment acceptance criterion；criterion 只关联 `REQ-*`。
- 每个 `priority: must` requirement 至少有一个 implementation surface 关联该 criterion。
- automated requirement/invariant case 的 `tests` 非空，subject 为 `REQ-001/TC-001` 或 `INV-001/TC-001`。
- `manual` case 不要求 `tests`。

缺失时 fail closed，不写 transition。subject-first 稳定输出格式与现有 alignment diagnostics 一致：

```text
REQ-001: REQ_WITHOUT_AC
REQ-001: CRITICAL_REQ_WITHOUT_SURFACE
REQ-001/TC-001: TEST_BINDING_REQUIRED
INV-001/TC-001: TEST_BINDING_REQUIRED
```

此阶段只检查 selector 非空。文件存在性仍在 `PLANNED -> IMPLEMENTING` 用现有 `TEST_PLAN_TARGET_MISSING` 检查，避免测试文件尚未实现时无法进入 PLANNED。

Task Contract skill 写 requirements、invariants，以及完整合法的 `alignment.yaml`：`version`、current `task_id`、goal、scope、non-goals、boundaries、constraints、assumptions、acceptance criteria、implementation surfaces、verification、decision/interface references、open lists，且 `freeze={frozen: false, frozen_at: null, contract_hash: null}`。不能仅写 AC/surface/verification；`harness align init` 在文件存在时返回 `ALIGNMENT_EXISTS`，不是更新入口。CLI 负责 state transition、seal、plan initialization。

### 4. Lifecycle

```text
task new
-> classify (profile-specific empty plan/execution initialization)
-> harness transition SPECIFYING
-> Task Contract skill writes requirements, invariants, and complete alignment.yaml
-> harness align freeze (draft completeness)
-> harness align check (frozen seal)
-> harness transition PLANNED (contract admission runs here)
-> harness check minimal
-> harness transition IMPLEMENTING
```

任一步失败输出可执行 next command；不要求删除 `.harness` 文件或编辑 task state。

## Verification

1. Frozen alignment revise 后必须重新 check/freeze；无 revise 不能覆盖 seal。
2. 连续创建 Q2 和 Q3 task：Q2 为 empty v1，Q3 为 empty v2；均无前 task items/receipts。
3. automated case 无 `tests` 时 `SPECIFYING -> PLANNED` 返回 `<subject>: TEST_BINDING_REQUIRED`，task bytes 不变。
4. requirement 无 AC 或 must requirement 无 surface 分别返回已有 stable code。
5. complete contract 可经 skill/CLI 边界完整进入 IMPLEMENTING。
6. `upgrade-execution` 不会重置新 task 或跨 task 继承 history。
7. v2 protected snapshot task 的 compact context 在 protected untracked path 存在时成功生成。

## Risks

- Archive 路径必须排除 product workspace fingerprint；`.harness` 已被现有 fingerprint exclude。
- Alignment audit schema 变化必须保持旧 frozen task 可读。
- Contract writer、alignment validator、plan initializer 必须共享 task identity，避免新的跨 task 泄漏。

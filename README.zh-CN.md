# Superpowers Engineering Harness v0.3.2

[English](README.md)

Engineering Harness 是 [Superpowers](https://github.com/obra/superpowers) 开发工作流外层的确定性控制平面。它不替代 Agent 或 worker Skill；它持久化任务状态、要求可验证证据，并阻止 Agent 未经 Gate 批准就宣称任务完成。

[架构全景图](docs/architecture.md)

## v0.3.2 兼容性与测量状态

`v0.3.2 development candidate`：已批准功能及后续限定修复已实现，不代表发布或当前 HEAD 的版本级 Gate 验收。[交付状态及发布验收建议](docs/superpowers/reports/v032-context-efficiency.md#v032-delivery-status)区分历史任务验收和版本发布就绪。单独授权发布前，下方固定版本安装示例继续使用 v0.3.1 current release；不能假定 v0.3.2 tag 已存在。

Context 自动扩展采用批处理：候选资格消失时提交合法 prefix 后停止；真正的发布前错误不写新事件。`harness evidence plan --json`、`harness impact reconcile --file proposal.yaml --dry-run` 是只读诊断，不授予执行权限。共享资源测试保持串行；沿用精确 `--reuse-if-valid`，不跨 HEAD 继承证据，也不跳过 RED/finding 执行。

Profiling 默认关闭，通过 `harness context --compact --profile-json /tmp/context-profile.json` 启用。发布前失败 exit 2；Context 发布后 profile 写入 OSError 为 exit 3，输出 `PROFILE_WRITE_FAILED_CONTEXT_PUBLISHED context_published=true`。此时 Context 已发布，应检查并独立校验，不盲目重试；stdout 错误不归类为该 exit 3。

旧任务缺可信范围来源时以 `TEST_SCOPE_AUDIT_INVALID` 阻断。可信 origin、事务化 add 与 Gate replay 联动保护 required tests；apply 还需精确选定的 RETIRE/REBIND 用户授权。MIGRATE 仅重建来源。不得自动重建范围、freeze/resume、降风险或标记 verified/COMPLETE。激活后的元数据要求 v0.3.2 reader，旧 reader 拒绝 minimum-reader 标记。见[显式范围迁移](docs/test-scope-migration.md)及[已批准效率规范](docs/2026-10-14-context-evidence-collection-efficiency-spec.md)。

[Context 实测报告](docs/superpowers/reports/v032-context-efficiency.md)：按用户新指示仅使用 N=0/1/10/50 共80个样本，剩余 N=100 取消。大量扩展的 cold 场景改善；N=0 与 steady 中位数变慢。不宣称普遍提速或完整矩阵验收。尚无 evidence 专属缓存收益证据，持久化 evidence 缓存继续延期。后续任务级独立复审和原生 Gate 不追溯验收这批基准，也不证明 Agent 遵从、完整矩阵性能或版本发布就绪。另一次固定源码的原任务回放中，单次调用内复用 Decision 解析／schema 准备后，中位耗时由 21.0835 降至 20.1166 秒，约降低 4.6%；实际读取与校验次数不变，不外推为普遍提速。

## 平台与可恢复发布（macOS-only）

v0.3.2 candidate 仅支持 macOS，以及通过原生 exchange/no-replace/no-follow/同步检查的本地文件系统。
Linux、Windows 及其他系统的发布后端在打开发布目录或创建 capability probe 前返回 `PUBLICATION_UNSUPPORTED`。
不隐含支持网络、FUSE、远程或特殊文件系统；libc 符号存在或 probe 成功，不等于全部文件系统或断电保证。
不回退到会覆盖目标的普通 rename。

保证是保留被移走的 inode/字节，**不是 content CAS**，也不保证 canonical 路径永远保留最新用户版本。
发生冲突时，用户对象可能被**迁移**到保留位置；外部编辑器仍可通过已打开的 FD 改写同一 inode。
共享 advisory lock 只约束配合的 Harness 操作，不约束外部编辑器。
批量发布及其受保护 finalizer 不隐含升级独立 atomic write、任务目录替换或外部读写器的保证。

- `.harness/.staging/`：准备输入，不是恢复权威；stage 保留。
- `.harness/.transactions/`：活动恢复描述符；未解决或未知条目使受准入保护的 Gate/transition
  在读取 canonical 事实前拒绝，不自动修复。
- `.harness/.publication-retained/`：被移走对象、capability probe、journal frame 和终态恢复数据。
  仅有终态保留数据不代表 pending。task new/recover 将真实的旧 Harness 目录保留在其中的
  `task-replacement-*/previous`，保留原 inode 与已打开 FD 的后续写入，不在准备新任务时复制旧保留树。
  任务替换报错后，先核对当前任务再决定重试：旧目录可能位于同级 `..harness.backup` 或保留 slot。
  不自动重试或删除；此处仅保证对象寿命，不认证任务目录原子性或硬件断电行为。
- 存储包含实际元数据字节，不是证据缓存或执行授权。新私有目录请求 `0700`、新文件 `0600`；
  被移走对象保留原 inode/mode，不自动加固已有存储。应按敏感数据管理。
  数据无限期增长，可能导致 `ENOSPC`；不提供 pruning 命令或按年龄清理。
  清理需单独设计并明确授权，删除恢复数据不是受支持的修复方式。

## 为什么用 Harness

你告诉 Agent 要改什么。Harness 把任务、证明和 Gate 结果留在 `.harness/` 里，新会话可以继续同一件工作。在 `harness gate` 打印 `DECISION: CONVERGED` 之前，Agent 不能把任务标成完成。

- 小而低风险的修复留在 Q1 / FAST：失败证明、修复、通过证明、Light Gate。
- 普通交付留在 Q2 / STANDARD：合同、相关测试、review，以及最终计划核对。
- 高风险变更留在 Q3 / STRICT：一次推进一个计划项。风险可以升级，不会被悄悄降低。

提问会直接回答，并且不创建任务。只有你提出修改时才开始改代码，例如："Use Engineering Harness to fix this bug: cancelling an order twice issues two refunds."

## 5 分钟上手

通过一条显式 bootstrap 命令安装 Superpowers、Pi skills 和匹配版本的确定性 CLI。未指定版本时，安装器解析 npm `latest`，并在修改安装前要求存在匹配 Git tag：

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-pi.sh | bash
```

需要固定版本时：

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-pi.sh | bash -s -- v0.3.1
```

安装器检查是否已配置 Superpowers，仅在缺失时安装；同时协调固定版本的 Harness Pi skills，把匹配 Python CLI 安装到隔离用户环境，并暴露 `~/.local/bin/harness`。如果 `~/.local/bin` 不在 `PATH`，安装器会给出提示。重复安装相同版本保持幂等。若本地安全策略要求，请先审查下载脚本再执行。

源码开发时，另行使用 `python -m pip install -e /path/to/superpowers-engineering-harness` 安装可编辑环境。

从源码构建 v0.3.2 候选版本需 `setuptools>=77.0.3`，以支持 SPDX 许可证元数据（PEP 639）。默认 PEP 517 构建隔离会安装该构建依赖；使用 `--no-build-isolation` 时需自行提供。Python 运行时要求仍为 `>=3.11`；setuptools 68 不再声明为受支持构建后端。

仓库只需初始化一次。之后的日常工作是向 Agent 说明要做什么。Engineering Harness skill 读取持久化状态，并自己调用 `harness`。你不需要输入这些命令。

```bash
cd your-project
harness init
```

打开会话并说明要改什么，例如：

```text
Use Engineering Harness to fix this bug: cancelling an order twice issues two refunds.
```

工作中断后，新开一个会话，让 Agent 继续当前任务。Pi 安装 Skills 后需新开会话。Skills 在会话启动时加载。

### Antigravity CLI（agy）

在任意目录执行一次，安装最新稳定版 Harness CLI 和 AGY 全局 skills：

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-agy.sh | bash
```

需要固定版本时：

```bash
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-agy.sh | bash -s -- v0.3.1
```

安装器更新 `~/.gemini/antigravity-cli/skills/` 下 Harness 自己的 skills，保留无关全局 skills；不会初始化项目。每个 Git 项目中单独运行一次 `harness init`，再用 `agy` 启动 AGY；首次会话可用 `/engineering-harness` 显式调用 Harness。

## 当前日常路径

阅读下面的命令块之前，先选一条路径。

```text
问题或解释 → 直接回答，不建任务
小改动     → Q1 / FAST：RED → GREEN → Light Gate
普通交付   → Q2 / STANDARD：合同、相关测试、review、最终 Plan
高风险     → Q3 / STRICT：一次只推进一个计划项
```

你描述要做的变更。Agent 负责分类风险、完成实现，并在每个阶段调用 Harness。多数日常 Harness 命令无需交互；Agent 仍可能请求需求澄清、设计批准、接受 Decision、明确跳过或取代某项、受保护操作授权，或处理升级决定。

下面的命令块是 Agent 执行的步骤。`harness status` 是只读操作，不修改 Harness 状态。Gate 输出 `DECISION: CONTINUE` 并写入 blocker 后，Agent 才运行 `harness resume`；它按 blocker code 选择恢复状态，不信任持久化的 `recover_to`。

Q2 / STANDARD 与 Q3 / STRICT 共用 contract、review 和 Gate 路径。Agent 记录 `review outcome PASS`，它执行 `REVIEWING → GATING`：

```bash
harness status
harness transition IMPLEMENTING
harness evidence run --type unit_test --command "pytest tests/test_cancel.py"
harness transition VERIFYING
harness review complexity --file review.yaml
harness transition REVIEWING
harness review outcome PASS --reason-code REVIEW_CLEAN
harness gate
# 检查 DECISION: CONVERGED，然后：
harness transition DONE
```

阻塞恢复（`harness gate` 输出 `DECISION: CONTINUE`；Gate 持久化 blocker，`harness resume` 按 code 推导目标状态）：

```bash
harness gate
# 仅在 DECISION: CONTINUE 后
harness resume
```

进入 `VERIFYING` 前记录影响范围和关联测试。Harness 永不执行全量测试，即使仓库指令要求执行。证据 scope 固定为 `related`，且必须覆盖全部 required tests：

```bash
harness impact add-change src/orders/cancel.py
harness impact add-test tests/test_cancel.py::test_duplicate_cancel_single_refund
harness evidence run --type unit_test --scope related --covered-test tests/test_cancel.py::test_duplicate_cancel_single_refund --command "pytest tests/test_cancel.py::test_duplicate_cancel_single_refund"
```

关联 test evidence 采用 append-only 文件名（`unit-test-<hash>.json`）。Gate 合并所有 fresh record 的 `covered_tests`，新增一个 required test 时只需运行该 test。`VERIFYING → REVIEWING` 先执行 freshness preflight；required evidence stale 时拒绝进入。STANDARD/STRICT task plan 声明的 test target 文件不存在时也会拒绝。Review reason code 为受控集合：匹配的结果使用 `REVIEW_CLEAN`、`TEST_COVERAGE_INSUFFICIENT`、`EVIDENCE_INCOMPLETE`、`INVARIANT_UNPROVEN`、`TEST_SCOPE_INSUFFICIENT`、`LOGIC_ERROR`、`REGRESSION`、`CONTRACT_VIOLATION` 或 `INVARIANT_VIOLATION`。

### 回归策略兼容性

`gate.regression.confirmed_finding_without_test` 仅作为兼容字段保留，只支持数值零。省略该字段或整个 `regression` 段时仍按零处理，不能用它豁免 Finding 证明要求。

此前 Schema 接受的非零值，现在会在完整或 FAST Gate 评估前 fail-closed：退出码 `2`，诊断包含 `gate.schema.json` 和配置字段路径；任务不推进，配置不被改写。请显式将现有 `gate.yaml` 中该值改为 `0` 后重试。`harness init` 跳过已有文件，不负责迁移此配置；不提供迁移命令，也不静默截断为零。

### Q1 / FAST

提问或解释属于 Q0：Agent 直接回答，不创建 Harness task。Q1 / FAST 仅限范围窄、低风险的工作。必须显式分类；当前业务路径已命中 `.harness/risk-boundaries.yaml` 的 Q2/Q3 时，Q1 分类失败且不落盘。FAST 在读取 Plan、Markdown 或自动 evidence source 之前返回。它仍要求 task 级失败 RED、成功 GREEN 证据和 Light Gate，但跳过 impact、复杂度审查、requirements、invariants ceremony。`harness status` 的 Build/Unit/Integration 摘要与 Evidence 列表使用同一 live projection。若 work item 已在目标分支实现，用 `harness task verify-existing` 记录有效 existing-verification，禁止伪造 RED；普通缺陷修复仍走 RED→GREEN。`requires_reproduction` 保持 task 为 `CLASSIFIED`，创建或恢复 finding 后正常复现。

```bash
harness task classify --level Q1 --scope low --contract none --data none \
  --authorization none --security none --concurrency none --deployment none
harness transition IMPLEMENTING
# 修复前记录失败 regression proof，修复后记录通过 proof
harness evidence run --type unit_test --phase red --covered-test tests/test_x.py::test_x --command "pytest tests/test_x.py::test_x"
harness evidence run --type unit_test --phase green --covered-test tests/test_x.py::test_x --command "pytest tests/test_x.py::test_x"
harness transition VERIFYING
harness transition GATING
harness gate
```

FAST 不授予外部操作权限。每种授权在当前 task 内独立；只授权用户请求的动作。不存在全量测试授权：

```bash
harness authorize commit
harness authorize push
# 另有 create-mr、ready-mr、merge、deploy；用 revoke-<action> 撤销
```

### Q2 / STANDARD

标准变更由 Agent 维护一份最终核对计划，并在 Gate 前完成核对。Q2 使用 final-only Plan execution v1。`harness plan status` 报告最终核对是否通过。`--verbose` 增加不含正文的项与 proof-health 视图。`harness gate preflight` 保留原有 `READY:` 和 blocker 行，再追加同一次 assessment 的 Plan 摘要。没有单独的 Gate preview 命令。Q2 不使用 Q3 日志命令。

```bash
harness plan status
harness plan status --verbose
harness plan sync-markdown docs/plan.md
harness check admission  # 一次报告全部 implementation-entry 缺陷
harness gate preflight
```

### Q3 / STRICT

严格工作由 Agent 按计划项推进，跳过或取代某一项之前会先问你。Q3 使用可重放的 execution v2，并保留相同且独立的最终证明检查。日志命令在现有锁下写入 `.harness/plan-execution.yaml`。`harness plan begin` 只能开始规范顺序中的下一个未终态项。`block` 和 `plan resume` 只改变该项；它们不调用 `harness resume`，也不改变顶层任务状态。`refresh-proof` 替换当前 COMPLETE 证明。`upgrade-execution` 只在现有记录全部仍是 `PENDING` 时发布空的 v2 日志。

```bash
# 开始首个计划项前，先升级仍为 all-PENDING 的旧版 v1 execution。
harness plan upgrade-execution
harness plan begin P-001
harness plan block P-001 --reason "waiting on an accepted decision"
harness plan resume P-001

# 二选一：自动推导机械证明，
harness plan reconcile P-001 --auto
# 或显式提交证明。
harness plan reconcile P-001 --complete \
  --evidence unit-test-<digest> --surface src/example.py

# 仅在 evidence 或 changed surface 变化后刷新证明。
harness plan refresh-proof P-001 \
  --evidence unit-test-<new-digest> --surface src/example.py
```

`SKIPPED` 和 `SUPERSEDED` 是显式 `reconcile` 处置。Q3 的这两项必须有已接受的 Decision；`--auto` 不能创建它们，也不能创建 reason、Decision 或执行历史。省略 `--verbose` 时，默认 `harness plan status` 输出保持兼容。

风险只能升级，不能降级。Evidence reuse、soft budget、local telemetry、fixture benchmark 已提供；remote telemetry 和外部 agent benchmark 声明不提供。

<a id="transition-graph-and-command-admission"></a>

## 状态图与命令准入的区别

`state_machine.legal_targets(current)` 返回状态图上的后继状态，包含专属命令管理的边。某个目标属于返回集合，只说明状态图存在该边，**不代表**允许执行 `harness transition TARGET`，也不证明已经就绪。函数只接收状态，不读取任务或 profile，不检查证据、授权、publication 准入及其他守卫。普通 CLI status 不使用它展示可执行目标。

应使用负责该操作的命令：

| 状态图边／当前状态 | 实际路径 |
| --- | --- |
| `CREATED -> SPECIFYING` | 先执行 `harness task classify`；未分类任务不能绕过分类。 |
| 从 `CLASSIFIED` 出发 | `FAST` 进入 `IMPLEMENTING`；`STANDARD`／`STRICT` 进入 `SPECIFYING`。其他图后继不是可任选的 profile 入口。 |
| 从 `REVIEWING` 出发 | 通过 `harness review outcome` 选择评审结果路径，不能直接 transition。 |
| `GATING -> CONVERGED`／`BLOCKED` | 仅由 `harness gate` 记录 Gate 决策。 |
| 从 `BLOCKED` 出发 | 使用 `harness resume` 执行有类型的恢复；该命令不豁免授权要求。 |
| `VERIFYING -> GATING` | FAST 可经 `harness transition` 请求此迁移，但仍需通过检查；STANDARD／STRICT 必须先完成评审路径。 |

即使是普通命令管理的边，也可能因准入条件不足而拒绝。状态图校验、命令归属和动态就绪条件应分开理解；不要为适配某个命令裁剪共用状态图，也不要手改任务状态绕过拒绝。

## 边界

> **安全边界：** `harness evidence run --command` 以本地 Harness 操作者直接输入、受信任 shell 文本执行（`shell=True`）。

禁止将远程请求、配置值、API payload、CI 元数据或任何不可信输入转发给此选项。

Markdown checkbox 是 canonical Plan execution 的单向投影。它不是 Gate 输入，不是证明，也不是事实来源。`harness plan sync-markdown` 只修改显式仓库路径里的勾选字符。若 Plan 在任何执行历史出现前变更，`harness plan sync-fingerprint` 可刷新语义摘要；已有 item 或 transition 历史时会拒绝。

`--auto` 只能确立机械 `COMPLETE`。它选择有界的证据覆盖和已变更表面，再把一条普通 COMPLETE 请求交给现有的加锁核对路径。它不能选择 `SKIPPED` 或 `SUPERSEDED`。

### 恢复指引

Harness 错误可能包含建议命令 `Next:`。它只提供指引：Harness 永远不会自动执行建议命令。运行任何会修改状态的命令前先检查其含义。查询稳定诊断码的说明：

```bash
harness explain PLAN_STALE
harness explain CONTRACT_CHANGED
```

在 `PLANNED → IMPLEMENTING` 前，使用只读聚合检查器，在一次运行中报告彼此独立的 contract、test-plan、alignment、freeze 与 Plan 初始化缺陷：

```bash
harness check admission
```

**Gate 与 Finding 契约：** 只有 `harness gate` 可以评估或持久化产品 Gate 结果；直接运行 `python scripts/quality_gate.py` 已禁用。持久化 Finding 必须显式声明 category（`adversarial`、`diagnosability`、`complexity` 或 `interface`）；无 category 的旧记录以 `MIGRATION_REQUIRED` 失败。`finding.schema.json` 已删除，改用分类 Schema。

### 铁律

1. 任务状态存于 `.harness/current-task.yaml`，不能只存在模型上下文。
2. 状态转换受固定状态机控制。
3. 必须 Gate PASS 才可 `CONVERGED → DONE`。
4. CONFIRMED bug 必须有回归测试。
5. Evidence 必须新鲜，并绑定当前 Git HEAD/workspace。
6. 有界迭代耗尽进入 `ESCALATED`，不允许无限修复。
7. Markdown 不是 Gate 事实。权威来源仍是 canonical Plan YAML。
8. `--auto` 只记录机械 `COMPLETE`。语义上的 skip 和 supersede 仍是操作者的显式处置。

## 版本演进

```text
v0.1    State + Evidence + Gate
  ↓
v0.2    最小实现检查 + 复杂度 Review
  ↓
v0.2.3  Q0/Q1/Q2/Q3 风险自适应工作流
  ↓
v0.2.4  Test Plan → 可执行绑定 → fresh evidence
  ↓
v0.2.6  Production Diagnosability Contract + DIAG Finding + Gate
  ↓
v0.2.7  Task Ownership + Review Convergence + Gate Readiness
        + product freshness / canonical covered tests
  ↓
v0.2.8  Derived Context + Integrity + Host Usage + Multi-run Benchmark
  ↓
v0.2.9  实现前 Alignment 闭环与冻结
        + 合同 / 边界漂移诊断
  ↓
v0.2.10 Canonical Plan execution reconciliation
        + Q3 journal + Context/status + mechanical projections
  ↓
v0.3.0  Architecture Scope Gate P0
        + Architecture Context Projection P1
        + Architecture Evaluation P2
  ↓
v0.3.1  Task bootstrap + protected snapshots + immutable evidence fixes
```

`v0.3.1 current release` 修复 task bootstrap、protected snapshot 与 immutable evidence；既有 risk-adaptive、Context、Alignment 与 Plan Reconciliation safeguard 均保留。v0.3.0 新增 operator-authored Architecture model、确定性 ownership 与 Git attribution、Alignment seal v2、required-mode scope checks、有界 declared-plus-one-hop Context projection，以及彼此独立的 Drift Detection 与 Context Recovery experiments。Benchmark 结果保持 `PENDING`，直到外部 accepted run artifacts 为每个 fixture/arm 提供至少三次运行。不声明任何实测 benchmark 改进。见 [v0.3.0 架构设计](docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md)。

**Routing：** Q0 直接回答、不创建 task；Q1 / FAST 使用 RED/fix/GREEN/Light Gate；Q2 / STANDARD 与 Q3 / STRICT 使用完整 contract/review/Gate 流程。

## Engineering Quality

```text
                         Requirement
                             │
                             ▼
          Contract / Invariants / Test Plan
                             │
                             ▼
                    Implementation
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
     Correctness        Maintainability    Diagnosability
       Tests         Complexity Review   Logs / Trace Context
          │                  │                  │
          └──────────────────┼──────────────────┘
                             ▼
                  Evidence + Review + Findings
                             │
                             ▼
                 确定性质量门禁
                             │
                             ▼
                            DONE
```

Harness 负责状态、证据、Finding 生命周期和 Gate；Agent 判断业务语义与日志质量。Harness 不提供 logger SDK、OpenTelemetry、APM、自动插日志或通用源码扫描。

```text
Requirement
  ↓
Risk classification (CREATED → CLASSIFIED) → Task Contract (CLASSIFIED → PLANNED)
  ↓
Minimal Implementation Check — PREVENT
  ↓
Implementation / TDD (IMPLEMENTING)
  ↓
Verification + fresh evidence (VERIFYING)
  ↓
Complexity Reviewer — DETECT
  ↓
Adversarial review / finding reproduction (REVIEWING)
  ↓
Quality Gate (GATING)
  ↓
CONVERGED → DONE
```

## 仍然生效的规则

AI Coding 工作流常见问题：上下文丢失、Agent 自证完成、测试或证据过期、review finding 未复现、修复循环不收敛、功能正确但实现复杂度不必要。Harness 将这些风险变为可持久化、可检查控制：

```text
State + Contract + Invariant + Executable Test + Evidence + Deterministic Gate
```

| 层 | 职责 |
|---|---|
| Model | 推理和修改代码的 Worker |
| Superpowers | 设计、计划、TDD、review 等开发工作流 |
| Engineering Harness | 状态、合同、证据、finding、gate 控制器 |
| Tests / compiler / gate | 事实来源 |

Harness 适合 Agent 驱动功能开发和 bug 修复交付；不替代 CI、安全扫描或人工架构决策。

### FAST 仓库验证

FAST 默认要求 RED/GREEN 和 fresh build evidence。项目检查配置在 `gate.fast.verification`；typecheck 为 opt-in：

```yaml
fast:
  verification:
    build: required
    typecheck: optional
```

缺失、失败、过期的 required evidence 以 `FAST_REPOSITORY_VERIFICATION_MISSING` 阻塞并返回验证。授权只控制 Harness 动作；Harness 无法检测 outside Harness 执行的动作。

### Decision Record 与 Interface-first Contract

重要工程选择不能只留在聊天上下文。Agent 必须基于已知事实给出选项、推荐、理由、权衡和影响；用户确认后持久化为 Decision Record：

```bash
harness decision propose --topic cache --question "选择何种缓存？" --context "已有 Redis" --option local=进程内缓存 --option redis=共享缓存 --recommend redis --reason "复用现有基础设施"
harness decision accept DEC-001 --option redis
```

外部/public API、SDK、Plugin、Event、CLI 与跨模块 Service 边界，必须先声明 consumer、input/output/error semantics、compatibility 和 verification：

```bash
harness interface declare --name orders-api --kind http --consumer web-client --input "request schema" --output "response schema" --error "stable code" --compatibility compatible --rationale "additive field"
harness impact add-interface INT-001 --kind http --consumer web-client --compatibility compatible --contract-id INT-001
```

Q1 声明 external interface 会返回 `PUBLIC_INTERFACE_RISK_ESCALATION_REQUIRED`；必须显式升级 Q2/Q3。私有 helper 不需要 Interface Contract。Gate 会阻止未解决 Decision、缺 Contract/compatibility/verification，以及未授权 breaking change。

### FAST 风险边界

FAST 不通过关键词猜测 API/安全风险。在 `.harness/risk-boundaries.yaml` 声明变更风险路径：

```yaml
boundaries:
  q2: [src/**/api/**, schemas/**]
  q3: [auth/**, permissions/**, migrations/**]
```

无 policy 的业务变更以 `RISK_REVALIDATION_POLICY_MISSING` 阻塞；超过 Q1 的边界变更以 `RISK_ESCALATION_REQUIRED` 阻塞。显式升级：

```bash
harness task escalate --level Q2 --reason "public contract changed"
```

仅 `docs/`、`tests/`、`test/`、根目录 Markdown 变更无需 policy。

<!-- path-identities -->
**两套路径身份：**`workspace_fingerprint` 绑定产品新鲜度，包含代码、测试、文档与配置，仅排除 `.harness/` 控制数据。修改已跟踪测试或文档（或符合条件的未跟踪文件）会使旧证据和 Context 变陈旧。`business_paths` 过滤 FAST 风险升级使用的路径，排除 `.harness/`、`docs/`、`tests/`、`test/` 及根目录 Markdown（如 `README.md`）。风险策略排除不等于豁免新鲜度检查，也不授权跳过必需测试或错误分类公共接口/安全变更。上述目录外的嵌套 Markdown 仍属于业务风险路径。此处说明现有策略，不新增语义风险推断。
<!-- /path-identities -->

### 任务身份保留

`task new`、`task recover`、`task migrate-id` 拒绝复用当前任务、history 归档名／任务文档、持久化 Decision 记录／索引中已有的 ID。前导零别名（`TASK-5`／`TASK-005`）按同一数值身份处理。在现有 publication 锁内、替换复制或身份写入之前，以退出码 2、`TASK_ID_ALREADY_USED` 拒绝。应选未使用 ID，不要删历史或决策绕过守卫。

`task new` 不再继承根 `.harness/behavior-fixtures`，不会遍历或复制该项。原件随旧任务完整保留在命令报告的 `.publication-retained/task-replacement-…/previous/` 目录中，不删除，也不建立可写链接。因此新任务下原规范夹具路径将不存在；需要复用时，应显式将必要数据复制到新任务自有位置。`task recover`、`task escalate` 和其他路径保持原有复制行为；这不是通用清理或迁移命令。此规则仅针对根目录，不排除嵌套的同名 `behavior-fixtures` 目录。

赋予不同身份时，占用来源不可读、结构非法或含符号链接，以 `TASK_ID_RESERVATION_INVALID` 拒绝；先诊断来源，不能把读取失败当作无占用。仅当所有 scope 工件均不存在时，legacy `migrate-id` 可修复非法的当前 ID 字符串；目标仍须合法且未占用，history／Decision／索引校验不跳过。当前 `task.id: null` 仍是合法的未分配身份，不属于非法字符串；既有 legacy 身份赋值与 genesis scope 绑定继续支持。其他非字符串当前 ID 或缺失任务结构仍拒绝。`new`／`recover` 的占用检查及既有 scope 绑定限制保持不变。历史重号不批量改写，也不妨碍使用真正空闲的 ID。迁移前既有的显式 publication recovery 仍执行。

例外：legacy 迁移到完全相同的当前 ID 不创建新身份，也不重新扫描占用来源。它不验证或修复损坏的历史／决策，不认证完整性、不创建 scope、不接受决策、不授予 Gate 资格；原有 legacy 保存路径仍可能重写任务／telemetry。可运行 `harness explain TASK_ID_ALREADY_USED` 或 `harness explain TASK_ID_RESERVATION_INVALID` 获取只读引导；两者均不改状态、不执行恢复。

守卫仅检查当前身份、history 直属名称／任务文档及 Decision 归属，不遍历探针、验收转储或 retained 树。这不是所有权威痕迹已被移除后的永久身份注册表。归档已裁剪但决策仍在时，决策仍保留其 task ID。

### 证据复用

复用必须显式请求，且只限当前 task：

```bash
harness evidence run --type build --command "python -m pip wheel . --no-deps" --reuse-if-valid
```

`EVIDENCE_REUSED` 表示未运行命令。复用要求之前成功、命令/证明身份完全一致、HEAD 与 product workspace fingerprint 未变、运行时完全一致。任一不匹配都会正常执行命令。

收集器只在前置检查与落盘时短暂持锁；外部命令执行期间**不持根锁**，允许子命令再次调用 Harness。落盘时核对根目录/任务身份，向最新任务合并预算增量，并将不可覆盖的 receipt 与任务/telemetry 作为有界 native bundle 发布。预算仍是前置软限制，不承诺并发执行的硬额度预占。

命令执行后准入或发布失败且未确定持久提交时，收集器返回 `2`，不自动重跑或恢复。若已确定 `COMMITTED`，仅后续 stage 归档或发布器清理失败，则报告 `PUBLICATION_COMMITTED_CONTEXT` 和 `EVIDENCE_PUBLICATION_COMMITTED`：canonical 收据与预算已落盘，采集成功（取消仍返回 `130`）。不要为修复归档重跑命令；精确匹配且有效的证明可通过 `--reuse-if-valid` 复用，不再次执行或计预算。`EVIDENCE_RESULT_RETAINED: <path>` 指向系统临时目录 `harness-evidence-attempt-*` 下权限受限的非 canonical `result.json`；测量结果**不是已接受、可复用的证明**。若发布已完成但输出/解锁失败，报告 `EVIDENCE_PERSISTENCE_UNCERTAIN`，重试前先核对 canonical 状态。取消仍返回 `130`；普通命令失败/超时记录在 receipt 的 `exit_code`，不等于收集失败。保留失败会明确报告。保留对象可能包含命令/输出数据、持续占用磁盘且无自动清理；临时目录保留不保证断电或 OS 清理后仍存在。

### 实际测试执行证明

测试 receipt 必须带实际 pytest 子进程生成的 `test_execution`，不能仅凭命令字符串匹配声明覆盖。文件／函数级声明包含全部已收集的参数化用例；被过滤、跳过或未执行的成员不能证明整个目标。过滤执行应声明实际执行的具体节点。

RED 必须由每个声明目标的实际 call 阶段断言型失败（含 pytest 期望失败）支撑，退出码为 1，且没有 collection/setup/teardown/internal 错误。检查器中未处理的 `KeyError`、超时、取消、collect-only 都不是 RED；应将预期产品行为写成断言，并单独诊断设置错误。断言是否对应真实需求仍需人工审阅。

收集器向子进程加入私有独立 pytest reporter，不注入 Harness 源码；测试内部的嵌套 pytest 不算独立证明。合格命令 profile 限单一串行原生 pytest，保留 reporter，可带字面量环境赋值（支持 `env`）、`cd ... &&` 前缀及透明的 `sh/bash/zsh -c/-lc` 包装。复合顺序、管道、OR／后台命令、重定向、替换及任意程序包装仅保存测量，即使最后 pytest 通过也不能授予证明，防止前置失败被掩盖；远程／Vitest selector 解析不等于执行证明。未报告／未支持的 runner（含未经验证的 worker／传输适配）仍可记录测量，但不能证明覆盖、RED/GREEN 或复用。旧 receipt 保留原样；缺少实际执行记录以 `EVIDENCE_TEST_EXECUTION_INVALID` 阻断，不自动升级。collector exit 0 仅表示已保存，不表示证明合格。本地受信执行不是 OS sandbox 或可执行程序身份认证：所选 executable/module/plugin/conftest 代码受信。同名自定义 `pytest`／`python` 包装器可在内部吞掉前提失败，basename 分类无法识别；应使用已知测试程序，单独收集前提。显式 worker／传输参数（`-n`、`--numprocesses`、`--dist`、`--tx`、`-d`）仅保存测量；reporter 也拒绝 ini／环境注入的有效 worker 配置。这不等于 xdist 已获验证。

wheel 从干净源码快照构建，并逐项核对实际载荷；不会清理或复用旧 `build/` 缓存。

### 产品 evidence freshness 与 covered-test 路径

Test/build evidence 相对 **product workspace fingerprint** 判断是否 fresh（产品代码、测试、依赖、非 control-plane 配置）。另有 **control-plane fingerprint** 覆盖 `.harness/` 任务状态、evidence 文件、review 结果、requirement/invariant verification metadata。

写入 control-plane 记录不会使产品证明 stale。收集相关测试后，执行 `harness requirement verify`、`harness invariant verify`、complexity/diagnosability review、`harness review outcome` 可以更新 `.harness/`，无需因此重跑产品测试。修改产品代码、产品测试或任务纳入的非 control-plane 配置仍会标记 `EVIDENCE_WORKSPACE_STALE`。篡改 evidence payload、无效 binding、无效 control-plane schema 仍阻断 Gate；这些失败不会被报告成产品测试 stale。

Covered tests 存储为仓库根目录 canonical path。命令 `cd` 进入子项目时，仍绑定 test plan 的根路径：

```bash
harness evidence run --type unit_test --scope related \
  --covered-test backend/tests/foo.py \
  --command "sh -lc 'cd backend && pytest tests/foo.py'"

harness evidence run --type unit_test --scope related \
  --covered-test agents-frontend/src/__tests__/foo.spec.ts \
  --command "sh -lc 'cd agents-frontend && npx vitest run src/__tests__/foo.spec.ts'"

harness evidence run --type unit_test --scope related \
  --covered-test agents-frontend/src/__tests__/foo.spec.ts \
  --command "sh -lc 'cd agents-frontend && npm run test:unit -- --run src/__tests__/foo.spec.ts'"
```

同一测试在仓库根目录或子项目目录执行，存储相同 canonical covered-test path。canonical path 不存在、逃逸仓库、无效相对 `cd`、或 selector 未在命令中执行时，收集拒绝绑定（`COVERED_TEST_NOT_EXECUTED`、`COVERED_TEST_PATH_INVALID`）。绑定 `--covered-test` 时，`npm run <script>` 必须能静态解析为 pytest 或 `vitest run`，否则 `TEST_RUNNER_UNRESOLVED`。不带 covered-test 的 build/lint `npm run` 不按缺失测试 runner 处理。旧 evidence 中的 cwd-relative selector 仍可绑定；下一次 collection 会迁移为 canonical path。

### 自适应运行

Evidence blocker 用 `harness resume` 恢复；review 测试缺口用 `harness review outcome VERIFICATION_GAP --reason-code TEST_COVERAGE_INSUFFICIENT`。禁止直接 state shortcut。

FAST evidence budget 为 soft：test 2、build 1、相同失败 retry 1。超预算必须提供全部 override 字段：

```bash
harness evidence run --type build --command "python -m pip wheel ." --budget-override-reason "new evidence" --budget-override-evidence build.json --budget-override-hypothesis "packaging path"
```

已分类的 mutating task 可生成经过验证的派生 Context：

```bash
harness context                   # compact YAML，保留完整 Control Core
harness context --full --json
harness context validate           # 只读；不重新生成 stale Context
harness context explain --json     # 解释已保存的选择结果
```

最近一次成功快照保存在 `.harness/context/{current,manifest,evidence}.yaml`，由同一 `context_hash` 关联。Integrity 失败返回 2，不输出 Context 正文。发布使用共享锁及异常回滚；尚不提供进程强制终止后的崩溃原子恢复。Context Evidence 只记录 Harness 生成了什么，不证明 Agent 实际消费，也不作为 Gate 的 product evidence。不会创建或推进任务；Q0 不进入此流程。已支持显式扩大：`harness context expand --trigger INSUFFICIENT_CONTEXT --reason "需要依赖上下文"`。命令记录 task-bound 事件、递增 `budget.context_expansions`，按 LOCAL → BOUNDED → EXPANDED 升级，不改变 risk 或授权。随后重新运行 `harness context` 刷新已 stale 的快照。生成时会自动记录越界的开放 finding 和 ACCEPTED decision，按 task、trigger、对象 ID、相关路径/scope 指纹去重。控制事件先落盘，再重建派生快照。失败 evidence 的 `covered_tests` 不在 Working Set 时也会触发扩大。已有风险升级历史生成 `RISK_ESCALATED` 事件，不额外增加 policy 等级。Integrity 失败仍 fail-closed，不通过 expansion 绕过校验。

仅本地 telemetry：`harness telemetry show`，测量 `elapsed_seconds`、`harness_command_calls`、evidence counts。宿主可通过 `harness telemetry report --usage-file <path>` 上报 usage；文件支持 JSON/YAML，相对路径以命令调用目录为准：

```json
{"task_id":"TASK-101","usage":{"total_tokens":1234,"source":"runtime","tool_calls":12}}
```

上报当前任务的累计快照，不是增量；重复快照幂等，省略字段变为 null。`save_task` 保留 usage，新任务不继承旧 usage。计数只能为非负整数或 null；任一 token 有值时必须给出 `source: runtime|provider|estimated`，三项 token 齐全时 input + output 必须等于 total。任务缺失、ID 不匹配、非法 usage 均退出 2。usage 是本地宿主输入，不是独立认证的供应商证据；Harness 不猜测不可见的 agent 调用，不运行 tokenizer。未上报保持 null，历史 `token_estimate: null` 不变；可上报不代表已证明效率提升。运行 fixture validation：`harness benchmark run --fixtures benchmarks/fixtures`。

比较已记录的 baseline/adaptive artifacts：

```bash
harness benchmark compare --fixtures benchmarks/fixtures --baseline baseline-artifacts --adaptive adaptive-artifacts

# v0.2.9：从显式持久化 records 输出 Alignment 指标
harness benchmark alignment --records alignment-records.yaml
```

stdout 分别列出历史 `overall:` 与 v0.2.9 `experiment:`。缺 usage 或不完整 runs 时 experiment 为 `INCONCLUSIVE`；即使 overall 是 `CORRECTNESS_PRESERVED`，也不表示效率已通过。每个 fixture-required correctness 字段必须在两侧均为 true。缺少 proof 为 `INCONCLUSIVE`，不能声称 correctness preserved。Harness 不运行或证明 external agent runs、tokens、tool calls。

### 自动编排

当 Engineering Harness Skill 控制任务时，它会在 `PLANNED` 自动调用 Minimal Implementation Check、在 `VERIFYING` 前记录 impact analysis、在验证全绿后且 `REVIEWING` 前调用 Complexity Reviewer。状态 guard 拒绝跳过记录。全量测试始终禁止；只运行明确列出的影响相关测试。

## v0.2：必要复杂度

实现前，Minimal Implementation Check 记录 Decision Ladder。按顺序搜索：是否必要、仓库复用、stdlib、平台原生能力、已安装依赖、本地实现，最后才增加最小新 abstraction。

```bash
harness check minimal --file minimal-implementation.yaml
```

验证后，Complexity Reviewer 审查变更 diff，仅能创建具备证据的 DELETE、REUSE、STDLIB、NATIVE、YAGNI、SHRINK 类型 `CPLX-*` finding。

```bash
harness review complexity --file complexity-review.yaml
# 可选 override：harness review complexity --base origin/main --file complexity-review.yaml
```

开放 HIGH complexity finding 阻塞 gate；MEDIUM 和 LOW 仅提示。安全、授权、审计、兼容性、迁移、无障碍和 NFR 所需复杂度不自动视为过度设计。Complexity review 默认使用任务 Git baseline，包含已提交、staged、unstaged 和相关 untracked 变更；`--base` 仅作显式 override。

## 生产可诊断性（v0.2.6）

Q0 跳过可诊断性；Q1 可执行业务 ID、异常上下文、敏感数据的 Agent advisory 检查，但仅用于路由，不构成持久化 Core/Gate 证明。Q2 仅当 Contract 要求时创建 `.harness/observability.yaml` 并执行 `harness review diagnosability`；Q3 始终要求有效 applicability 与 fresh review evidence。Harness 校验 artifact 与 Gate，不提供日志 SDK、OpenTelemetry、自动插日志或通用源码扫描。

## 依赖与 token 使用

Harness 依赖 Superpowers worker Skills，尤其 brainstorming、writing-plans、TDD、review、verification。Harness 控制交付闭环，不复制这些能力。

推荐 Caveman Mode 减少 Agent 输出 token。代码、命令、错误、evidence 和状态必须保持技术信息完整。

## 文档与开发

- [架构全景图](docs/architecture.md)
- [Evidence freshness 与测试路径绑定](docs/2026-09-07-evidence-freshness-and-test-path-binding-issues.md)
- [v0.2.2 flow hardening 设计](docs/superpowers/specs/2026-08-26-v022-flow-hardening-design.md)
- [v0.2 设计](docs/superpowers/specs/2026-08-25-v02-minimal-complexity-design.md)
- [完整生命周期示例](docs/worked-example.md)
- [历史 v0.1 实施手册](docs/engineering-harness-v0.1.md)

只运行明确列出的影响相关测试。package metadata 区域示例：

```bash
python -m pytest tests/test_version_consistency.py tests/test_readme_docs.py -q
```

## 许可证

Apache-2.0 © 2026 Yezhiwei

# Superpowers Engineering Harness v0.3.0

[English](README.md)

Engineering Harness 是 [Superpowers](https://github.com/obra/superpowers) 开发工作流外层的确定性控制平面。它不替代 Agent 或 worker Skill；它持久化任务状态、要求可验证证据，并阻止 Agent 未经 Gate 批准就宣称任务完成。

[架构全景图](docs/architecture.md)

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
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-pi.sh | bash -s -- v0.3.0
```

安装器检查是否已配置 Superpowers，仅在缺失时安装；同时协调固定版本的 Harness Pi skills，把匹配 Python CLI 安装到隔离用户环境，并暴露 `~/.local/bin/harness`。如果 `~/.local/bin` 不在 `PATH`，安装器会给出提示。重复安装相同版本保持幂等。若本地安全策略要求，请先审查下载脚本再执行。

源码开发时，另行使用 `python -m pip install -e /path/to/superpowers-engineering-harness` 安装可编辑环境。

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
curl -fsSL https://raw.githubusercontent.com/yezhwi/superpowers-engineering-harness/main/scripts/install-agy.sh | bash -s -- v0.3.0
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

## 边界

> **安全边界：** `harness evidence run --command` 以本地 Harness 操作者直接输入、受信任 shell 文本执行（`shell=True`）。

禁止将远程请求、配置值、API payload、CI 元数据或任何不可信输入转发给此选项。

Markdown checkbox 是 canonical Plan execution 的单向投影。它不是 Gate 输入，不是证明，也不是事实来源。`harness plan sync-markdown` 只修改显式仓库路径里的勾选字符。

`--auto` 只能确立机械 `COMPLETE`。它选择有界的证据覆盖和已变更表面，再把一条普通 COMPLETE 请求交给现有的加锁核对路径。它不能选择 `SKIPPED` 或 `SUPERSEDED`。

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
```

`v0.3.0 current release`；既有 risk-adaptive、Context、Alignment 与 Plan Reconciliation safeguard 均保留。v0.3.0 新增 operator-authored Architecture model、确定性 ownership 与 Git attribution、Alignment seal v2、required-mode scope checks、有界 declared-plus-one-hop Context projection，以及彼此独立的 Drift Detection 与 Context Recovery experiments。Benchmark 结果保持 `PENDING`，直到外部 accepted run artifacts 为每个 fixture/arm 提供至少三次运行。不声明任何实测 benchmark 改进。见 [v0.3.0 架构设计](docs/Superpowers-Engineering-Harness-v0.3.0-Architecture-Scope-and-Drift-Design.md)。

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

### 证据复用

复用必须显式请求，且只限当前 task：

```bash
harness evidence run --type build --command "python -m pip wheel . --no-deps" --reuse-if-valid
```

`EVIDENCE_REUSED` 表示未运行命令。复用要求之前成功、命令/证明身份完全一致、HEAD 与 product workspace fingerprint 未变、运行时完全一致。任一不匹配都会正常执行命令。

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

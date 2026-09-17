# Superpowers Engineering Harness v0.2.8

[English](README.md)

`v0.2.8 current release`；v0.2.7 的 risk-adaptive workflow、Task Ownership、review recovery、evidence、Gate、Decision 和 Interface safeguard 均保留。v0.2.8 新增经过校验的派生 Context 与 fail-closed Integrity、task-bound usage 上报和 multi-run Benchmark 报告。Benchmark 效率结论要求完整 runtime 数据；缺失 metric 保持 `INCONCLUSIVE`，已知 correctness 或 integrity 失败优先。见 [v0.2.8 实现契约](docs/Superpowers-Engineering-Harness-v0.2.8-Implementation-Contract.md)。

**Routing：** Q0 直接回答、不创建 task；Q1 / FAST 使用 RED/fix/GREEN/Light Gate；Q2 / STANDARD 与 Q3 / STRICT 使用完整 contract/review/Gate 流程。

[架构全景图](docs/architecture.md)

Engineering Harness 是 [Superpowers](https://github.com/obra/superpowers) 开发工作流外层确定性控制平面。它不替代 Agent 或 worker Skill；它持久化任务状态、要求可验证证据，并阻止 Agent 未经 Gate 批准就宣称任务完成。

## 生产可诊断性（v0.2.6）

Q0 跳过可诊断性；Q1 可执行业务 ID、异常上下文、敏感数据的 Agent advisory 检查，但仅用于路由，不构成持久化 Core/Gate 证明。Q2 仅当 Contract 要求时创建 `.harness/observability.yaml` 并执行 `harness review diagnosability`；Q3 始终要求有效 applicability 与 fresh review evidence。Harness 校验 artifact 与 Gate，不提供日志 SDK、OpenTelemetry、自动插日志或通用源码扫描。

## 解决什么问题

AI Coding 工作流常见问题：上下文丢失、Agent 自证完成、测试或证据过期、review finding 未复现、修复循环不收敛、功能正确但实现复杂度不必要。

Harness 将这些风险变为可持久化、可检查控制：

```text
State + Contract + Invariant + Executable Test + Evidence + Deterministic Gate
```

## 设计原理

| 层 | 职责 |
|---|---|
| Model | 推理和修改代码的 Worker |
| Superpowers | 设计、计划、TDD、review 等开发工作流 |
| Engineering Harness | 状态、合同、证据、finding、gate 控制器 |
| Tests / compiler / gate | 事实来源 |

Harness 适合 Agent 驱动功能开发和 bug 修复交付；不替代 CI、安全扫描或人工架构决策。

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
```

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

## 流程

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

铁律：

1. 任务状态存于 `.harness/current-task.yaml`，不能只存在模型上下文。
2. 状态转换受固定状态机控制。
3. 必须 Gate PASS 才可 `CONVERGED → DONE`。
4. CONFIRMED bug 必须有回归测试。
5. Evidence 必须新鲜，并绑定当前 Git HEAD/workspace。
6. 有界迭代耗尽进入 `ESCALATED`，不允许无限修复。

## 5 分钟上手

安装 worker 工作流、Harness Skills 和确定性 CLI：

```bash
pi install git:github.com/obra/superpowers
pi install git:github.com/yezhwi/superpowers-engineering-harness
pip install -e /path/to/superpowers-engineering-harness
```

初始化目标仓库；每个会话从持久化状态开始：

```bash
cd your-project
harness init
harness status
```

向 Agent 发起 Harness 工作，例如：

```text
Use Engineering Harness to fix this bug: cancelling an order twice issues two refunds.
```

Pi 安装 Skills 后需新开会话。Skills 在会话启动时加载。

## 日常使用

> **安全边界：** `harness evidence run --command` 以本地 Harness 操作者直接输入、受信任 shell 文本执行（`shell=True`）。

禁止将远程请求、配置值、API payload、CI 元数据或任何不可信输入转发给此选项。

**Gate 与 Finding 契约：** 只有 `harness gate` 可以评估或持久化产品 Gate 结果；直接运行 `python scripts/quality_gate.py` 已禁用。持久化 Finding 必须显式声明 category（`adversarial`、`diagnosability`、`complexity` 或 `interface`）；无 category 的旧记录以 `MIGRATION_REQUIRED` 失败。`finding.schema.json` 已删除，改用分类 Schema。

正常成功路径（`review outcome PASS` 执行 `REVIEWING → GATING`）：

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

阻塞恢复路径（`harness gate` 输出 `DECISION: CONTINUE`；Gate 持久化 blocker，`harness resume` 按 code 推导目标状态）：

```bash
harness gate
# 仅在 DECISION: CONTINUE 后
harness resume
```

进入 `VERIFYING` 前记录影响范围和关联测试。全量测试需显式授权：

```bash
harness impact add-change src/orders/cancel.py
harness impact add-test tests/test_cancel.py::test_duplicate_cancel_single_refund
harness authorize full-suite
harness evidence run --type unit_test --scope full_suite --command "pytest"
```

会话中断后运行 `harness status`；Harness 从 `.harness/current-task.yaml` 恢复。`status` 是只读 projection；Gate 阻塞后运行 `harness resume`，Harness 按 typed blocker code 自动选择正确恢复状态，不信任持久化 `recover_to`。Review reason code 为受控集合，例如 `TEST_COVERAGE_INSUFFICIENT`、`EVIDENCE_INCOMPLETE`、`LOGIC_ERROR`。

### 风险自适应流程（v0.2.3）

- **Q0：** 直接回答；不创建 Harness task。
- **Q1 / FAST：** 仅限范围窄、低风险工作。必须显式分类；当前业务路径已命中 `.harness/risk-boundaries.yaml` 的 Q2/Q3 时，Q1 分类失败且不落盘。FAST 仍要求 task 级失败 RED、成功 GREEN 证据和 Light Gate，但跳过 impact、复杂度审查、requirements、invariants ceremony。`harness status` 的 Build/Unit/Integration 摘要与 Evidence 列表使用同一 live projection。若 work item 已在目标分支实现，用 `harness task verify-existing` 记录有效 existing-verification，禁止伪造 RED；普通缺陷修复仍走 RED→GREEN。`requires_reproduction` 保持 task 为 `CLASSIFIED`，创建或恢复 finding 后正常复现。
- **Q2 / STANDARD** 与 **Q3 / STRICT：** 使用现有完整 Harness 流程。风险只能升级，不能降级。

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

FAST 不授予外部操作权限。每种授权在当前 task 内独立；只授权用户请求的动作：

```bash
harness authorize commit
harness authorize full-suite
harness authorize push
# 另有 create-mr、ready-mr、merge、deploy；用 revoke-<action> 撤销
```

Evidence reuse、soft budget、local telemetry、fixture benchmark 已提供；remote telemetry 和外部 agent benchmark 声明不提供。

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

同一测试在仓库根目录或子项目目录执行，存储相同 canonical covered-test path。canonical path 不存在、逃逸仓库、无效相对 `cd`、或 selector 未在命令中执行时，收集拒绝绑定（`COVERED_TEST_NOT_EXECUTED`、`COVERED_TEST_PATH_INVALID`）。`npm run <script>` 仅在命令 cwd 的 `package.json` 脚本可静态解析为 pytest 或 `vitest run` 时生效；否则以 `TEST_RUNNER_UNRESOLVED` 失败。旧 evidence 中的 cwd-relative selector 仍可绑定；下一次 collection 会迁移为 canonical path。

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
```

stdout 分别列出历史 `overall:` 与 v0.2.8 `experiment:`。缺 usage 或不完整 runs 时 experiment 为 `INCONCLUSIVE`；即使 overall 是 `CORRECTNESS_PRESERVED`，也不表示效率已通过。每个 fixture-required correctness 字段必须在两侧均为 true。缺少 proof 为 `INCONCLUSIVE`，不能声称 correctness preserved。Harness 不运行或证明 external agent runs、tokens、tool calls。

### 自动编排

当 Engineering Harness Skill 控制任务时，它会在 `PLANNED` 自动调用 Minimal Implementation Check、在 `VERIFYING` 前记录 impact analysis、在验证全绿后且 `REVIEWING` 前调用 Complexity Reviewer。状态 guard 拒绝跳过记录。全量测试授权仍必须由人类显式决定。

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

```bash
python -m pytest tests/ -q
```

## 许可证

Apache-2.0 © 2026 Yezhiwei

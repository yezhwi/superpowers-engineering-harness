# Superpowers Engineering Harness v0.2.2

[English](README.md)

`v0.2.2 current release`；`main` 包含 unreleased v0.2.3 risk-adaptive behavior。

**Routing：** Q0 直接回答、不创建 task；Q1 / FAST 使用 RED/fix/GREEN/Light Gate；Q2 / STANDARD 与 Q3 / STRICT 使用完整 contract/review/Gate 流程。

Engineering Harness 是 [Superpowers](https://github.com/obra/superpowers) 开发工作流外层确定性控制平面。它不替代 Agent 或 worker Skill；它持久化任务状态、要求可验证证据，并阻止 Agent 未经 Gate 批准就宣称任务完成。

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

## 流程

```text
Requirement
  ↓
Task Contract (CREATED → PLANNED)
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

正常成功路径（`review outcome PASS` 执行 `REVIEWING → GATING`）：

```bash
harness status
harness transition IMPLEMENTING
harness evidence --type unit_test --command "pytest tests/test_cancel.py"
harness transition VERIFYING
harness review complexity --file review.yaml
harness transition REVIEWING
harness review outcome PASS --reason-code REVIEW_CLEAN
harness gate
harness transition DONE
```

阻塞恢复路径（`harness gate` 执行 `GATING → BLOCKED`；`harness resume` 按 blocker code 推导目标状态）：

```bash
harness gate
harness resume
```

进入 `VERIFYING` 前记录影响范围和关联测试。全量测试需显式授权：

```bash
harness impact add-change src/orders/cancel.py
harness impact add-test tests/test_cancel.py::test_duplicate_cancel_single_refund
harness authorize full-suite
harness evidence --type unit_test --scope full_suite --command "pytest"
```

会话中断后运行 `harness status`；Harness 从 `.harness/current-task.yaml` 恢复。`status` 是只读 projection；Gate 阻塞后运行 `harness resume`，Harness 按 typed blocker code 自动选择正确恢复状态，不信任持久化 `recover_to`。Review reason code 为受控集合，例如 `TEST_COVERAGE_INSUFFICIENT`、`EVIDENCE_INCOMPLETE`、`LOGIC_ERROR`。

### 风险自适应流程（v0.2.3）

- **Q0：** 直接回答；不创建 Harness task。
- **Q1 / FAST：** 仅限范围窄、低风险工作。必须显式分类；FAST 仍要求 task 级失败 RED、成功 GREEN 证据和 Light Gate，但跳过 impact、复杂度审查、requirements、invariants ceremony。
- **Q2 / STANDARD** 与 **Q3 / STRICT：** 使用现有完整 Harness 流程。风险只能升级，不能降级。

```bash
harness task classify --level Q1 --scope low --contract none --data none \
  --authorization none --security none --concurrency none --deployment none
harness transition IMPLEMENTING
# 修复前记录失败 regression proof，修复后记录通过 proof
harness evidence --type unit_test --phase red --covered-test tests/test_x.py::test_x --command "pytest tests/test_x.py::test_x"
harness evidence --type unit_test --phase green --covered-test tests/test_x.py::test_x --command "pytest tests/test_x.py::test_x"
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
harness evidence --type build --command "python -m pip wheel . --no-deps" --reuse-if-valid
```

`EVIDENCE_REUSED` 表示未运行命令。复用要求之前成功、命令/证明身份完全一致、HEAD/workspace 未变、运行时完全一致。任一不匹配都会正常执行命令。

### 自适应运行

Evidence blocker 用 `harness resume` 恢复；review 测试缺口用 `harness review outcome VERIFICATION_GAP --reason-code TEST_COVERAGE_INSUFFICIENT`。禁止直接 state shortcut。

FAST evidence budget 为 soft：test 2、build 1、相同失败 retry 1。超预算必须提供全部 override 字段：

```bash
harness evidence --type build --command "python -m pip wheel ." --budget-override-reason "new evidence" --budget-override-evidence build.json --budget-override-hypothesis "packaging path"
```

仅本地 telemetry：`harness telemetry show`。它测量 `elapsed_seconds`、`harness_command_calls`、evidence counts；agent metrics 不可用：`token_estimate: null`，tool calls/search rounds 为 null。运行 fixture validation：`harness benchmark run --fixtures benchmarks/fixtures`。

比较已记录的 baseline/adaptive artifacts：

```bash
harness benchmark compare --fixtures benchmarks/fixtures --baseline baseline-artifacts --adaptive adaptive-artifacts
```

每个 fixture-required correctness 字段必须在两侧均为 true。缺少 proof 为 `INCONCLUSIVE`，不能声称 correctness preserved。Harness 不运行或证明 external agent runs、tokens、tool calls。

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

- [v0.2.2 flow hardening 设计](docs/superpowers/specs/2026-08-26-v022-flow-hardening-design.md)
- [v0.2 设计](docs/superpowers/specs/2026-08-25-v02-minimal-complexity-design.md)
- [完整生命周期示例](docs/worked-example.md)
- [历史 v0.1 实施手册](docs/engineering-harness-v0.1.md)

```bash
python -m pytest tests/ -q
```

## 许可证

Apache-2.0 © 2026 Yezhiwei

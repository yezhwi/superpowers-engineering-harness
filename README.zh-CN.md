# Superpowers Engineering Harness v0.2

[English](README.md)

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

```bash
harness status
harness transition IMPLEMENTING
harness evidence --type unit_test --command "pytest tests/test_cancel.py"
harness transition VERIFYING
harness gate
harness converge
```

进入 `VERIFYING` 前记录影响范围和关联测试。全量测试需显式授权：

```bash
harness impact add-change src/orders/cancel.py
harness impact add-test tests/test_cancel.py::test_duplicate_cancel_single_refund
harness authorize full-suite
harness evidence --type unit_test --scope full_suite --command "pytest"
```

会话中断后运行 `harness status`；Harness 从 `.harness/current-task.yaml` 恢复。

## v0.2：必要复杂度

实现前，Minimal Implementation Check 记录 Decision Ladder。按顺序搜索：是否必要、仓库复用、stdlib、平台原生能力、已安装依赖、本地实现，最后才增加最小新 abstraction。

```bash
harness check minimal --file minimal-implementation.yaml
```

验证后，Complexity Reviewer 审查变更 diff，仅能创建具备证据的 DELETE、REUSE、STDLIB、NATIVE、YAGNI、SHRINK 类型 `CPLX-*` finding。

```bash
harness review complexity --file complexity-review.yaml
```

开放 HIGH complexity finding 阻塞 gate；MEDIUM 和 LOW 仅提示。安全、授权、审计、兼容性、迁移、无障碍和 NFR 所需复杂度不自动视为过度设计。

## 依赖与 token 使用

Harness 依赖 Superpowers worker Skills，尤其 brainstorming、writing-plans、TDD、review、verification。Harness 控制交付闭环，不复制这些能力。

推荐 Caveman Mode 减少 Agent 输出 token。代码、命令、错误、evidence 和状态必须保持技术信息完整。

## 文档与开发

- [v0.2 设计](docs/superpowers/specs/2026-08-25-v02-minimal-complexity-design.md)
- [完整生命周期示例](docs/worked-example.md)
- [历史 v0.1 实施手册](docs/engineering-harness-v0.1.md)

```bash
python -m pytest tests/ -q
```

## 许可证

Apache-2.0 © 2026 Yezhiwei

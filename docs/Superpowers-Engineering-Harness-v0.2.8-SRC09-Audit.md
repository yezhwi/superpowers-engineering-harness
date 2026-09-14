# v0.2.8 SRC-09 源登记审计

## 最新接入证据

生产 build/validate 已接入受控读取范围，未知 Gate/Selector open 与吞异常路径有专属拒绝测试。`src09_probe.py` 加 `git_source_scope_probe.py` 本轮 **5 passed in 7.92s**。原未知文件自动 hash 探针依已批准设计改为“显式登记后变化 stale”，并保留独立未知读取拒绝探针；不是改成扫描所有未知文件。

以下 RED 数量为历史记录。SRC-09 仍待 bootstrap、元数据查询、依赖闭包与资源边界独立复审，不能仅凭探针全绿签收。

## 修复进展（后续轮次）

已在 `context/freshness.py` 登记 `risk.user_changes.paths` 的字面路径；复用 contained-path/file-version 检查，不改变 Gate 或 product fingerprint。

- 新增 `tests/test_context_protected_freshness.py`：首次 9 failed / 1 passed，修复后 10 passed；覆盖修改、出现、删除、空列表、越界、外部 symlink、构建中变更及字面 `*`/`::` 文件名。
- 本探针重新执行：**2 failed, 2 passed in 4.89s**。真实 FAST 漏项与已登记对照 GREEN；未知读取机制两个探针仍 RED。
- 相关回归：**447 passed in 360.95s**，不是全量；未做独立 reviewer 复审。
- 同构排查：普通 scope glob/test selector 保持原规则；FAST 保护路径按 Gate 实际字面文件读取规则登记，不复用 selector 截断。未引入新锁。
- SRC-09 仍未关闭。以下保留修复前审计记录，不作为当前失败数量。

## 结论与范围

基线：`main` / `d6a2438` 加未提交 Context 实现。仅审计、隔离探针与文档；未修改 Gate/产品实现、未运行全量、未推进 `.harness` 任务。不是独立 reviewer 复审。

发现两类不同问题：

1. **机制缺口，已由注入探针证实**：未登记的新增 Gate 控制读取不会自动阻止 Context 发布。静态清单不满足 SRC-09 的未知输入 fail-closed 要求。
2. **当前读取漏项，已无注入复现**：FAST 的 `risk.user_changes.paths` 可以引用 ignored 文件。Gate 读取并计算保护指纹，但 Context `_declared_paths()` 只登记 task.scope 等路径，不登记该字段。此文件变化可改变 live Gate blocker 而不改变 `capture()`。

第二项不等于已证明 Gate 绕过：Integrity 会重新评估 Gate，可能通过内容比对拒绝旧 Context。此次证明的是源版本不完备；没有证明旧 Context 在完整校验下仍获通过。

## 可重跑证据

探针：[docs/audits/src09_probe.py](./audits/src09_probe.py)。显式执行，不放进默认 `tests/` 回归集合，不用 xfail 隐藏失败。

```bash
PYTHONPATH=src:tests python -m pytest -q docs/audits/src09_probe.py --tb=short
```

本轮结果：**3 failed, 1 passed in 4.52s**。

| 探针 | 结果 | 含义 |
|---|---|---|
| `test_unregistered_gate_read_must_prevent_publication` | RED，`DID NOT RAISE` | 模拟 Gate 读取 `.harness/extra-policy.yaml`，生成仍成功；未登记读取未被禁止。 |
| `test_unregistered_control_change_must_change_manifest` | RED | 修改该模拟控制输入，capture 相同。 |
| `test_fast_ignored_user_change_input_must_be_versioned` | RED | 当前 Gate、无 monkeypatch：ignored 保护文件变化，FAST_USER_CHANGE_MODIFIED 从无到有，但 capture 相同。 |
| `test_registered_gate_change_does_change_manifest` | GREEN | 对照：修改已登记 gate.yaml，capture 改变。 |

所有探针沿用 `tests/test_context_builder.py` 的临时 Git repo fixture。真实漏项 fixture 只将路径放进 `risk.user_changes.paths`，不同时放进 `scope.protected_user_paths`；现有 schema/loader 接受这种输入。若未来选择强制两字段一致，也必须明确兼容策略，不能假定所有旧 task 已同步。

## 已追踪的读取边界

| 调用路径 / 输入 | 当前版本登记 | 观察 |
|---|---|---|
| `FileContextSource.load` → task/requirements/invariants/gate/impact/observability | `ROOT_FILES` | 固定文件内容与缺失状态参与 hash。 |
| `assess_gate` → FAST risk boundaries / gate verification policy | `risk-boundaries.yaml`、`gate.yaml` | 已登记。 |
| STANDARD/STRICT Gate → findings、decisions、interface-contracts、evidence | `ARTIFACT_DIRS` | 目录成员递归登记；`.tmp` 除外。规范引用由 `paths.py` 等限定。 |
| `workspace.snapshot` → Git HEAD、产品 diff、非 ignored untracked 文件 | `head`、`workspace_hash` | `.harness` 与未引用 ignored 文件有意不在 product fingerprint。不能用此 hash 弥补所有间接控制读取。 |
| `run_fast_gate` → `protected_paths_fingerprint(risk.user_changes.paths)` | task YAML 被登记，所指 ignored 文件可能未登记 | **当前已复现漏项**；字段文字的 hash 不是被引用文件内容的 hash。 |
| 声明路径：task.scope、impact、observability、test plans、findings、decisions | `declared_files` | 显式文件内容/缺失被登记；一般 glob 不展开。 |
| package schemas / projection 实现 | `PROJECTION_VERSION=1`；本 repo 开发时部分由 product hash 间接覆盖 | 外部项目使用已安装包时，没有建立资源/实现变更与 projection version 的自动一致性证明。待设计版本边界，不在本次已复现缺陷范围。 |
| 假设未来新增的任意控制输入 | 无通用读取审计 | 首个注入探针证明缺少自动拒绝机制。 |

静态搜索重点：`quality_gate.py` 的 `_evaluate_gate`、`run_fast_gate`、`assess_gate`；其 `decision`、`interface_contract`、`diagnosability`、`evidence_validator`、`workspace`、`risk_boundaries`、`paths` 依赖。此表不是对所有动态分支、第三方库或子进程 I/O 的完备证明。

## 根因

`context/freshness.py::capture` 在构建前后计算同一静态集合。只有已登记对象变化才能被 `require_fresh` 看见。

- 新增读取没有要求登记的运行时约束。
- `_declared_paths` 目前读取 task.scope，却没有读取 FAST 实际使用的 risk.user_changes.paths。
- `.git/info/exclude` 排除的保护文件不进入 product fingerprint。
- 因而前后 capture 相等不能单独证明“Gate 判定依据未改变”。

## 建议修复顺序

### 1. 先修当前漏项（最小范围）

将 `risk.user_changes.paths` 加入显式路径登记，保留 existing task 兼容；使用已有 contained-path、file-version 校验，不改 Gate 保护语义。不通过放宽 Integrity 或 product fingerprint 解决。

验收：
- 上述真实漏项探针 GREEN，并迁入正常测试集合。
- 文件变更、出现、消失均改变 Context freshness；越界路径/外部 symlink fail-closed。
- 构建中受控修改该文件，拒绝混合版本。
- 不把控制面变化错误传播成 product evidence stale。

这一步只关闭具体漏项，不关闭未知读取机制 SRC-09。

### 2. 再确定 SRC-09 机制方案

| 方案 | 优点 | 局限 |
|---|---|---|
| 扩大静态清单 + 分支回归 | 修改少，能修已知漏项 | 无法自动禁止未来未登记读取；不能据此关闭 SRC-09。 |
| 统一受控 source/read 接口 + 依赖声明 + 禁止旁路检查 | 可维护、可测试，可登记读取字节和缺失/目录依赖 | 需迁移 Gate 间接 loader；只建接口而未禁止直接 Path/open 仍不够。 |
| 隔离 Context worker 中跟踪/限制 I/O | 不把全局 monkeypatch 留给并发调用；可验证真实读取 | 必须处理 exists/stat/目录成员、资源文件、原生库与 Git 子进程边界；Python open 审计本身不等于完整沙箱。 |

建议先做第 1 步，再为第 2 步设计受控 source 接口与明确旁路约束；如果约束无法证明契约要求，需采用更强隔离或由用户批准修订契约。禁止把更新文档当作机制已实现。

不建议：生产进程中临时全局 monkeypatch `Path.read_text`；会漏 `open/read_bytes/stat` 等路径，并引入线程间污染。

## 状态

- SRC-09：仍缺口，现有注入探针已 RED。
- SRC-04/05：新增当前真实间接 ignored 输入漏项证据，待修。
- 既往 430/61 项相关回归记录不撤销，但它们没有覆盖本次负例。
- 审计轮次未修复；后续具体漏项修复见文首。仍未提交，无 Gate CONVERGED 或 Product Done 声明。

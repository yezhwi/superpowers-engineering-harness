# SRC-09 生产接入后的边界审计

## 范围与状态

本轮为边界审计，不修改产品实现。使用已接受的威胁模型：可信 Harness Python 意外漏登记；不要求原生恶意代码或任意子进程沙箱。

已有未知 open、吞异常、Selector 与 validate 拒绝测试通过，不撤销这些结果。但 SRC-09 尚未达到完整闭包保证。本报告不是独立 reviewer 复审。

## 本轮复现

```bash
PYTHONPATH=src:tests python -m pytest -q docs/audits/src09_boundary_probe.py --tb=short
```

初始结果：**4 failed, 2 passed in 10.76s**。后续 bootstrap/closure 修复后重跑：**2 failed, 4 passed in 9.99s**。仅合成临时 repo，未触碰活跃任务。

| 场景 | 结果 | 准确解释 |
|---|---|---|
| Gate 新增未登记文件的原生 Path.exists | RED：生成未抛异常 | Python open audit 不观察该查询。迁移/静态检查应承担此约束，而非宣称运行时 hook 已覆盖。 |
| Gate 新增未登记文件的原生 Path.stat | RED：生成未抛异常 | 同上；存在性、类型、元数据也可能影响 Gate 分支。 |
| 经 source_access.exists 查询未知源 | GREEN：拒绝 | 受控接口有效，不能把它与原生 Path 查询混为一谈。 |
| 新增普通 helper 导入后调用 | RED：静态检查无告警 | `direct_io_lines` 只检查当前 AST；不跟随未知模块，不要求导入闭包评审。不是动态反射攻击。 |
| bootstrap 的 _declared_paths 新增未知 read_text | GREEN（后续） | 固定 ROOT_FILES/canonical artifact member 发现范围已拒绝相邻控制文件。 |
| 静态检查直接 Path.exists | GREEN：识别违规 | 已纳入检查的函数内，显式元数据旁路会被测试抓到；不能笼统称“所有元数据旁路都未保护”。 |

测试中 monkeypatch 模拟未来可信代码新增依赖，不证明当前未修改 Gate 实际读取 extra-policy.yaml。间接 helper 静态探针检查的是待补的架构要求，不是宣称 direct_io_lines 已承诺解析任意 Python。

## 根因与审计证据

### 1. 运行时范围不覆盖 bootstrap

修复前，`context/integrity.py` 的 build_context/validate_context 在进入 context_read_scope 前调用 capture；结束时 capture 同样在范围外。`freshness.capture` 现先进入固定 bootstrap_scope 完成声明发现。

`context/read_scope.py` 仍在 source_scope 前调用 `_untracked_paths` 构造允许集合。这些属于可信基础设施，但现有静态检查没有把它们作为完整、受限的 bootstrap 闭包验收。

bootstrap 必須能够读取固定 task/声明记录以建立文件清单；解决方法不能是“先解析所有动态路径并自动授权所有读取”。声明发现和依赖读取必须分阶段。

### 2. 静态清单未覆盖调用闭包

目前检查有两种：
- 模块级：context/source、context/integrity、risk_boundaries、diagnosability、evidence_validator。
- 函数级：Gate 主要评估函数、artifact loader、workspace 控制 helper、paths.evidence_path。

函数片段测试不会自动覆盖新 helper、模块级读取或导入变化。`direct_io_lines` 对常见直接方法引用和简单别名有效，但不维护允许导入集合，也不递归核对 Harness 依赖。

在接受的“运行时 open 守卫 + 静态元数据/旁路约束”设计下，这是未完成的第二道防线。

## 闭环探针结果（第十九批后）

`PYTHONPATH=src:tests python -m pytest -q docs/audits/src09_probe.py docs/audits/git_source_scope_probe.py docs/audits/src09_boundary_probe.py --tb=short`：**11 passed in 9.37s**。

其中原来 raw `exists/stat` 的两项不再假设 Python `open` audit hook 能拦截 metadata；它们现在构造未来 trusted Gate 源码，并验证 `assert_trusted_closure` 在发布前报 `DIRECT_IO`。这与 SRC-09 受信代码/非 sandbox 范围一致。受控 adapter 调用、未知 bootstrap read、Git pipe-fd 和 indirect helper probe 保持实际运行覆盖。

此结果不是独立 review，也不是完整测试套件或恶意代码 sandbox 声明。SRC-09 实现边界已测通；签字仍等待独立复审及授权全量验证。

## 依赖闭包防线进展

已新增 `context/dependency_closure.py` 与 `tests/test_context_dependency_closure.py`。它从显式 Context projection entry 集追踪本地 Harness import，拒绝未登记 helper；非投影/基础 adapter 必须在有限名单中写非空理由。非 adapter 模块出现直接文件 I/O 同样失败。

首轮 4 RED（模块不存在）；实现后覆盖：未知 helper import、已声明 helper 的直接 I/O、无理由 adapter、当前受信闭包。核心闭包测试与 Context/Gate 回归 **211 passed in 317.24s**，非全量。此前整组命令 480 秒超时，不能作为通过证据。

限制：adapter 是显式审查边界，不是安全豁免；当前 `context.freshness` adapter 仍记录 bootstrap 两阶段范围待办。闭包按模块而非调用图划分，`context.escalation`/store 等 mutation 模块的非投影函数必须凭理由隔离，后续独立复审需要判断这些理由是否足够窄。原生动态 import/reflection 仍不在能力范围。

## 建议修复顺序

### A. 补可审查的依赖闭包清单

建立显式 bootstrap / projection / trusted-adapter 分组。每个 entry 指定模块或函数、允许的 Harness 依赖及原生 I/O 理由。

新增 Harness import/helper 必须使静态测试失败，直到加入闭包并完成直接 I/O 检查。不能通过只检查函数名相同的旧片段忽略新增依赖。

Git、package resource、底层 source_access、freshness 的原生 I/O 用有限 adapter 例外列出。禁止 `workspace.py` 或 `freshness.py` 整模块无理由豁免。

该闭包检查针对可信源码发布前回归，不冒充运行时静态分析器或沙箱。

### B. 将 bootstrap 约束分成两阶段

1. 用固定 ROOT_FILES、canonical artifact 成员规则建立最小声明发现范围。
2. 在此范围内解析 task/scope/test plan 等依赖声明；未知控制 open 拒绝。
3. 退出声明发现范围，验证规范路径后冻结允许集合；再读取 declared 文件、执行受限 workspace/Git 查询。
4. 前后核验必须使用相同规则。新目录成员出现使 stale，不静默追加入正在发布的文档。

同时保持 optional missing、ignored 显式路径、FAST 保护文件、schema 版本与 derived 排除规则。

### C. 验收两道防线的组合

- 未登记原生 open：运行时拒绝。
- 未登记 source_access 元数据：运行时拒绝。
- 已扫描模块新增直接 Path.stat/exists：静态拒绝。
- 新增间接 helper/import：闭包检查拒绝，不能默默绕开扫描。
- bootstrap 新增未知控制读取：拒绝，生成失败不覆盖旧快照。

原生 Path 元数据注入探针可以保留作为 runtime 能力边界演示；只有在新增静态闭包负例证明此类代码不能进入可信发布集合后，才允许按组合保证解释其结果，不能直接 xfail 然后宣布 SRC-09 完成。

## 不在本轮已证明范围

未证明当前存在错误 Gate PASS；未证明所有 package loader、线程继承、符号链接竞态或第三方 native I/O 安全。尚未执行跨平台真实打包环境/独立 reviewer 验证。

本轮只新增探针和审计记录；无业务修复、无全量测试、无提交、无活跃任务状态推进。下一步优先做 A，再做 B，完成后重新签收 SRC-09。

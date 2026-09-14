# SRC-09：受控读取与旁路约束设计

## 状态与授权

用户已接受：防止可信 Harness Python 代码意外漏登记；不承诺拦截恶意原生扩展或任意子进程绕过。

本文件将该边界细化为实现设计，尚非已完成能力。当前两个未知读取 RED 探针仍保留。继续在现有 main 工作，不创建 worktree、不提交、不推进当前无关 Harness 任务。

依据：实施契约 §9.2/§9.3、SRC-09 审计；本设计不降低 Gate、Review、Evidence、risk 或授权要求。

## 第一批实施进展

已新增 `src/harness/source_access.py` 独立守卫与 read_bytes/read_text/exists/is_file 入口；一次安装 audit hook、ContextVar 隔离、sticky violation（含嵌套传播）。`tests/test_source_access.py` 11 项通过；与 Context CLI、Gate、workspace、文档等相关回归合计 151 项通过（非全量）。

第二批已补受控接口观察记录：read_bytes/read_text 记录实际返回 bytes 的 SHA-256，捕获 FileNotFoundError 记录 missing；exists/is_file 记录查询结果；members 记录非递归 pattern 的成员名及目录缺失。重复观察冲突与范围退出时复核失败返回 CONTEXT_STALE，嵌套观察传播至外层。snapshot 返回副本，目录列举不授权读取成员。

新增 `tests/test_source_observations.py` 首轮 7 RED，补齐后守卫/观察合计 27 passed；本轮相关回归 **167 passed in 108.69s**，非全量。外层 finally 重置 ContextVar，未新增全局 monkeypatch 或更改 Gate 锁。

仍未接入生产 Context/Gate，静态旁路检查、资源版本绑定未实现。直接调用底层 Path/open 虽受未知路径守卫约束，但不会产生受控接口的 bytes 观察记录；必须完成迁移与旁路检查，不能据此关闭 SRC-09。原未知读取集成探针仍未关闭。线程测试覆盖各线程显式建立范围，不证明范围自动跨线程传播。独立复审未做，未提交或推进原任务。

## 第三批：首个 loader 迁移

`context/source.py` 的直接读取、存在性/类型检查和成员枚举已迁移至 `source_access`；新增 is_dir/is_symlink 观察与退出复核。YAML 文档读取一次，返回字节同时用于 ref hash 和解析，路径 containment 先于读取。

`tests/test_source_boundaries.py` 包含该模块直接 I/O 的 AST 检查、hash/解析同源反例、外部路径读取前拒绝反例；不声称该检查覆盖别名或完整 Gate 闭包。相关回归 **479 passed in 331.63s**，非全量。新测试曾复现迁移顺序导致 containment 晚于读取，现已修正并回归。

生产构建尚未激活 source_scope，Gate 间接 loaders 尚未迁移；因此未知读取集成探针仍未关闭。下一批扩展静态检查的别名覆盖与 Gate 读取链，之后才能激活并验收守卫。独立复审未做。

## 第四批：简单别名检查与 FAST 间接 loader

新增 `tests/source_boundary_checks.py`，静态检查直接 I/O 引用（不只函数调用），覆盖方法赋值、builtins/io/os 的别名/from-import。受控模块别名只有明确导入且未被重绑定时豁免；赋值、参数、重复导入及 except 变量遮蔽有负例。该工具是保守测试 lint，不证明动态反射或任意跨模块调用闭包安全。

检查范围现为 `context/source.py`、`risk_boundaries.py`。FAST 的 load_boundaries 改用受控 read_text，风险分类和原有错误封装不变；局部导入避开 source_access→Context model→Gate 的导入环。新增真实 loader 测试验证成功/缺失 bytes 观察，以及捕获 RiskBoundaryPolicyError 后 scope 仍失败。

本轮相关回归 **255 passed in 200.71s**，不是全量；仍未激活生产 Context scope，未迁移完整 Gate 间接 loader/包资源集合。原未知读取集成探针不标记通过。独立复审未做。

## 第五批：decision/interface 控制读取迁移

`decision.py` 与 `interface_contract.py` 的 task ID 读取、单记录读取、目录存在性/类型查询、成员枚举已迁移到 source_access。schema 读取与写入函数未纳入此次迁移，不宣称两模块全部 I/O 已受控。

新增 `tests/test_artifact_source_access.py`，首次 10 RED；补齐后覆盖六个 loader 函数的静态直接 I/O 检查、实际 bytes/成员/task 观察、缺失目录、列举不授予成员读取权、读取后删除触发 stale。相关回归 **299 passed in 276.78s**；导入整理后 artifact/decision/interface **28 passed**。未运行全量。

导入排序已修；两模块原有 UP017（timezone.utc）未顺手修改，lint 以忽略该规则的改动范围检查通过，不能称全仓 lint 无告警。生产 scope 仍未激活，Gate 主体、evidence/diagnosability/workspace 等读取链及包资源版本尚待接入。未提交、未推进原任务、未做独立复审。

## 第六批：包 schema 入口与版本绑定

新增 `schema_resources.py`：显式登记 17 个 schema 名称，拒绝未知/非规范资源；read_schema 解析同一份已观察 bytes。source_scope 独立记录资源 hash 并在退出时复核，未知资源违规具有 sticky 属性。文件系统资源仅获得本次单文件 open 许可，不授权相邻 Python 文件或整个目录；外部 schema symlink 被拒绝。非 Path Traversable 保留资源读取路径，尚不宣称通过所有 zip/原生导入器隔离场景。

Context `generated_from.schema_resources` 纳入 schema 原始字节版本；PROJECTION_VERSION 提升到 2。旧 projection=1 派生文档 schema 校验拒绝，要求重新生成；task 无需迁移。decision/interface schema 读取已使用统一入口，其他 Gate/schema 消费者仍待迁移。

新增测试首轮 10 RED；迁移 artifact 后其资源观察 2 RED→GREEN。本轮相关回归 **287 passed in 300.62s**；补充旧 projection、吞异常及 schema 越界 symlink 后针对性 **28 passed in 3.45s**。lint/格式/diff 检查通过的范围为新增资源模块、source_access/freshness 和对应测试；不是全量验证。

生产 source_scope 仍未激活，SRC-09 未关闭。未提交、未推进原任务、未做独立复审。

## 第七批：Evidence 与 Gate schema 入口

`evidence_validator.py` 的 evidence 文件查询/读取迁移到 source_access；projection 与 reuse 的 schema 校验统一使用 read_schema。Gate 的 validate_schema 同样迁移至资源入口，保留既有 InvalidHarnessState/schema 校验消息。source_access 在 evidence projection 内局部导入，避免初始化循环。

`tests/test_evidence_source_access.py` 首轮 4 RED，覆盖正常 evidence bytes/hash、missing 类型观察、非法记录仍记录 schema、reuse schema 观察；增加 evidence 模块和 Gate validate_schema 的静态直接 I/O 检查。首轮相关测试 80 passed，集成回归 **292 passed in 276.60s**，非全量。

Gate 主体的 artifact/YAML 读取及 diagnosability/workspace 等间接依赖尚待迁移。生产 source_scope 仍未激活，不能把本批视为 SRC-09 关闭。未提交、未推进原任务、未做独立复审。

## 第八批：Gate 主体控制读取

Gate 的 `_load_yaml`、`load_evidence`、`load_findings`、`run_fast_gate`、`_evaluate_gate` 直接文件读取、存在性与集合枚举已迁移受控接口；`write_back` 非投影写入路径未改。新增对应函数静态检查及真实 canonical 源观察测试，首轮 6 RED。

迁移初稿顶层 source_access 导入导致独立 Gate 脚本导入环，已有回归捕获退出码 1 而非 2；改为读取函数内局部导入后 Gate/新增测试 68 passed。随后相关集成回归 **259 passed in 324.60s**，非全量；保留 Gate 判断与 blockers 规则。

生产 source_scope 尚未激活；diagnosability、workspace、paths 等间接读取和 Context 内其余直接 I/O 仍须核对。SRC-09 未关闭。未提交、未推进原任务、未做独立复审。

## 第九批：workspace/paths 控制侧读取

workspace.observability_inspected_paths、protected_paths_fingerprint 的文件分支，以及 paths.evidence_path 的错误候选枚举已迁移受控接口。Git product fingerprint、control_plane_fingerprint API 不改。静态函数检查和真实文件观察测试首轮 RED，迁移后相关回归 **220 passed in 120.27s**，非全量。

新生产接入阻塞已实测：source_scope 拒绝 subprocess 包装 Git stdout 管道的整数 fd，导致合法 Git 查询失败。可复跑 `PYTHONPATH=src:tests python -m pytest -q docs/audits/git_source_scope_probe.py --tb=short`，本轮 **1 failed in 0.33s**。未用 xfail 隐藏，也未放行所有 fd。正常回归中的保护文件观察测试仅隔离 `_run` 返回值，不能充当真实 Git 接入通过证明。

下一检查点应先实现限定 Git 查询/管道来源的受控适配器，再继续生产 scope 激活；diagnosability 等间接读取仍待迁移。SRC-09 继续未关闭，现有两个未知读取探针之外还有上述 Git 接入 RED。未提交、未推进原任务、未做独立复审。

## 第十批：受控 Git 查询适配器

新增 `git_query.py`，只接受 workspace 已使用的 rev-parse、ls-files、merge-base 和固定形状 diff 查询，拒绝 push/reset/额外输出选项。workspace._run 改用该入口；非零退出仍产生 WorkspaceError。

采用适配器拥有的 TemporaryFile 捕获 stdout/stderr，而非放行 subprocess.PIPE 的任意整数 fd；不修改 fd 守卫。输出文件在成功、失败/异常时关闭，不需要双管道排空线程。diff 显式禁用 ext-diff/textconv，Git fsmonitor 禁用；不宣称对所有 Git 原生内部或配置行为实现系统沙箱。临时捕获位于系统临时目录，不进入 repository 源清单。

真实 Git scope 探针从 RED 转 GREEN（1 passed）；正常保护文件观察测试撤掉 Git mock。新增真实 Git/error 测试、任意 fd 仍拒绝、双路各 2 MB 输出和启动失败清理测试。首个大组 420 秒超时，未判通过；重跑分批 **140 passed in 75.14s** 与 **157 passed in 390.43s**，合计 297 项相关回归通过，非全量。

Git 接入阻塞已修；生产 source_scope 仍未激活，diagnosability 及剩余依赖闭包/静态检查未完成，两个未知读取集成探针不因此关闭。未提交、未推进原任务、未做独立复审。

## 第十一批：diagnosability 读取迁移

`diagnosability.py` 的合同/review/impact/task/finding/evidence 读取与成员枚举统一使用 source_access；五类包 schema 通过 read_schema。保留原 JSON/YAML/schema 错误封装、review/finding/blocker 规则及写入流程。模块级静态直接 I/O 检查通过。

新增测试首轮 3 RED / 1 passed；迁移后 diagnosability 的 CLI、Gate、生命周期、端到端相关测试 42 passed。Context/Gate 集成回归 **267 passed in 277.15s**，非全量。

生产 source_scope 仍未激活；下一检查点核对 Context 自身读取及 workspace 产品查询适配边界，生成冻结的精确文件/目录授权后接入 build/validate。未知读取集成探针仍不标记通过。未提交、未推进原任务、未做独立复审。

## 第十二批：生产读取范围接入

新增 `context/read_scope.py`，依据冻结 generated_from 的控制文件、显式声明路径及 Git 返回的非 ignored untracked 产品文件集合授权。canonical artifact 单目录成员模式独立声明，允许检查已知规则内缺失 evidence，不因此授权整个 repository。source_scope 增加显式 member_rules，仍按父 scope 逐层约束。

build/validate 的 loader、注入 Selector 与 Integrity 内容复核接入 source_scope。Integrity 的 schema/fragment 读取使用统一入口。新增生产未知 Gate 读取、吞异常、validate、Selector 旁路负例均经历 RED→GREEN；合法 Gate BLOCKED 仍可投影。

相关回归分批 **174 passed in 297.72s**、**138 passed in 186.83s**。审计与真实 Git 探针 **5 passed in 7.92s**。按本设计 §7，原“未声明文件变化必须自动改变 capture”探针调整为显式登记后的 freshness 测试；未知读取拒绝独立保留，修复前 RED 日志仍在审计报告。

这不是 SRC-09 正式关闭：bootstrap capture、workspace 产品元数据/原生 Git、动态导入与第三方资源、直接 stat/exists 旁路约束仍须独立核对；当前静态检查只覆盖明确列出的已迁移模块/函数，不能宣称任意新 helper 导入都自动拒绝。未提交、未推进原任务、未做独立复审。

## 第十三批：接入后边界审计

新增 [SRC-09 边界审计](./Superpowers-Engineering-Harness-v0.2.8-SRC09-Boundary-Audit.md) 与 `docs/audits/src09_boundary_probe.py`，结果 **4 failed, 2 passed in 10.76s**。未登记原生 exists/stat、未知间接 helper 静态识别、bootstrap 新增未登记读取仍无完整保护；受控 exists 与直接元数据静态检查对照通过。

这些探针模拟未来可信代码意外新增读取，不宣称当前 Gate 已读未知文件或发生错误 PASS。原生元数据不由 open audit 捕获属于已知边界，缺口在静态闭包防线与 bootstrap 约束尚未完整。下一步先补显式依赖闭包检查，再约束 bootstrap 的声明发现阶段。未改业务代码、未提交、未做独立复审。

## 第十四批：可信依赖闭包检查

`context/dependency_closure.py` 按显式 entry/allowed/adapter 清单检查本地 Harness import：未知 helper 拒绝；非 adapter 的直接 I/O 拒绝；adapter 必须有非空边界理由。测试先 4 RED，后通过未知 helper、直接 I/O helper、无理由 adapter 与当前闭包四种场景。

此前整组 480 秒超时，不记作通过；分批 Context/Gate 核心回归 **211 passed in 317.24s**。Ruff 对 quality_gate.py 报告不可执行 shebang、未使用 evidence_dir 和 args；本批不处理无关清理，不能称全仓 lint 通过。

闭包现在将 bootstrap/freshness 标记为显式 adapter，理由写明两阶段范围待办；这提高可审查性，但不修复 bootstrap 漏读。下一步实现最小声明发现范围，再重新运行 boundary probe。未提交、未推进原任务、未做独立复审。

## 第十五批：bootstrap 声明发现范围

`freshness.capture` 先进入新增 bootstrap_scope，只允许固定 ROOT_FILES、ARTIFACT_DIRS 及 decisions/findings 的 canonical 成员规则读取 `_declared_paths`；发现的路径才加入后续 version 计算。相邻未声明控制文件在声明阶段 read_bytes/read_text 立即拒绝，不能用动态声明给自身授权。

新增 `tests/test_freshness_bootstrap_scope.py` 首轮 3 RED，覆盖 bootstrap 注入未知 read、相邻文件与 optional 源存在性。核心闭包/Context/Integrity/read-scope 回归 **101 passed in 146.76s**。边界审计重跑从 4 RED/2 GREEN 改为 **2 RED/4 GREEN in 9.99s**；剩余 RED 仅为原生 exists/stat runtime hook 能力边界。

尚未解决 `_untracked_paths` 在 read_scope 前的产品集合发现，或完整原生 metadata 静态发布防线。不能据此关闭 SRC-09。Ruff/格式检查仅改动范围通过；未提交、未推进原任务、未做独立复审。

## 第十六批：版本采集第二阶段范围

新增 `version_scope`：bootstrap 先发现声明，随后冻结 ROOT_FILES、当前 canonical artifact members、规范声明/FAST protected 路径及 Git 已返回的 untracked 产品集合，才运行 `_capture_versions`。版本循环中注入的未知 read_text 先 RED，现被 scope 拒绝；现有 canonical artifact 保持可读。

新增 `tests/test_freshness_version_scope.py`，本批 5 项通过；Context builder/integrity/read-scope/CLI 回归 **125 passed in 228.28s**，非全量。`_untracked_paths` 仍在 version_scope 之前通过固定 Git 适配器发现产品集合；这是显式 adapter 边界，尚未成为受控 Python 元数据查询。目录成员在冻结后新增的交错场景仍需专属测试。

SRC-09 继续未关闭；未提交、未推进原任务、未做独立复审。

## 第十七批：冻结后成员/产品交错

`tests/test_freshness_version_scope.py` 新增两条受控插入反例：version_scope 已冻结后新增 canonical evidence 成员，及 Git untracked 发现后新增产品文件。两者均以 CONTEXT_REFERENCE_BROKEN 拒绝，不能静默吸收进入本次 capture；此前未知 file_version 读取、正常 canonical 读取仍覆盖。

本批 freshness/bootstrap/read-scope/integrity/CLI 分批回归 **88 passed in 220.68s**，非全量。此结果仅保证受 scope 的实际 open 路径不会混入当前版本；原生 exists/stat 的 Gate 分支仍依赖静态闭包发布检查，SRC-09 不关闭。未提交、未推进原任务、未做独立复审。

## 第十八批：protected literal 路径回归修复

bootstrap 重构后，version_scope 初稿误把 FAST protected 的字面 `*` 文件名当 scope glob 跳过，`private/literal*.txt` 读取被拒绝。复现为 `test_context_protected_freshness` 1 failed/9 passed。修复将 discovered scope glob 与 protected 字面路径分开：前者不枚举，后者无条件冻结规范文件；`::` 语义不变。

修复契约：普通 scope glob 不得授权扫描，FAST 实际读取的 protected 字面文件不得漏授权或漏 freshness。反例/同构覆盖 literal `*` 与 `::`，修复后 freshness/protected **18 passed in 12.48s**、Context 核心 **162 passed in 430.87s**（分批，非全量）。未做独立 reviewer 复审；SRC-09 仍不关闭。

## 第十九批：untracked 产品发现边界

`workspace._untracked_paths` 不再在 version_scope 前对 Git 返回的每个路径调用原生 Path.is_file。Git 枚举后的名称经相对路径/无 traversal/非 `.harness` 过滤后冻结为 allowed；实际 bytes 读取仍在 scope 内，缺失/替换 race 由受控 open 拒绝。

新增 `tests/test_workspace_untracked_scope.py`，原生 is_file 探测反例先 1 RED/4 GREEN，修复后 workspace/Context/freshness 21 passed，扩大分批回归 **228 passed in 271.91s**。Ruff 对 workspace.py 仍报告两项未改行 C401，本批不做无关重构；非全仓 lint 通过声明。原生 exists/stat 的 Gate 分支仍依赖静态闭包防线，SRC-09 不关闭。未提交、未推进原任务、未做独立复审。

## 1. 不变量

1. 参与 Context/Gate 投影的控制读取必须有规范路径和显式依赖声明。
2. 文件内容、缺失、目录成员都是依赖；不能只拦 read_text 而遗漏 exists/glob。
3. 未登记控制读取必须拒绝当前 Context，不能吞掉异常后输出看似有效的 blockers。
4. Manifest 的文件 hash 对应实际解析的字节；读前/读后版本冲突返回 CONTEXT_STALE。
5. 新机制只在 Context 构建/校验范围生效；普通 Gate 的判定语义不变。
6. 不遍历全部 `.harness` 补清单；derived、telemetry、staging/history 默认仍排除。
7. 并发请求不得共享可变读取记录或临时修改全局 Path/open 函数。

## 2. 两道约束，不冒充沙箱

### A. 运行时控制文件 open 守卫

使用一次性安装的 Python audit hook 和 ContextVar 范围标记。没有激活 Context 范围时 hook 立即返回。

激活时，对本 repository `.harness` 内、或指向该目录的文件 open 检查允许清单。未知路径在读取前拒绝，并在本次范围记录 sticky violation。范围退出时再次检查 violation：即使 Gate 捕获 Exception 转成 blocker，也不能发布 Context。

注意：
- hook 不是任意 I/O 拦截器，不能承诺观察所有 stat/exists/native I/O。
- hook 永久安装，不在请求间反复安装；读取范围通过 token 恢复，嵌套范围不能扩大父范围授权。
- hook 中不再次读取文件；路径归一化与重入保护必须有测试。
- audit 参数中的 fd 不能被误认为路径。可信入口的 fd 来源必须受控；已打开 fd/线程传递不能成为未登记控制输入渠道。
- 先处理规范路径和 symlink escape，再匹配声明。缺失文件的 open 尝试也需要登记。

该层用于让现有注入式 `extra-policy.yaml` 读取探针真正 RED→GREEN，不只是新增一条静态 lint。

### B. 受控源接口与静态旁路检查

可信 Python 读取链逐步迁移到一个内部模块 `src/harness/source_access.py`：

```python
read_bytes(path: Path) -> bytes
read_text(path: Path, *, encoding: str = "utf-8") -> str
exists(path: Path) -> bool
is_file(path: Path) -> bool
members(directory: Path, pattern: str) -> tuple[Path, ...]
```

接口在未激活范围时保持普通文件语义；激活时先要求依赖声明、记录读到的字节/缺失/成员集合，再返回给 loader。JSON/YAML 必须解析这些返回字节，不再二次直接打开。

静态检查针对 Context/Gate 的可信源码闭包，拒绝新增直接 open、Path.read_*、exists/is_file/stat、glob/rglob/scandir，以及未分类的新 I/O helper 导入。检查还必须覆盖简单别名与 from-import 形式；无法识别的新调用不能静默列入豁免。

这不是证明任意 Python 程序安全：动态反射、恶意规避不在接受范围。静态闭包清单和工具豁免属于评审资产，变更必须连同读取测试更新。运行时 hook 负责实际未知 open，静态检查负责 hook 无法观察的元数据调用和新旁路。

## 3. 声明与观察分离

不能把“观察到读取”自动等同于“允许读取”。构建开始冻结允许集合：

- 固定 canonical 文件，包括 optional 的明确路径；
- 显式 canonical artifact 目录及规定成员模式；
- scope/test plan/finding/decision/FAST 保护路径等声明文件；
- 独立分类的 package resources 和 workspace 工具输入。

受控枚举先记录完整成员列表，再读取成员。新建成员在读后复核使 Context stale，不被静默吸收进正在构建的快照。

读取返回的原始 bytes 用于内容 hash。重复读取同一路径若版本不同，立刻 stale。检查最终观察集属于声明集，且开始/结束版本一致。

存在性查询无论返回 true/false 都记录。未知文件即使不存在，也不能不经登记影响 Gate 分支。

## 4. 接入位置

- `context/integrity.py`：build_context 和 validate_context 包含声明冻结、受控 load/Gate/_check、结束检查；不只保护 CLI。
- `context/source.py`：通过 source_access 解析源；保留严格 schema、路径、ID 校验。
- `context/freshness.py`：保留 product/control 分离；结合实际观察记录复核，不用 product hash 代替控制源。
- `quality_gate.py` 及 decision/interface_contract/diagnosability/evidence_validator/risk_boundaries/test_plan 的真实读取链：迁移 I/O，不修改业务规则。
- `context/store.py`：仅接受范围检查成功的文档；generate/validate/explain/expand 全部间接经过 Integrity 边界。

声明捕获本身是受信基础设施，也要测试：不允许因为它读取源列表就无限授权后续所有路径。

## 5. Git、包资源与线程边界

- Git 命令只允许既有 workspace helper 的固定只读查询，绑定 HEAD/product fingerprint。不得给任意 subprocess 一个“不检查”通行证。
- Git 原生内部读取不由 Python audit hook 完整观察；其语义通过固定命令、输出指纹和回归测试约束。
- 包 schema 不按用户控制 artifact 分类；登记明确资源集合/资源版本，避免整个 site-packages 被当作控制文件白名单。
- projection/资源规则变化提升 PROJECTION_VERSION 或等价实现版本；旧派生 Context 要求重新生成。
- 当前可信读取链保持同步。若新增 worker thread，必须显式传播读取范围；未接入的后台读取不得参与投影。添加线程创建旁路测试，不能假设 ContextVar 自动跨线程传播。

## 6. 错误与恢复

未登记源使用 `CONTEXT_REFERENCE_BROKEN`，附规范来源标识，不输出源内容；避免新增无消费者的错误枚举。实际版本冲突继续 `CONTEXT_STALE`；非法文档继续现有 schema/state 错误码。

所有 CLI 入口失败 exit 2、无损坏 Context stdout、不覆盖最后完整派生快照。普通 product Gate BLOCKED 仍可成功投影。

修复未知读取的正确方式是声明并验证真实依赖，不是 catch 后继续、切 full、或复制旧 Gate 摘要。

## 7. 必须验收的负例

1. 未登记 read_text/read_bytes/open，以及 symlink 别名读取：拒绝发布。
2. Gate 吞掉未知读取异常后返回正常 assessment：范围退出仍拒绝。
3. 未登记 exists/stat/目录枚举：受控接口拒绝；新增直接调用的静态检查失败。
4. 已登记 optional 缺失允许查询；出现/消失触发 stale。
5. 构建中成员新增、删除、内容变化：stale，旧完整快照不变。
6. 注册源正常通过，derived/telemetry 写入不自 stale。
7. 同时构建两个 repository、嵌套调用、失败清理：读取授权与记录不泄漏。
8. 同一守卫下比较 FAST/STANDARD/STRICT Gate 输出；业务语义不变。
9. build/validate/generate/explain/expand 所有入口覆盖，禁止只修 CLI 主入口。
10. 包 schema/投影版本变化后旧 Context 不被当作同版本有效文档。

现有审计第二个探针要求 capture 自动纳入“从未声明”的文件，这不是唯一合法修复。受控设计允许直接拒绝未知读取，不应为了让这个断言通过而扫描所有文件。将探针拆为“未知访问被拒绝”和“显式登记后变化必 stale”，保留原历史 RED 记录及迁移理由。

## 8. 实施检查点

1. 先实现受控接口、范围状态和守卫的独立负例；不提前宣称 SRC-09 完成。
2. 迁移 Context/Gate 读取闭包并启用静态检查；把未知读取探针纳入正常回归。
3. 完成所有入口、线程/异常和资源版本测试，再更新验收映射。

若 Python audit hook 的实际行为不能满足未知 open 的稳定拒绝、异常保留或并发隔离，停止接入并报告；不靠扩大豁免消除失败。不在本设计下擅自改为更强系统沙箱。

独立复核与授权全量执行仍是后续验收，不由设计文档代替。

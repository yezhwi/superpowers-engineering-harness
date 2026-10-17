# Context 与证据收集效率优化 Spec

> 版本：v0.6（发布清单与§7.3机制验收口径一致；已批准语义不变）
>
> 日期：2026-10-14（实测案例日期：2026-10-13）
>
> 状态：IMPLEMENTATION_CONTRACT / 已按评审明确契约；未实现、未做性能验收
>
> 设计基线：Harness checkout `c74ac4d4477469fdbeda80a2b470094d3134375f`
>
> 案例：knowledge_base `TASK-1038001`，Q3 / STRICT
>
> 授权范围：编写带证据的 spec；不修改 Harness 实现、业务代码、任务状态，不提交、不部署。

## 1. 结论与目标

优化目标不是减少必须验证的行为，而是减少 **重复读取/重建、无效重跑和验证后的范围漂移**。

推荐分两步交付：

1. **P0：计时 + 自动扩展批处理 + 验证前范围/绑定诊断。** 保持evidence freshness、既有Gate、risk、用户授权与安全不变量；资格消失时首次退出码由失败变成功是§6单列的已批准例外，真实错误零写入按已批准failure atomicity处理。
2. **P1：经授权的测试范围对账入口 + 一次调用内的解析复用 + 既有有效 evidence 复用。** 无审计缩减新增Gate blockers是收紧，不是放宽；不接受stale proof，不删除历史RED，不自动豁免要求。

不先做跨 HEAD 证据复用、不先做持久缓存、不先并行共享数据库测试，也不靠延长超时宣称优化完成。

**成功定义**：在合法范围基线/审计下，批处理保持相同安全事实、事件终态及既有阻断集合（资格消失的首次退出码变化单列）；N个新增扩展不再触发约2N次完整源读取/Gate assessment；过期前置在昂贵执行前报告。范围退役Gate检查是另一个明确的安全收紧：无审计缩减新增typed blockers，不要求和旧漏洞路径相同。

## 2. 证据与溯源

证据摘要和源码摘录已复制为 [本地证据包](2026-10-14-context-evidence-collection-efficiency-evidence.json)，避免依赖 `/tmp` 长期存在。证据包记录原始文件路径、SHA-256、被摘取字段、源码行号及安装版逐文件 hash 对照。原始失败记录未修改。

证据包是调查材料，**不是 Harness Gate evidence，不可 attach 成测试通过或优化通过证明**。仅复制必要字段，不包含完整业务日志、测试 stdout、Secret 或环境文件。

### 2.1 实测时间：不要把 pytest 时间当整轮成本

| 证据 ID | 实际结果 | 时间 | 时间含义 |
|---|---|---:|---|
| E01 | `harness context --compact` 被 SIGTERM，exit_code=null | 240.021 秒 | 监督器测得整次进程耗时；不是 CLI 成功 |
| E02 | 相同 CLI 第二次 exit 0 | 211.660 秒 | 监督器测得整次进程耗时 |
| E05 | R2 相关单测 93 passed | 4.66 秒 | pytest 报告时间 |
| E06 | JSON/索引相关单测 181 passed | 8.77 秒 | pytest 报告时间 |
| E07 | 实际 producer native 80 passed | 13.04 秒 | pytest 报告时间 |
| E08 | Record/查询相关 PG 73 passed | 43.53 秒 | pytest 报告时间 |
| E09 | projection 相关 PG 148 passed | 14.08 秒 | pytest 报告时间 |
| E10 | native outbox 10 passed | 109.31 秒 | pytest 报告时间，含实际进程/异步行为 |
| E11 | 受限 ES pipeline 11 passed | 165.04 秒 | pytest 报告时间，含实际进程/异步行为 |

最近两次 Context 调用合计 **451.681 秒（约 7.53 分钟）**。不含独立 validate、Agent 阅读、工具调度及其间空闲时间；不能外推为整场会话总耗时。第二次运行沿用了第一次由 CLI 合法持久化的扩展记录，不是冷态重复 benchmark。

### 2.2 当前控制面缺口

E03：当时 `impact.required_tests` 64 个路径，18 个不存在，名单完整保存在证据包。这些路径对应此前已批准的 core-only scope reset 归档，不证明有18个产品缺陷，也不授权恢复旧实验架构。

E04：

- Context 生成后独立 validate exit 0，completeness/accuracy/freshness/traceability 均 true。
- 随后又修改 impact，因此刚生成的 Context 只能作为历史快照，后续必须重建。
- `harness transition VERIFYING` exit 1：`PLAN_RECONCILIATION_BLOCKED`；P-001～P-005 未收账。
- `harness plan reconcile P-001 --auto` exit 1：`PLAN_PROOF_MISSING`。
- 快照还报告6个 requirement pending、4个 invariant pending、9个 case缺绑定、build/complexity/diagnosability证明缺失，以及 stale单测证明。
- 本轮没有重跑业务测试或执行最终 Gate；不能将上述控制面缺口写成业务测试失败。

### 2.3 源码证据：放大点不只一处

1. [S01：escalation.py:131–151](../src/harness/context/escalation.py#L131)：`apply_automatic_expansions` 按候选循环，每次调用 `_record_expansion`，然后再次 `build_context`。
2. [S02：escalation.py:244–275](../src/harness/context/escalation.py#L244)：`_record_expansion` 自己先完整 `build_context`，再验证 trigger basis。因此每个新增候选通常有前后两次完整重建。
3. [S03：source.py:400–452](../src/harness/context/source.py#L400)：每次 `FileContextSource.load()` 遍历证据并 project/validate，计算 workspace/plan assessment，再 `quality_gate.assess_gate`。
4. [S04：store.py:82–145](../src/harness/context/store.py#L82)：生成入口先 build、应用扩展、validate，再 staging/publication及两次 freshness检查。
5. [S05：integrity.py:266–323](../src/harness/context/integrity.py#L266)：build和validate均经 `_load_stable` 重新加载 authoritative sources；validate不是只比较输出 hash。

若有 N 个实际新增自动事件，控制流包含约 **1 + 2N 次 build_context，再加最终 validate 的一次完整源加载**。这是静态调用路径计数，不是本次运行实测 profiler 计数；不同早退/失败路径可能不同。不得写成“已证明95% CPU花在某函数”。

S01～S05 的 checkout文件与被测安装版文件 SHA-256一致。S06～S10整文件存在版本差异，证据包明确标记；后述 workspace/CLI设计依据当前checkout，不能声称安装版整体等于该Git commit。

### 2.4 排除已修复旧问题与未测推测

当前 [workspace.py:101–160](../src/harness/workspace.py#L101) 已将 `.harness/**` 排除于产品 fingerprint；[2026-09-07旧问题文档](2026-09-07-evidence-freshness-and-test-path-binding-issues.md)也标注已修复。**不能再将“写requirement verification使产品测试自我失效”当本次已确认根因。** Context仍应对控制面变化失效，这是正确安全行为。

当前 product fingerprint包含HEAD、staged/unstaged diff与非忽略untracked内容；[evidence_validator.py:100–135](../src/harness/evidence_validator.py#L100) 检查HEAD和前后workspace。提交或真实产品/纳入文档变化后，旧证据不能靠“源码似乎一样”直接变fresh。

没有本次 schema/Gate/capture/read/lock分阶段计时，也没有完整会话重跑总数和token成本，无法给出原因百分比或优化后绝对秒数。

## 3. 边界与不变量

| ID | 必须保持 |
|---|---|
| EF-INV-01 | 全局must requirements、critical invariants、已接受决策、开放findings及typed blockers不被压缩或缓存遗漏 |
| EF-INV-02 | risk/profile/执行权限不随Context扩展改变；Q3不降级；USER_AUTHORITY_REQUIRED/HALT_AND_WAIT仍立即停止 |
| EF-INV-03 | canonical source/fingerprint变化必须fail-closed；不能以旧Context、日志末行或CLI exit0代替完整有效证明 |
| EF-INV-04 | 每条合法扩展保留task/trigger/object/source_hash、顺序、from/to与预算累计；历史事件不抹除 |
| EF-INV-05 | 不删RED、不修改旧evidence payload/HEAD，不把 attach或reuse当重新执行，不自动标verified/COMPLETE |
| EF-INV-06 | 并发用户编辑、symlink/path escape、metadata读取失败和publication故障仍阻断；rollback仅回退本操作拥有的字节 |
| EF-INV-07 | 性能telemetry不含URL、密码、日志/业务内容；不参与product freshness、不形成Context自我失效循环 |
| EF-INV-08 | 缩减必测范围必须具有有效范围依据及审计，不能让must requirement失去证据义务 |

非目标：放宽Gate通过条件、实现跨HEAD证据继承、无限延长timeout、扫描全仓库猜依赖、恢复归档测试/迁移、创建新的业务数据库对象、认证本案例的整体Ready。

## 4. 方案选择

| 选项 | 收益 | 风险 | 决策 |
|---|---|---|---|
| 仅延长超时 | 能等到完成 | 重建放大仍在，无进度，下一轮再浪费 | 只作临时有界诊断，非优化交付 |
| 改Agent顺序与范围对账 | 减少无效验证 | 不解决Context内重复计算 | 必做，先行 |
| 自动扩展批量规划/发布 | 直接降低N倍重建 | 正常事件/并发安全等价；资格消失首次exit变化、真实错误零写入按§6批准契约验收 | P0推荐 |
| 一次调用内内容寻址解析复用 | 避免重复schema/YAML工作 | 复用边界错误可能漏漂移 | P1，仅测量后实施 |
| 持久结果缓存/跨HEAD复用 | 潜在更大收益 | 新鲜性/环境来源契约显著扩大 | 本spec排除 |

## 5. P0-A：分阶段计时与进度接口

### 5.1 最薄公共接口（拟新增，不表示现已支持）

```bash
harness context --compact --profile-json <outside-repository-output.json>
harness context --compact --progress
```

- 默认stdout保持原Context YAML/JSON与exit-code契约。
- `--progress`仅向stderr发出固定阶段名、计数、elapsed_ms；不输出canonical内容。
- profiling默认关闭；关闭时不得新增路径检查、输出依赖或失败条件。
- 显式profile输出只允许仓库外路径，或经实现/测试确认排除在 `capture()` 之外的derived telemetry位置；不能仅因位于 `.harness/` 就判定安全。不得覆盖source、Secret、既有文件或使用symlink。
- 启用profile时先验证输出位置。发布前的路径/权限失败返回 **2**，stderr包含 `context_published=false`。
- Context已合法发布后profile写入失败：拟新增Context命令专用退出码 **3**，stderr固定报告 `PROFILE_WRITE_FAILED_CONTEXT_PUBLISHED context_published=true`；stdout仍输出合法Context。调用方必须区分此码与未发布失败，不自动重跑生成或回滚已发布Context。当前checkout的cmd_context仅返回0/2，退出码3尚无冲突；实现时再次核查。
- 集成顺序：Context生成/渲染 → 打印合法Context → 单独try写profile。发布后的profile `OSError` 必须在该独立分支转为3，不能进入 [cmd_context当前的OSError→2分支](../src/harness/controlplane.py#L1827)。stdout打印自身失败不是profile输出失败，不能冒充stdout已输出。
- profile用同目录安全临时文件写完整JSON，再原子改名发布；遵守不覆盖既有目标及symlink约束，失败清理本操作临时文件，不能留下半份JSON。此写入在锁外进行，不写Harness权威成员。

内部使用单调时钟；日志时间只用于人读。`total_ms`测量命令入口到Context输出/锁释放结束的操作时间，**不含随后外部profile文件写入**；profile记录显式声明该时间边界。profile写入失败码不改变Context已发布事实。

```json
{
  "version": 1,
  "operation": "context.generate",
  "task_id": "TASK-1038001",
  "outcome": "SUCCESS|FAILED|CANCELLED",
  "context_published": false,
  "timing_scope": "context_operation_excludes_profile_output",
  "phase_semantics": "exclusive",
  "total_ms": 0,
  "phases_ms": {
    "lock_wait": 0,
    "capture": 0,
    "source_load": 0,
    "evidence_validate": 0,
    "gate_assess": 0,
    "selection": 0,
    "expansion_plan": 0,
    "publish": 0,
    "integrity_validate": 0,
    "overhead": 0
  },
  "counters": {
    "source_loads": 0,
    "gate_assessments": 0,
    "full_context_builds": 0,
    "expansion_candidates": 0,
    "expansion_events_written": 0,
    "evidence_records": 0
  }
}
```

上例全部0是schema示例，不是测量结果。所有 `phases_ms` 均为 **exclusive**：进入嵌套phase时暂停父phase，返回后恢复；多次调用累计。`overhead`覆盖阶段切换、输入输出及未归类操作。该对象所有阶段之和等于 `total_ms`（允许序列化精度误差≤1ms）。若另加inclusive指标，必须放在独立 `inclusive_phases_ms` 对象，不参与求和。

计数器只在函数入口累计：`full_context_builds`只数 `build_context`，`source_loads`只数 `FileContextSource.load`，`gate_assessments`只数 `assess_gate`。最终validate计入后两项，不计入build。读文件、capture和内存selector都不能冒充load或build。

profile不是authoritative source，不进入Context hash。SIGTERM handler只记录取消标志，不执行I/O；待事务处理完成、退出 `telemetry_lock` 且不再写Harness成员后，才允许向安全profile目标原子写 `CANCELLED`。所有profile记录均包含实际 `context_published`，包括CANCELLED；只能在合法Context发布完成后置true，取消不等于未发布。强杀或无法到达该边界可以没有profile，不能强行写一份“成功取消”记录；不修改Gate/task状态。

### 5.2 必测

stdout向后兼容；JSON可解析；不泄露Secret；阶段计数可对照spy；错误路径也有真实elapsed/outcome；telemetry写入后证据和Context不自我失效。安全测试使用仓库外临时输出。

## 6. P0-B：自动扩展批处理，保留逐事件语义

### 6.1 模块与依赖

`store.generate_context → expansion planner/publisher → integrity/source/selector`。

只调整自动Context生成内部执行方式，复用现有transaction、telemetry_lock、source_access/read_scope、capture/require_fresh和selector；不引入第二套Gate或状态机。`telemetry_lock`已可重入；从首次快照读取到扩展发布、最终Context校验和发布结束，外层锁必须连续持有，中间不得释放。人工 `expand_context` 保持现有逐事件发布，不参与batch。

事件构造必须与 `_record_expansion` 共用同一实现，不重写近似版本：先按policy构造，随后 `event.update(automatic)`，因此automatic候选自己的 `source_hash`覆盖 `digest(generated_from)`。`RISK_ESCALATED` 的from/to依据 `risk.escalation_history` 与已有事件to计算，不是一律升一档；包含最大policy自环。

拟新增私有接口：

```text
plan_automatic_expansions(validated_source, current_context) -> ExpansionBatch
publish_expansion_batch(harness_dir, batch, expected_sources) -> publication_result
```

`ExpansionBatch`：task_id、原source versions、原expansion尾部摘要、按顺序events、budget_delta、预期final_policy。包含原始事件全部字段；不是用户授权证明。

### 6.2 算法与语义

1. 连续持锁完成一次authoritative snapshot/source load，得到基准B；只在进入时获取一次有序初始列表C。
2. 按C规划。每接受一个事件，用原active_expansions/effective_policy及selector对模拟状态**内存重投影**；资格重检直接调用同一个 `automatic_candidates(simulated_context)`，沿用当前候选dict成员关系判断，不能另写路径判断或放宽相等条件。不再次全量load/Gate。
3. 按task/trigger/object/source_hash去重。scope真实改变仍是新基准，不能忽略scope hash。
4. 三类结果互斥：
   - **资格消失**：初始候选因已接受事件而不再成立，不发射它；终止本次候选遍历，发布此前仍合法的有序前缀，然后继续最终Context生成。这不是source stale，也不触发整批零写入。
   - **初始列表之外的新候选**：本调用不追加、不重新发现，留给后续调用；与旧循环只取一次候选保持一致。
   - **真实错误**：源漂移、非法schema/非法候选、symlink、并发用户编辑等保持原非零错误；发布前发现时一条新事件都不写，不发布新Context。
5. 对稳定B的合法前缀计算events/budget_delta，一次stage/publish task预算与expansion log，保持原pre/post freshness检查；空前缀不写事件。
6. 发布后按新canonical输入生成最终Context，执行独立完整validate和bundle publication。后校验不省略。

旧算法在资格消失时已发布合法前缀但本次报 `CONTEXT_STALE`，重试才可能完成。新契约在此情形直接完成本次生成：**首次exit由失败变成功是用户本次评审明确批准的行为变更**，单独列入兼容和回归，不归入failure atomicity，也不声称单调用退出码完全等价。稳定终态及事件前缀与旧算法保留一致；若后续重试产生额外候选，应按相同调用/候选边界比较，不假称一次batch等价于任意多次旧算法重试。

### 6.3 一致性与故障契约

- 一个批次内event预算/log更新是同一事务；无半条事件或budget/log不一致。
- publication失败按已有事务恢复规则处理，不覆盖并发用户编辑；process crash按既有transaction恢复机制验证，不能只测试Python exception。
- 新批次成功后、最终Context生成失败：合法batch审计可保留，旧Context将因source变化stale；下次dedup重试。不得将“扩展已写”当“Context已验证”。
- 用户评审接受：源漂移及发布故障零写入新events（发布中故障仅恢复本操作拥有的字节；crash须完成既有恢复机制验收）。这项failure atomicity变化不包括“资格消失”。后者必须发布合法前缀并继续，不能回到同一基线无穷重试。
- 不增加未授权risk/profile迁移，不减少每条event的budget统计。最大policy为EXPANDED也仍保留必要审计事件。

### 6.4 结构性验收

对稳定source、N=0/1/10/50/100，按§5.1函数入口定义验收：**full_context_builds≤2、source_loads≤3、gate_assessments≤3**，不随N线性增长。最终validate只计load和assess；capture另计，不藏计数。它们是硬结构验收，不是测得的加速数字。

正常完整候选路径与reference逐事件算法对比：除generated时间/hash和telemetry外，control、working、omitted、references、policy、event字段/顺序、budget、blockers一致。资格消失case另比较已批准的合法前缀/稳定终态及首次退出码差异；真实错误按已批准failure atomicity验收。hash按新canonical输入重算，不搬旧hash。

N循环主要变成必要内存selection/事件规划，而不是N次I/O和Gate全量评估。若内存selection仍占主导，另测另提案，不自动扩大本次缓存范围。

## 7. P0-C / P1-A：验证前诊断与有审计的范围对账

### 7.1 只读快速诊断（P0）

拟接口：

```bash
harness evidence plan --json
harness impact reconcile --file proposal.yaml --dry-run
```

只读取已有声明路径，不扫描全仓库生成猜测覆盖，不调用外部测试或生产环境。

输出分类：

- `MISSING_DECLARED_TEST`：缺文件/selector，连同引用它的REQ/INV/case/plan item。
- `UNBOUND_TEST_CASE`：已有case未绑定。
- `PLAN_ITEM_UNRECONCILED`：哪项缺证明，不自动COMPLETE。
- `EVIDENCE_HEAD_MISMATCH`、`EVIDENCE_WORKSPACE_STALE`：保留现有原因区分。
- `NO_FRESH_COVERAGE`：按实际covered_tests缺集给最小相关执行计划。
- 独立显示未授权环境动作、环境前置未验证或共享资源串行约束；不猜成测试已通过。

**只读诊断是建议，不是有效Context、不授执行权限、不替代Gate。** schema/不可读源错误fail-closed，不用部分可读结果继续变更。

先完成所有可获批元数据修正，再一次生成正式Context；无法避开的Context失效应提示原因，而非静默一遍遍重建。

### 7.2 范围变更入口（P1，批准后实施）

当前CLI主要支持add，[controlplane.py:2873–2989](../src/harness/controlplane.py#L2873)；没有退役必测项的成对对账接口。新入口不能是无约束`remove-test`。

拟接口：

```bash
harness impact reconcile --file proposal.yaml
```

```yaml
version: 1
task_id: TASK-1038001
expected_impact_hash: sha256:<original>
retirements:
  - test: backend/tests/archived_example.py
    reason_code: ACCEPTED_SCOPE_RESET
    decision_ref: DEC-010
    replacement_tests: [backend/tests/current_contract.py]
bindings:
  - owner: REQ-001
    case: TC-001
    tests: [backend/tests/test_database_profile.py]
```

示例不证明DEC-010授权任意test退役。实施层必须验证：

1. task身份/原hash、path containment、可执行selector、涉及的全部case/plan references；查证decision status/selected scope/constraints，而不是仅接受一个DEC ID字符串。
2. 每个移除路径：明确范围退出或现存替代覆盖。替代路径存在不证明业务等价；等价由contract/accepted decision和后续test evidence共同验证。
3. 没有替代且仍属must requirement的路径：拒绝变更；不能留下空test_plan再称已收口。退出整个requirement属contract变更，走原realignment/user-authority/re-freeze，不由impact编辑器顺手完成。
4. 新绑定不自动写verified/evidence，不复用未执行selector，不清除findings/失败历史。bindings只能改现存case的测试映射，不能重写statement/priority/severity。
5. 所有受影响artifact一次事务更新，附append-only审计（before/after hash、paths、decision refs、reason、timestamp），并标记Context需再生成。
6. sealed boundary drift仍调用原Guard。打印 `USER_AUTHORITY_REQUIRED/HALT_AND_WAIT` 即停；不得为省时间自动freeze或resume。
7. 单纯add只授权扩展，不默认允许retire；退出范围必须有可验证明确用户决策。没有支持的授权路径时返回typed blocker，不能hand-edit绕过。

可先交付只读plan/dry-run，测试/外部命令执行计数必须为0。**§7.3 Gate强制点与权限验证通过之前，不交付apply。** E03的18条路径维持未解决，不恢复归档代码、直接改impact删除路径或虚构测试。

### 7.3 强制点：Gate拒绝无审计缩减（P1 apply的先决条件）

仅CLI检查不够：当前 `capture()` 将required_tests纳入版本，但不判断缩减是否合法。用户直接改 `impact.yaml` 后重建Context，可能形成新鲜但无退役审计的视图。新检查必须进入 **`quality_gate.assess_gate` 的公共评估路径**，经 `FileContextSource.load` 投影为Control Core typed blockers；`harness gate`、Context生成、阶段迁移都共享该检查，不能只在reconcile handler运行。

拟私有接口：`assess_test_scope_retirements(harness_dir) -> typed blockers`。输入为当前impact、task-bound受保护原始范围基线、append-only范围审计、actual decisions及contract/case/plan绑定。不得把audit当授权source；授权仍来自有效用户决策/封存契约。

- 原始基线包含task_id、最初已获授权的required_tests和source hash，按既有sealed boundary规则保护；后续范围增加/退役用append-only记录，包含sequence、previous hash、before/after范围、decision refs及affected bindings。审计与基线必须显式加入schema、source_access/read_scope和 `capture()`，不能作为derived telemetry排除。
- 评估器从原始基线顺序重放审计，验证链完整、task匹配、每次缩减的decision状态、selected scope、constraints和权限，得到允许的必测集合；任何历史增加也保留在重放链，避免新增项随后无审计消失。
- 既有任务在审计功能启用前增加的路径，继续按“未入链的纯增加”处理，直到获授权迁移将它们纳入可信基线；不能把该历史兼容规则用于启用后的新增路径。
- **§7.3 Gate检查与同事务 `impact add-test` 必须同一次启用**，不能先启用Gate、后补add审计。启用后正式add-test必须将impact变化与受保护范围基线更新/追加add审计同一次事务提交，禁止分开写或异步补审计，否则“先add、再手改删”可绕过检查。该联动发布、旧任务迁移机制、故障回滚及兼容测试必须在Gate检查启用前就绪，不仅是apply前置；**不要求所有既有任务的数据迁移先完成**。既有任务可在启用之后逐项完成获授权数据迁移，期间无可信基线的任务保持typed blocker。apply仍晚于检查/add-test联动、seal迁移机制及权限验收；不能借apply跳过具体任务的可信基线或授权要求。
- 当前required_tests少于已授权集合且无有效退役审计，返回拟新增 `TEST_SCOPE_RETIREMENT_UNAUDITED`；audit损坏/缺失/重写或无可信基线返回 `TEST_SCOPE_AUDIT_INVALID`；决策/constraints不足返回 `TEST_SCOPE_RETIREMENT_UNAUTHORIZED`。schema/读取错误fail-closed，不用缺文件当空集合。
- 替代文件存在仅通过路径检查，不证明业务等价。仍在scope的must obligation没有有效覆盖映射时继续阻断；绑定存在也不自动verified，必须另有fresh evidence。
- 直接删impact路径、删/重写audit、修改受保护baseline、仅填DEC编号或伪造替代路径，均须阻断。hash链仅用于一致性，不宣称能抵抗拥有全盘写权限者重写所有来源；保护边界与现有seal/authority机制共同验收。
- 老任务无可信基线/审计时返回typed blocker，走显式获授权的历史范围重建/迁移；不能用当前缩减列表自动初始化并自证合法。E03应以可追溯的原64路径范围审议，不能将剩余46条默认当新基线。§7.3合入后TASK-1038001也预期阻断，直至原64路径范围完成获授权迁移；这是预期安全收紧，不是回归漏网。

基线/审计schema版本与seal接入需在实现前确定并同步迁移规范；在其未具备Gate保护前，apply仍禁止。不能以新增CLI已完成宣称EF-INV-08已实现。

## 8. P1-B：一次调用内复用与既有evidence reuse

### 8.1 解析复用

仅在profiling显示证据schema/YAML验证占显著成本后实施。首选一次command内immutable source对象和schema validator复用。

复用键至少包含canonical path、原始content SHA-256、schema hash、validator/projection版本、task、当前HEAD及workspace；任何依赖、目录成员集或源字节变更必须重新评估。不能仅按mtime/size复用，不能把旧Gate blocker列表当新结果。

边界：canonical facts仍在capture/require_fresh处重新确认；standalone `context validate` 必须独立读取，不能复用前一次命令内存。持久缓存与跨命令可信缓存排除于本spec。

### 8.2 不重造已有evidence能力

当前已有 `--reuse-if-valid`，见 [collect_evidence.py:824–853](../src/harness/collect_evidence.py#L824)、[test_cli_evidence_reuse.py](../tests/test_cli_evidence_reuse.py)。推荐调度器使用既有检查，不再另造“看到exit0就跳过”的逻辑。

复用直接调用既有 **`can_reuse_evidence(record, ReuseRequest, current_head, current_workspace, current_runtime)`**，不得按下列摘要重写谓词或建立更宽松的快捷分支。任务边界由当前 `.harness/evidence/` 目录和collector决定；record没有单独task_id字段，不能发明字段比较冒充当前契约。

当前谓词要求phase为缺省或green且record与request一致、exit_code==0、type/command一致；unit/integration/contract的scope一致；covered_tests与covered_test_cases分别集合全等；HEAD及前后workspace匹配；runtime全等且schema有效；request finding_id/test_id为空，record subject/test为空。**合法GREEN复用现在已支持**，不是新功能。`EVIDENCE_REUSED`与`EXECUTED`明确区分。

RED/finding reproduction、HEAD/command/coverage/workspace/runtime任一不匹配或其他谓词条件失败：按现有collector分支执行原命令，仍服从预算/权限等原检查，不能以旧exit0跳过。E05–E11均为历史commit `f26069ea` 的摘要，不是可供当前HEAD复用的proof。

HEAD改变后的内容等价继承、环境epoch/依赖版本的新proof模型需要独立设计，**不在本次授权内**。纯文档是否属于产品fingerprint也不全局自动豁免。

## 9. 调度流程优化（无需先改产品代码）

推荐稳定工作批次：

```text
读取合法Context/仅在失败时做只读诊断
 → 一次整理impact、scope、test bindings及已批准决策
 → 生成/验证正式Context
 → 执行最小相关RED/GREEN与必要恢复检查
 → 每个Plan Item及时保存实际proof并合法reconcile
 → 冻结本次review source snapshot
 → complexity / diagnosability / 独立review
 → 合法阶段迁移与最终Gate
```

- 不把所有P项积压到最后；不为通过入口强标COMPLETE。
- 两个互斥资源组：共享PG状态用例、共享MySQL/config/Redis/MinIO/ES用例各组内串行；只有可证明不同隔离资源的组才能并行。
- 输出统一记录实际command、cwd、root-relative covered_tests、exit code、起止时间、精确cleanup和环境身份。first-error、timeout和failed-provider证据保留。
- source变更后重新跑精确失败项及受影响测试；只是复审metadata写入不要求盲重跑业务测试，但Context仍应更新。
- provider失败不是review PASS；重复retry有限预算，有新证据/假设再试。最终read-only review包source hash稳定后再启动，减少每个小改动都重读整任务。
- 有效snapshot若随后scope/contract改变，显式记录失效，不能“最后再补一条impact”而把前面的验证当当前authority。

## 10. 验收矩阵与benchmark

### 10.1 必须新增或扩展的反例

| Case | 检查 |
|---|---|
| EF-T01 | N=0/1/10/50/100事件；固定完整build/load/Gate次数上界 |
| EF-T02 | 正常成功语义与reference一致；共用event构造、automatic source_hash覆盖、RISK_ESCALATED history from/to和最大policy自环；人工expand_context仍逐事件 |
| EF-T03 | 第一条后候选资格消失即停止；消失点之后即使仍在初始列表且合格，本次也不发射，留给下一次生成；提交合法前缀并本次成功，重试不重复前缀/无无穷回滚；不追加初始列表外候选；首次exit差异单独断言 |
| EF-T04 | 同task/trigger/object/source_hash重跑无新event；basis真实改变新增事件 |
| EF-T05 | 不同task历史decision不进入当前Control Core或触发扩展；同task历史RED保留 |
| EF-T06 | stage/publish前后并发用户edit、symlink substitution、目录成员变化均fail-closed，不回滚用户字节 |
| EF-T07 | 发布异常/KeyboardInterrupt/进程中断；预算/log一致或可证明恢复；没有新鲜旧Context假象 |
| EF-T08 | profile默认关闭零新失败；exclusive总和/入口计数；发布前失败exit2+false；stdout输出后profile OSError走独立exit3+固定stderr，不被cmd_context收成2；原子写入无半份JSON；CANCELLED锁外且带真实context_published；无Secret/self-stale |
| EF-T09 | 18缺失target fixture在测试执行前分类报错，执行counter=0；不是删文件来制造GREEN |
| EF-T10 | 未授权retire拒绝、accepted decision不覆盖路径拒绝、替代不存在拒绝、must空绑定拒绝 |
| EF-T11 | Gate/Context手改impact删路径阻断；audit/baseline缺失或重写、仅DEC ID拒绝；Gate检查与同事务add-test同一次启用，启用后新增再手改删仍阻断；add-test+基线/audit故障无partial state；启用前历史增加待授权迁移；合法审计保持pending、CAS失败无部分写入、sealed drift仍HALT；旧任务缺可信基线阻断；只读plan/dry-run执行计数0 |
| EF-T12 | `.harness`仅验证状态更新不stale产品proof；HEAD/产品/test/被纳入配置变化仍stale |
| EF-T13 | 直接沿用can_reuse_evidence；缺省/合法GREEN复用；HEAD/command/scope/两种coverage/workspace/runtime/schema/subject/test错误拒绝；RED/finding执行原命令，任务目录隔离 |
| EF-T14 | 合法范围输入下批处理前后全局控制事实、既有blocked集合、risk/authorizations等价；无审计缩减另断言新增Gate blockers而非旧漏洞行为；无自宣称Gate PASS |

优先复用现存 [test_context_automatic](../tests/test_context_automatic.py)、[test_context_expansion](../tests/test_context_expansion.py)、[test_context_integrity](../tests/test_context_integrity.py)、[test_context_freshness_property](../tests/test_context_freshness_property.py)、[test_context_read_scope](../tests/test_context_read_scope.py)、[test_impact_control_plane](../tests/test_impact_control_plane.py)、[test_evidence_freshness_and_path_binding](../tests/test_evidence_freshness_and_path_binding.py)、[test_cli_evidence_reuse](../tests/test_cli_evidence_reuse.py)。路径是现有回归入口，不声称已覆盖上述新cases或已执行。

### 10.2 可重复benchmark

固定Python/OS/依赖版本、CPU资源、repo/workspace输入、HEAD、schema、artifact/evidence数、policy和候选类型；发布匿名fixture生成器与seed，禁止复制用户Secret/全量业务数据。

- 冷基准：每次用**全新相同fixture**，N=0/1/10/50/100，分别执行旧reference和新实现至少5次。
- 稳态：生成一次后，未改source再生成/validate，分别测至少5次；和冷态分开。
- 记录median/min/max与分阶段计时；5次只能作小样本，不宣称统计稳定p95。
- 成功/失败结果、freshness、blocker集合和审计字段都对比，不仅比stdout字节数或wall time；资格消失首次exit变化按EF-T03显式验收，范围退役新增blockers按EF-T11/14显式验收，不把已批准的差异当隐式等价。
- **硬验收仅为EF-T01/02/06及其余结构/安全用例。** v0.1提出的N≥50冷态median降50%、N=0退化≤10%，用户本次评审明确**不采纳为验收条件**；仅保留为历史提议，不用于阻断/宣称PASS，也未测达成。报告真实测量及原因，不弱化安全断言。
- 不设置本案例原环境绝对“小于30秒”的验收线。现场212秒不是固定fixture；旧timeout不能以exit0作为benchmark样本。
- 最后可在本案例冻结只读状态下复测Context，但不得执行迁移/seed或触碰production。不使用变更后的fixture去冒充同输入加速。

## 11. 兼容、发布、回滚与顺序

1. 先合入独立telemetry与counter测试；旧默认CLI输出/行为不变。
2. 批量自动扩展：沿用event schema和共用构造；显式记录已批准的资格消失首次exit变化、真实错误failure atomicity。保持连续锁和人工expand_context语义；增加mandatory字段须显式迁移，不改历史log/hash。
3. 先交付只读plan/dry-run；Gate范围退役检查与同事务add-test完成联动验收并同一次启用，不留只启用前者的窗口。apply在这两者、可信基线/append-only审计机制、schema/seal迁移机制与规范及权限/contract Guard全部验收之后交付。此处与§7.3一致：验收对象是机制与规范，不要求每个既有任务的数据迁移先完成；具体任务没有可信基线或有效授权时，apply继续被Gate阻断，不能借功能交付跳过任务前置。
4. 最后根据profile决定是否需要一次调用内parse cache；无证据则不做。
5. rollback只回退实现，不删除合法events、历史proof和scope审计。若新增schema旧版不能读，必须阻止旧版运行而非抹掉记录。
6. Agent技能说明同步先对账后昂贵验证、复用合法proof、相关测试和资源互斥规则；不把新的CLI草案写成现已可执行命令。

### 用户评审决议与实施前置

- 已接受：源漂移/发布故障零写入；资格消失发布合法前缀并完成生成，首次退出码变化单列，不混同failure atomicity。
- 已确定：Gate拒绝无审计缩减前，不交付apply；不从本案例或DEC编号泛化权限。
- 已确定：profile默认关闭、安全输出路径、发布后profile失败独立结果码；50%/10%不采纳为验收。
- 实施前仍须细化Gate基线/audit schema与seal迁移、退出码3冲突检查；这些是受§7.3强制点约束的前置，不授权先做无Gate保护的apply。

## 12. 本文完成度与未验证声明

本轮仅完成：源码/既有记录核对、字段级脱敏证据摘要、接口和验收设计、文档格式/链接/hash核查。不执行任何Harness任务命令、业务测试、性能benchmark、迁移/seed或部署。

v0.1已收到用户提供的源码/证据评审；v0.2按其结论修订并收到可作为实现契约的评审；v0.3消除旧句冲突、核对cmd_context并明确集成分支，获得用户提供的实现契约评审结论；v0.4关闭Gate/add-test启用窗口并补齐EF-T03停止断言；v0.5明确启用前要求迁移机制/回滚/兼容测试就绪，既有任务数据迁移可在启用后完成、期间维持typed blocker；v0.6将§11.3发布清单同步为机制/规范验收口径，具体任务apply仍受Gate约束，不改变已批准语义。本文修订自查不等于实现review、人类Approval或deterministic Gate。所有拟新增接口尚未实现/验收；没有新benchmark，也没有TASK-1038001状态变化。

修订清单：资格消失/真实错误三分支、共用event构造/RISK history、连续可重入锁、函数计数、Gate范围退役强制点、exclusive计时、cmd_context发布前2/发布后独立3分支、profile原子改名、CANCELLED实际context_published、同事务add-test与Gate检查同一次启用、启用前历史增加获授权迁移、消失点后初始合格候选本次不发射、既有reuse谓词、撤销50%/10%验收条件。原E01–E11/S01–S10证据包不改写；新增判断可直接对照 [telemetry_lock](../src/harness/telemetry_lock.py)、[event构造](../src/harness/context/escalation.py#L244)、[Gate公共评估](../src/harness/quality_gate.py#L1284)、[capture范围](../src/harness/context/freshness.py)、[reuse谓词](../src/harness/evidence_validator.py#L37)。不能引用本文声称优化已生效或任务已Ready。

# Superpowers Engineering Harness v0.2.8 实施契约

> 版本：v0.2.8  
> 状态：Implementation Contract（对实现有约束力）  
> 日期：2026-09-11  
> 基线代码：v0.2.7 / 当前 `main`  
> 愿景规格：`docs/Superpowers-Engineering-Harness-v0.2.8-Context-Execution-Efficiency-Spec.md`  
> 范围：Engineering Harness 控制面；不修改业务项目代码

本文件冻结 v0.2.8 **实际要做、实际能验收** 的范围。愿景规格保留意图与长期设计；二者冲突时，**以实现契约为准**。

本次边界修订对应 [契约验收用例清单](./Superpowers-Engineering-Harness-v0.2.8-Contract-Acceptance-Cases.md)。清单是待实现测试要求，不是已通过证据。

---

## 1. 效力

1. 本契约约束 v0.2.8 的代码、schema、CLI、SKILL、测试和发版门槛。
2. 愿景规格中未写入本契约的条目，默认 **Deferred**，不得当作 Product Done。
3. 禁止用「先实现优化、再补契约」绕过本文的数据源、兼容性和 Done 分级。

---

## 2. 版本目标

v0.2.8 建设 Context Control 与 Cost Observability，不靠削弱 Gate / Review / Evidence 来省 token。

```text
authoritative .harness state
        ↓
deterministic projection
        ↓
compact agent context
        ↓
Context Integrity Gate (fail-closed)
```

目标表述：

> Agent 只获取当前决策所需信息；任何被省略的信息必须可检测、可解释、可追溯、可恢复。

禁止表述为「让 Agent 知道得更少」。

---

## 3. Done 分级

v0.2.8 **发版只认 Product Done**。Experiment Done 是宿主会话实验，不挡 tag。

### 3.1 Product Done（发版门槛）

必须全部满足：

1. Runtime metrics **契约**可用：宿主可上报 usage；未上报保持 `null`。
2. `save_task` / `update_telemetry` **不得清空**已上报的 agent usage。
3. Lossless Control Core：mandatory control facts 的 recall / accuracy = 100%。
4. Context Integrity CI-01～CI-12 自动校验；失败 fail-closed。
5. Mandatory Global Context 不被 relevance filter 删掉。
6. authoritative state 变化后，旧 compact context 自动 stale。
7. omitted 项均有 `reason` + `ref`。
8. 每次成功生成 compact context 都可写出 Context Evidence。
9. `harness context`（`--compact` / `--full` / `--json`）可用。
10. SKILL 规定：有活跃 task 时优先 `harness context --compact`，而不是逐个读取全部 `.harness` 文件。
11. 旧 benchmark artifact 缺新字段时标记 `INCONCLUSIVE`；禁止把缺失 metrics 当作 `0`。
12. 不改变 Q0 语义、不放宽既有 Gate、不删除既有 Review / Evidence / Test Plan。

### 3.2 Experiment Done（不挡发版）

以下内容需要真实 Agent / 宿主会话数据，本仓库 CI **不能**自行证明：

- `correctness(adaptive) >= correctness(baseline)` 的现场 Agent 跑分
- Q1 corpus 的 `median total_tokens` 下降
- `tokens_per_success` 改善
- N≥3 次运行的 median / P90
- calibration / holdout / adversarial 分层跑分
- Avoidable Token Ratio

允许提供 comparator 与报告格式；缺真实 usage 时整体 Efficiency 结果必须是 `INCONCLUSIVE`，不得 FAIL，也不得 PASS。

### 3.3 明确不纳入 v0.2.8 Product Done

- `harness review-context`
- Finding-scoped review context 切片（现有 `harness finding resume-review` 保持不变）
- File read cache / `UNCHANGED` / diff-only
- Evidence digest（pytest 结构化摘要）；attach 路径已有 digest 者不改语义
- Token attribution（control/source/tests/evidence/search 分项）
- Search / file_reads 的 soft budget **强制 override**（字段可预留，见 §8）
- embedding / vector DB / LLM 摘要作为 authoritative context
- 绑定单一 Agent Runtime 或 tokenizer
- 符号表 / LSP / AST 解析

---

## 4. 非目标

- 新的业务质量 Gate。
- 删除或放宽 Review / Evidence / Test Plan / Diagnosability Gate。
- 用减少安全检查换 token。
- 统一 token hard limit；达到 token 数量后硬 BLOCK。
- 把 `harness status` 改造成 compact context。status 仍是给人看的只读摘要。
- 把 compact context 写回 `requirements.yaml` / `invariants.yaml` / `current-task.yaml` 当作新事实源。
- 重构整个 `controlplane.py` 或把 Context 逻辑堆进 `quality_gate.py`。
- 修改 Q1/FAST 的 Light Gate：FAST 仍不因 Context 功能去加载或强制 requirements/invariants。

---

## 5. Q0 边界

Q0 不进入本版本 Context Policy。

| 规则 | 约束 |
|---|---|
| 分级 | `risk.py` 与 `task.schema.json` 仍只有 `Q1/Q2/Q3` |
| 行为 | Q0 不创建 task、不读 `.harness`、不跑 `harness status`、不跑 `harness context` |
| SKILL | Q0 Decision Table 保持不变 |
| 无 task | `harness context*` 对缺失 `current-task.yaml` 返回既有 `INVALID_HARNESS_STATE` / exit 2 |
| 未分类 task | task 合法但 risk 缺失或为 null 时，`harness context*` 返回 `INVALID_HARNESS_STATE` / exit 2，提示先 classify；不得推断 risk/profile |

愿景规格 §13 的 `Q0 → MINIMAL` **作废**。

---

## 6. 权威数据源（禁止发明事实）

Context 只投影已有 artifact。禁止为了 YAML 示例新增第二份权威字段。

| Control Core 字段 | 权威来源 | 投影规则 |
|---|---|---|
| `task.id` / `state` | `current-task.yaml` | 原值 |
| `risk` / `profile` | `current-task.yaml` `risk` | 原值；缺失则按现有 task 规则 fail-closed |
| MUST requirements | `requirements.yaml` 中 `priority: must` | 完整记录；禁止摘要 statement |
| invariants | `invariants.yaml` 全部条目 | 全部进入 Layer 0；`pending/verified/violated` 原值 |
| decisions | `decisions/` 中 `status: ACCEPTED` | 完整记录 |
| findings | `findings/*.yaml` 且 `status ∈ OPEN_FINDING_STATUSES` | 完整记录。`OPEN_FINDING_STATUSES` = `PROPOSED, REPRODUCING, CONFIRMED, FIXING, FIXED` |
| finding 关联 | 现有 `target`（`REQ\|INV-n`） | **不**新增 `affected_requirements` |
| blockers | `assess_gate(..., allow_preflight=True)` | typed blocker 文档，与 status 投影一致 |
| scope | `current-task.yaml` `scope` | `owned_paths` / `protected_user_paths` 无损 |
| authorization | `current-task.yaml` `authorizations` | 原值 |
| constraints.security 等 | `risk.dimensions` 原枚举 | 只投影 `none/low/high`，不生成自然语言约束 |
| contract 约束 | 已声明 Interface Contract + `impact.contracts` | 只投影 id / 引用，不复制合同正文进 Layer 0 |
| observability | `observability.yaml` 若存在 | 投影 `required` 与 applicability 引用 |
| evidence freshness | `workspace.snapshot()` + evidence projection | 状态码，不把 raw stdout 塞进 Layer 0 |
| gate | live gate assessment | `status` + `blocked_by` |

Q1/FAST 允许 requirements/invariants 为空列表。空集上的 Integrity recall 视为 100%。**不得**为了 Context 去改变 FAST Gate。

文件缺失：

- 缺 `current-task.yaml`：既有错误。
- `requirements.yaml` / `invariants.yaml`：init 正常会创建。文件存在但 schema 非法 → fail-closed。FAST 且文件缺失 → 视为空列表。Q2/Q3 且文件缺失 → fail-closed。

---

## 7. Context 三层与 Policy

```text
Context = Layer 0 Lossless Global Core
        + Layer 1 Deterministic Working Set
        + Layer 2 Expandable References
```

### 7.1 Layer 0

禁止 LLM 摘要、禁止丢 ID、禁止把枚举改成近义自然语言、禁止裁剪：

- 全部 MUST requirements
- 全部 invariants
- 全部 ACCEPTED decisions
- 全部 OPEN/BLOCKING findings
- 全部 blockers
- 全部 `owned_paths` / `protected_user_paths`
- `risk.level` / `risk.profile` / `risk.dimensions`
- live gate blocking status

### 7.2 Layer 1 Working Set（确定性，禁止语义相似度）

允许进入 Working Set 的 **should/could** requirement，仅当：

- 某 open finding 的 `target` 等于该 id；或
- 其 `test_plan.cases[].tests` 中任一条目路径前缀落在 `owned_paths` 内。

允许进入 Working Set 的测试与文件：

- `impact.changed`
- `scope.owned_paths`
- `impact.required_tests`
- open finding 的 `regression_test.path`（若有）

`next_action` 只能由 `state` + `risk.profile` 按现有 SKILL dispatch 表投影，禁止模型生成。

候选集合限定为本次 source manifest 中的控制记录，以及由 scope、impact、finding、decision、已声明 contract/evidence 显式引用的文件或对象。不得为构造 omitted 默认枚举整个仓库。

候选集合中未内联的 should/could requirement、closed finding、非 owned 源文件、evidence raw 正文必须进入 `omitted`。未声明、未发现的仓库文件不属于该集合；manifest 必须说明候选集边界，不宣称已发现全部隐藏依赖。目录引用作为单个对象保留，不默认递归列出内容；显式展开后，新发现的对象加入候选集。

### 7.3 Layer 2

对 omitted 或未内联的大对象保留：

```yaml
ref: ".harness/requirements.yaml#REQ-027-06"
sha256: sha256:...
```

引用必须可解析（CI-08）。

### 7.3.1 引用与路径规则

- 文件 ref 使用仓库根相对路径；拒绝绝对路径、`..` 路径段、解析到仓库外的符号链接。目录引用遵守同一边界。
- fragment 按源文档 id 精确定位，必须恰好匹配一条记录；零匹配或重复匹配均为 `CONTEXT_REFERENCE_BROKEN`。文件引用 sha256 绑定整个源文件原始字节。
- 测试 selector 原值保留；路径比较使用 `::` 前的文件部分。路径匹配不证明测试已执行，执行覆盖仍由既有 Test Plan / Evidence 校验。
- 包含关系按规范化路径段判定：`src/foo` 包含 `src/foo/a.py`，不包含 `src/foobar/a.py`；不得使用裸字符串前缀。
- 目录引用 hash 绑定目录身份，不默认递归 hash；展开文件分别绑定内容 hash。product workspace hash 保持既有 Git 语义，不因此承诺覆盖全部 ignored 文件。
- 已删除文件、未来测试路径作为原始控制事实保留，标记 `availability: missing`，引用声明它的现存 authoritative 记录；不得伪造直接指向不存在文件的可展开 ref。
- FAST 缺失 requirements/invariants 时记录稳定 missing/empty 源标记，不生成坏 ref；文件随后出现必须使旧 Context stale。

### 7.4 Risk → Context Policy

| Risk | Workflow | Context Policy |
|---|---|---|
| Q1 | FAST | LOCAL |
| Q2 | STANDARD | BOUNDED |
| Q3 | STRICT | EXPANDED |

LOCAL 默认不得把 full repo / full docs / full test suite 列入 Working Set。  
BOUNDED 允许 `impact.direct_dependents` 与 declared contracts。  
EXPANDED 允许更广的 impact/contract 展开，仍必须记录 expansions 与 omitted。

明确区分：

```text
base_policy      = policy(task.risk.level)
effective_policy = max(base_policy, 当前 task 已持久化的 expansion policy)
```

顺序为 `LOCAL < BOUNDED < EXPANDED`。Context 与 Context Evidence 的 `policy` 表示 effective policy，同时记录 base policy。扩大 Context 不修改 risk/profile，不增加执行授权，也不绕过已有风险升级规则。Agent 不得自行标记 effective policy，升级只走 §10。

CI-12 校验 task risk/profile 原值；另外校验 base policy 映射及 effective policy 的合法来源，违规返回 `CONTEXT_POLICY_MISMATCH`。

---

## 8. Telemetry 与 Budget 兼容

### 8.1 Usage 契约

宿主上报（字段均可 null，除 `source` 在有任一 token 字段时必填）：

```yaml
usage:
  provider: string | null
  model: string | null
  input_tokens: integer | null
  output_tokens: integer | null
  total_tokens: integer | null
  source: runtime | provider | estimated
  tool_calls: integer | null
  search_rounds: integer | null
  file_reads: integer | null
```

规则：

- Harness 不算 tokenizer，不猜测 tool calls。
- `source=estimated` 时 comparator 必须标记较低可信级别。
- 任一需要比较的 metric 为 `null` → 该比较 `INCONCLUSIVE`。
- 禁止 `null` 转 `0` 后宣称效率提升。

### 8.2 禁止覆盖

`telemetry.update_telemetry()` 更新 harness-local facts（elapsed、harness_command_calls、evidence 计数、gate、risk）时，必须保留已有 `agent` / `usage`，除非本次调用显式传入新 usage。

现有测试「未上报则为 null」继续成立。新增测试：上报后经过 `save_task`，usage 仍在。

CLI：

```bash
harness telemetry report --usage-file <path>
```

### 8.3 Usage 上报、隔离与一致性

- 上报是当前 task 的累计快照，不是增量；宿主负责跨会话汇总。usage-file 顶层必须含 `task_id` 与 `usage`，其中 usage 使用 §8.1 字段。
- 相同快照重复上报幂等，不累加。新快照整体替换宿主 usage 域，缺失 optional 字段规范化为 null，不从旧快照拼接；Harness-local facts 不被覆盖。
- 计数只接受非负整数或 null，拒绝布尔值、负数、浮点数。任一 token 非 null 时 source 必填；三项 token 均非 null 时要求 input + output = total。不从缺失字段推算 token。
- task_id 不匹配时拒绝且不改文件。新 task 不继承旧 task agent/usage；同 task 的普通 save_task 保留 usage。
- ingest 与本地 telemetry 更新共享串行化的 read-modify-write 边界，并原子替换文件；只有 atomic rename 不足以防并发丢更新。提交上报时重新核验 task 身份，发生变化则拒绝，不得跨任务写入。
- Context 读取/validate 不回写 usage 或递增 harness_command_calls；纯 telemetry 变化不使 Context stale。

### 8.4 Budget schema

`task.schema.json` 的 `budget` 保持 `additionalProperties: false`。新增 **optional** 计数：

```text
search_rounds
file_reads
context_expansions
```

不加入 `required`。旧 task 缺这些字段仍合法，读取时视为 `0`；这是本地 budget 计数默认值，不适用于缺失的宿主 metrics。
v0.2.8 Product Done **不**对 search/file_reads 做 FAST override 强制。`context_expansions` 统计 §10 已持久化的有效 expansion 事件，包括自动事件和显式 expand；自动去重事件不重复计数。超限不 fail-closed。

---

## 9. Context Integrity

在 Agent 使用 compact context 之前执行。失败码：

```text
CONTEXT_INCOMPLETE
CONTEXT_INACCURATE
CONTEXT_STALE
CONTEXT_REFERENCE_BROKEN
CONTEXT_POLICY_MISMATCH
CONTEXT_SCHEMA_INVALID
```

| ID | Invariant |
|---|---|
| CI-01 | 每个 `priority: must` requirement 完整存在于 Layer 0，或 Layer 2 给出可解析 ref（Product Done 选择：MUST **完整存在于 Layer 0**，不允许只留 ref） |
| CI-02 | 全部 invariant 完整存在于 Layer 0 |
| CI-03 | 全部 OPEN/BLOCKING findings 完整存在于 Layer 0 |
| CI-04 | 全部 ACCEPTED decisions 完整存在于 Layer 0 |
| CI-05 | `owned_paths` / `protected_user_paths` 与 task 一致且无损 |
| CI-06 | blockers 与 live preflight gate 一致 |
| CI-07 | context 内 status/enum 与 authoritative 文件逐字段相等；context 不得引入新 status |
| CI-08 | 所有 `ref` 可解析到现存文件或 fragment |
| CI-09 | `generated_from.*` 与当前源 hash 一致，否则 STALE |
| CI-10 | 每个 omitted 项含非空 `reason` 与 `ref` |
| CI-11 | context 文档通过 schema |
| CI-12 | context 中的 risk/profile 与 `current-task.yaml` 一致 |

`--compact` 默认 fail-closed：Integrity 失败则非 0 退出，不把损坏 compact 打到 stdout。  
`--full` 同样 fail-closed；调试用完整投影不得跳过 Integrity。

业务 Gate BLOCKED 不等于 Context Integrity 失败：源合法且 blockers 准确投影时，应成功输出 Context。源损坏、Gate 无法评估或投影不一致才拒绝；禁止复制 status 的异常后回退旧摘要策略。

### 9.1 Freshness hash

```yaml
generated_from:
  task_hash:
  requirements_hash:
  invariants_hash:
  findings_hash:
  decisions_hash:
  evidence_hash:
  impact_hash:
  workspace_hash:          # product fingerprint（v0.2.7 语义）
  control_plane_hash:      # Context 专用 authoritative source manifest 指纹，不是全 .harness 递归 hash
  head:
context_hash:
```

任一 authoritative 源变化 → 旧 context STALE。
**禁止**用 product workspace fingerprint 代替 control-plane hash。二者分开，与 v0.2.7 evidence freshness 拆分一致。

### 9.2 Source manifest 边界

新增 Context 专用 source manifest；不得直接使用现有 `control_plane_fingerprint()` 对全部 `.harness/` 文件递归 hash，也不重定义该 API。

必须纳入：

- current-task、requirements、invariants、impact；
- findings、decisions、interface-contracts、evidence 的相关 canonical 文件集合，成员名及新增/删除参与 hash；
- gate、risk boundaries、observability，以及 live Gate / evidence projection 实际读取的其他配置、artifact 和 raw evidence 依赖；
- 当前 task 的 `context/expansions.yaml`；
- Context 直接引用的工作文件内容 hash、product workspace hash 和 HEAD。

必须排除：context/current、manifest、evidence 等派生产物；staging、临时文件、历史归档、纯观测 telemetry/benchmark report。历史或观测 artifact 只有被显式声明为本次控制输入时才纳入。

源按规范路径排序，optional 缺失源使用稳定 missing 标记；manifest 记录存在性、原始字节 hash、目录成员边界和投影版本。相同输入与版本得到相同 context_hash，generated_at 不参与语义 hash。不得遗漏 Gate 间接依赖；读取未登记控制输入时拒绝发布。

SRC-09 的威胁模型经用户确认：防止可信 Harness Python 代码意外漏登记；不承诺拦截恶意原生扩展或任意子进程绕过。该边界不免除可信读取链的文件内容、缺失、目录成员和间接依赖登记义务。机制设计见 [SRC-09 受控读取设计](./Superpowers-Engineering-Harness-v0.2.8-SRC09-Design.md)；设计不等于实现或验收通过。

### 9.3 快照一致性与发布

构建开始采集源版本，完成构建及 live Gate assessment 后重新核验。中途源集合、内容、workspace 或 HEAD 变化，则 `CONTEXT_STALE` / exit 2，不发布混合 compact；调用方可重新生成。

Integrity 成功后才发布派生文件；current、manifest、evidence 必须携带同一 context_hash。读者遇到版本不一致必须拒绝；逐文件 atomic rename 不等于多文件原子快照。发布失败不得用半写入产物替代最后一份完整快照。

`context validate` 校验已落盘 current 与当前源，不重新生成后掩盖 stale，不写 task、telemetry 或派生产物。freshness 只在核验时成立；之后变化需再次 validate，不宣称可阻止宿主使用缓存旧文本。

---

## 10. Escalation

同一 task 的 effective policy 只升不降；base policy 仍由 risk 决定。记录：

```yaml
context_expansion:
  task_id: TASK-001
  source_hash: sha256:...
  from: LOCAL
  to: BOUNDED
  trigger: FINDING_OUTSIDE_SCOPE
  reason: "..."
```

写入 `.harness/context/expansions.yaml`，**不**把该结构做成 `current-task.yaml` 的 required 字段。新 task 不继承旧 expansion，旧 task 的 current Context 也不得用于新 task。

自动 trigger 按 task_id、trigger、对象 id、触发依据源指纹去重；该指纹只绑定触发对象及 scope 等判定输入，不包含 expansion 自身、budget 或无关源变化。相同依据重复生成不得重复记录、逐次升级或增加 budget。自动 expansion 先完成控制写入，再从更新后的源构建 Context，禁止发布写入前快照。

### 10.1 Core 可自动判定的 trigger

Harness 在生成 context 时可以检测并记录（或拒绝 compact）：

| Trigger | 判定 |
|---|---|
| `FINDING_OUTSIDE_SCOPE` | finding 的 `regression_test.path` 或可解析路径不在 `owned_paths` 内 |
| `DECISION_OUTSIDE_SCOPE` | ACCEPTED decision 的 `scope[]` 与 `owned_paths` 无交集且 scope 非空 |
| `TEST_FAILURE_OUTSIDE_WORKING_SET` | 失败 evidence 的 `covered_tests` 不在 Layer 1 测试集 |
| `RISK_ESCALATED` | 已有 `harness task escalate`；随后 context policy 跟随新 risk |
| `CONTEXT_INTEGRITY_UNPROVEN` | Integrity 失败 → fail-closed，不「升级后凑合用 compact」 |

### 10.2 仅允许上报的 trigger

Core **不做**符号解析、依赖图推断、需求-实现语义匹配。必须由 Agent 调用：

```bash
harness context expand --trigger SYMBOL_UNRESOLVED --reason "..."
```

允许的上报枚举：

```text
SYMBOL_UNRESOLVED
REQUIREMENT_UNMAPPED
CROSS_MODULE_DEPENDENCY
API_OR_CONFIG_CHANGE
INSUFFICIENT_CONTEXT
```

非法枚举 → exit 2。合法 expand 递增 `budget.context_expansions`（若字段存在或按 optional 写入），并记录 expansion。LOCAL→BOUNDED→EXPANDED 单调。已是 EXPANDED 时再 expand：记录 trigger，policy 不变。

愿景规格 AC-028-07「全部 10 个 trigger 都有测试」收窄为：§10.1 与 §10.2 列出的枚举都有测试；不要求 Core 自己发现符号无法解析。

---

## 11. CLI

必须：

```bash
harness context                 # 默认 --compact
harness context --compact
harness context --full
harness context --json
harness context validate
harness context explain
harness context expand --trigger <ENUM> --reason <text>
harness telemetry report --usage-file <path>
```

stdout：

- 默认 YAML compact context
- `--json` 为同一文档的 JSON
- `explain` 输出 included / omitted / global / expansions 及 reason
- `validate` 只跑 Integrity，不要求打印全文

退出码：与现有 CLI 一致（0 成功，2 非法状态/用法，Integrity 失败为 2）。

P1（本版本不做）：`harness review-context`。

---

## 12. 落盘位置

current、manifest、evidence 是 derived view，不是 authoritative state；expansions 是 CLI 持久化的控制事件输入，不属于派生输出。

```text
.harness/context/
  current.yaml       最近一次成功生成的 context
  manifest.yaml      sources loaded/included 计数
  evidence.yaml      Context Evidence（当时 Agent 应看到什么）
  expansions.yaml    policy 升级记录
```

禁止把上述文件当作 Gate 的 product evidence。  
Context Evidence 至少包含：task_id、context_hash、generated_at、base_policy、policy、generated_from、integrity 四元组、included ids、omitted、expansions。

v0.2.8 Product Done 只保证**最近一次成功生成的完整快照**，三份派生文件关联同一 context_hash；失败生成不覆盖它。历史不可变快照与宿主消费回执延后。该证据只能证明 Harness 生成/提供了什么，不能证明 Agent 实际读取或遵循了什么，也不提供完整历史会话追溯。

---

## 13. 代码结构

新建包，不要把实现塞进 `quality_gate.py`：

```text
src/harness/context/
  __init__.py
  model.py
  builder.py          # authoritative → Control Core + references
  selector.py         # policy → working set + omitted
  integrity.py
  freshness.py
  policy.py           # Q1/Q2/Q3 → LOCAL/BOUNDED/EXPANDED
  escalation.py
  evidence.py
```

`cli.py` 只解析参数；`controlplane.py` 只路由。  
`UsageProvider` / `ContextSelector` / `ContextIntegrityChecker` 用 Protocol，测试可注入。不绑定 Agent Runtime。

---

## 14. SKILL 变更

`SKILL.md` Session Startup 在 **存在已分类的活跃 mutating task** 时改为：

```text
1. Detect .harness/
2. harness context --compact
3. 若 Integrity 失败：停止依赖 compact；按错误码处理，不得继续用损坏 context
4. 不得把 context 当作新的事实源；写回只通过既有 harness CLI
```

必须保留：

- Q0 Decision Table（先于 Session Startup）
- 「No state in context only」：权威仍是磁盘上的 `current-task.yaml`
- 禁止手改 state 字段

未分类的 CREATED task 先走既有 classify 路径，不要求先成功生成 Context；允许只读 task 分类字段以完成该路由，不读取全部控制文件。合法旧 task 的 risk 缺失/null 不得被静默补成某个 profile。

删除或降级「一上来就读全部 requirements/invariants/findings/evidence 文件」的默认路径。  
Agent 仍可通过 Layer 2 ref 按需 `Read` 单个文件。

---

## 15. Benchmark

保持现有 corpus 校验与 comparator 入口。扩展：

- artifact 可带 `usage` 与 `agent` 字段
- 缺字段 → `INCONCLUSIVE`
- 新增 `tokens_per_success` **计算函数**：全部尝试（包括失败尝试）的 total_tokens 之和 / 成功尝试数；任一尝试 total_tokens 或成功状态未知、零成功或空输入时为 INCONCLUSIVE，不输出 0。成功定义绑定 fixture 的全部 required_correctness，不由省 token 与否决定。
- 不把 AC-028-10 做成 CI 红灯

v0.2.7 的 AC16–18（Q1 算术平均 tool_calls / token_estimate / elapsed）保留为历史 comparator，不在本版本改为 median 以免假 PASS。新报告若输出 median，必须与旧 AC 分列。

新增独立 v0.2.8 总判定，禁止将历史效率子指标 PASS 当作优化成功：

1. 已知 Integrity 失败或 correctness regression → FAIL，即使 metrics 缺失或成本下降。
2. 无已知失败但任一必要 integrity/correctness/metrics 数据缺失 → INCONCLUSIVE；不得把 null 转 0。
3. 前两层有完整通过证据后，才比较效率。成功率下降不得以 token 降幅抵消；完整真实数据达到约定实验门槛才可 PASS，否则 FAIL。
4. 无已知安全/正确性失败时，estimated usage 单列低可信比较，不作为真实 runtime token 改善证明；真实效率结论保持 INCONCLUSIVE，优先于第 3 条的效率门槛比较。已知失败仍按第 1 条 FAIL。

报告分别列出历史 AC、Product Done 测试证据和 Experiment 总判定。缺外部实验数据不阻止 Product Done，不生成虚构 baseline。

---

## 16. 测试（Product Done 必须）

### Unit

- Q1/Q2/Q3 → LOCAL/BOUNDED/EXPANDED
- MUST / invariant / open finding / accepted decision / protected path 永不进入 omitted
- should requirement 无路径/finding 绑定时进入 omitted 且含 reason+ref
- omitted 缺 reason 或 ref → Integrity 失败
- context hash 稳定（相同输入相同 hash）
- 任一源文件变化 → STALE
- product fingerprint 变化 → STALE；仅 `.harness/` 元数据变化 → control_plane_hash 变、不得把既有 **product** evidence 标成 `EVIDENCE_WORKSPACE_STALE`
- usage 上报后 `save_task` 不丢失
- 未上报 usage 仍为 null
- null metric 不得当 0
- expand 非法 trigger → exit 2
- expand 单调升级

### Property

- 任意随机 MUST/invariant/open finding 子集：Layer 0 超集包含它们
- 任意 authoritative hash 变化：旧 context 校验为 STALE

### Integration

```text
task classify
 → context compact
 → 改 requirements.yaml
 → validate 报 STALE
 → 重新 compact 成功
```

### Adversarial（合成 `.harness` fixture，不跑外部 Agent）

- 非目标模块上的 invariant 仍在 Layer 0
- protected_user_path 仍在 Layer 0
- reopened / open finding 不可省略
- ACCEPTED decision 不可省略
- Q1 compact 的 Working Set 不含仓库级 docs 全量列表

不要求本仓库启动外部 Agent 来证明 token 下降。

---

## 17. 实施顺序

只按此顺序合并。禁止先做 Working Set 优化再补 Integrity。

| Step | 内容 | 完成判据 |
|---|---|---|
| 0 | 契约边界与验收用例冻结 | 本契约及关联用例清单一致；尚未执行项明确标记 |
| 1 | Telemetry ingest + 禁止覆盖 | `telemetry report`；save_task 保留 usage，快照幂等且任务隔离 |
| 2 | Control Core builder + `--full` | 单测 100% fact recall |
| 3 | Integrity / freshness / omitted | CI-01～12 全绿；失败 fail-closed |
| 4 | Selector + Policy | Q1 无 full-repo working set；全局核不被滤掉 |
| 5 | `harness context` CLI + 落盘 + Context Evidence | compact/full/json/validate/explain |
| 6 | expand 上报 + expansions 记录 | §10 枚举有测试 |
| 7 | SKILL.md + README/CLI help | Session Startup 改为优先 compact |

Step 1 可先于 Context 包合并。Step 4 不得先于 Step 3。

---

## 18. 兼容性

- 已分类、risk/profile 合法的旧 `current-task.yaml` 不迁移即可 `harness context`；未分类旧 task 先 classify，见 §5、§14。
- 不要求旧 task 具备 `budget.search_rounds` 等新字段。
- 现有 evidence / findings / decisions schema 不为 Context 做破坏性 required 变更。
- `harness status` 输出契约保持不变。
- 缺 usage 的 benchmark artifact → `INCONCLUSIVE`。

---

## 19. 文档

Product Done 必须同步：

- `SKILL.md`
- `README.md` / `README.zh-CN.md`（增加 `harness context`，不删除 Q0 表）
- CLI help
- 本契约与关联验收用例清单

愿景规格不必改写成与本契约逐段相同；在愿景规格文首增加指向本契约的说明即可（实现阶段做，不阻塞本文件生效）。

---

## 20. 最终原则

```text
Correctness Safety  → fail closed
Efficiency Budget   → soft / 本版本不强制
Missing Metrics     → INCONCLUSIVE, never 0
Q0                  → 不进 Context
Authoritative state → .harness artifacts
Context             → derived view only
```

v0.2.8 Product Done ≠ 「模型说节省了 token」。  
v0.2.8 Product Done =

```text
Integrity Evidence
+
Usage Contract
+
Deterministic Compact Context
+
SKILL 改读路径
```

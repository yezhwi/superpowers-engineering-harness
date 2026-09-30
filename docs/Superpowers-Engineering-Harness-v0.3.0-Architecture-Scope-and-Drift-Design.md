# Superpowers Engineering Harness v0.3.0 — Architecture Scope & Drift Design

> 版本：v0.3.0 设计规格
> 状态：Review Candidate
> 范围：Architecture model、确定性 ownership、Alignment freeze、Q2/Q3 Gate、Context projection 与 evaluation
> 前置版本：v0.2.10 Plan Execution Reconciliation
> 设计原则：Architecture 是声明式约束，不是自动推断出的系统真相。

---

## 1. 文档权威与交付边界

本设计取代原 `v0.2.10 Architecture Awareness` 草案。v0.2.10 的既定交付是 Plan Execution Reconciliation；Architecture Scope & Drift 属于 v0.3.0，不回填旧版本。

本设计覆盖完整语义边界，并分阶段交付：

- **P0**：Architecture artifact、ownership resolver、Alignment seal、Q2/Q3 Architecture Gate；
- **P1**：权威 Context projection 与 freshness；
- **P2**：带标注 corpus 的行为与成本评估。

本设计不授权实现、发布、迁移用户数据或自动生成 Architecture model。实施仍需独立 Task Contract、实现计划、TDD、review 和 Gate。

---

## 2. 问题定义

当前 Harness 可以冻结任务合同、文件 scope、接口边界、测试计划与 Plan execution，但没有仓库级、机器可读的模块归属模型。因此文件级事实无法回答：

1. 当前任务声明影响哪些模块；
2. 实际改动路径解析到哪些模块；
3. 实际模块是否越过已冻结声明；
4. Context restart 后应恢复哪些结构信息；
5. Architecture model 或 task module scope 是否在实现期间发生漂移。

v0.3.0 引入的机械声明仅为：

> 当前任务可归属的实际改动路径，没有越过已冻结的声明模块范围。

Architecture Gate **不能证明**：

- module 划分代表真实业务架构；
- `depends_on` 是完整调用图或数据流图；
- 未修改 module 不受行为影响；
- Agent 已理解 Context；
- token 或 tool cost 一定降低。

这些内容只能由设计 review、Task Contract、测试、人工标注 benchmark 或外部工程事实支持。

---

## 3. 目标

### G1. Canonical Architecture Data

使用版本化 YAML 描述 module、责任、dependency、evidence 与路径 ownership。

### G2. Deterministic Ownership

相同 artifact 与 canonical path 在所有受支持平台得到相同解析结果；冲突不得静默 tie-break。

### G3. Frozen Task Module Scope

Task 声明的 module scope 与 Architecture semantic fingerprint 一起进入现有 Alignment seal。

### G4. Diff-based Drift Detection

由 task-attributable Git change records 推导 actual modules，并与 declared modules 比较。

### G5. Source-isolated Context

仅在 Q2/Q3 required 模式加载 Architecture；Context 只投影 declared modules 与一层 dependency。

### G6. One Control-plane Authority

复用 Alignment、Decision、realignment、Gate、recovery、lock 与 atomic publication；不创建平行控制面。

---

## 4. 非目标

v0.3.0 不实现：

- 自动推断 module、ownership、dependency 或 scope；
- 全量静态调用图、运行时 tracing 或数据流分析；
- UML、HTML viewer、IDE 插件或 Architecture 可视化；
- Architecture 专用 Decision store、Finding lifecycle 或 convergence loop；
- persistent resolver cache、后台索引或仓库 watcher；
- 根据 LLM 判断覆盖机械 resolver 结果；
- 用 architecture declaration 替代 Requirements、Invariants、Impact、Plan 或 tests；
- 自动把 direct dependency 加入 task scope；
- 以 `HEAD != repository_revision` 推断 stale。

---

## 5. 术语

| 术语 | 定义 |
|---|---|
| Architecture Model | `.harness/architecture.yaml` 中的仓库级声明模型 |
| Module | 稳定 ID 标识的责任边界 |
| Ownership Rule | canonical path pattern 到 module 集合及 path kind 的声明 |
| Declared Modules | `current-task.scope.modules` 中由当前任务声明并冻结的 module 集合 |
| Actual Modules | task-attributable changed paths 经 resolver 得到的 module 并集 |
| Architecture Drift | `actual_modules - declared_modules` 非空 |
| Semantic Fingerprint | 对规范化 Architecture 语义字段计算的 SHA-256 |
| Task-attributable Change | 现有 workspace authority 判定属于当前任务的 changed-path record |
| Support Path | 仍受 file scope 管理，但不映射业务 module 的路径 |

---

## 6. 激活与 source isolation

现有 `.harness/gate.yaml` 增加可选配置：

```yaml
gate:
  architecture:
    mode: required
```

规则：

- 缺少 `gate.architecture` 配置等价于 `mode: off`；
- mode 仅允许 `off | required`；
- 不提供语义模糊的 advisory Gate；
- `harness architecture check` 可在不持久化 Gate 结果的前提下提供只读诊断；
- `required` 仅作用于 Q2/STANDARD 与 Q3/STRICT；
- P0 必须扩展 `gate.schema.json` 与默认 template；legacy config 缺少该字段仍合法；
- 现有 Gate 在 FAST/Q1 分支前仍读取并校验 `gate.yaml`；Architecture 不改变该顺序；
- FAST/Q1 和 mode off 不读取 `architecture.yaml`、不加载 `architecture.schema.json`、不调用 resolver 或 Architecture Git adapter；
- 静态 import 本身不是隔离承诺：P0 必须把纯 Architecture domain module 加入 `context.dependency_closure.ALLOWED`，不得加入 `ADAPTERS`；
- `source_access` 与 `git_query` 继续作为现有 audited adapters；
- 损坏但 disabled 的 Architecture artifact 不得影响 FAST/Q1 或 mode-off task。

该顺序必须在 P0 由 source-access spy、schema-load spy 与 dependency-closure tests 证明，不能只由控制流注释声称。

---

## 7. Canonical Architecture Artifact

### 7.1 生命周期

`.harness/architecture.yaml` 是仓库级 canonical artifact，不是单任务 execution artifact：

- `harness task new` 不归档、不重置它；
- `harness init` 不覆盖已存在 artifact；
- 更新只能通过 validated publication command；
- canonical artifact 必须是 repository 内普通 UTF-8 文件，拒绝 symlink、目录与仓库外解析；
- Gate、Context 和 CLI 通过 `source_access` 读取；
- 文件正文不复制到其他 canonical artifact。

### 7.2 Schema

```yaml
version: 1

modules:
  - id: auth
    name: Authentication
    responsibility: Authenticate users and authorize requests.
    depends_on: [session]
    evidence:
      - type: source
        path: src/auth/service.py

  - id: session
    name: Session
    responsibility: Manage session lifecycle.
    depends_on: []
    evidence:
      - type: source
        path: src/session/store.py

  - id: payment
    name: Payment
    responsibility: Authorize and record payments.
    depends_on: []
    evidence:
      - type: documentation
        path: docs/architecture/payment.md

ownership:
  - id: OWN-001
    pattern: src/auth/**
    kind: production
    modules: [auth]

  - id: OWN-002
    pattern: src/shared/**
    kind: shared
    modules: [auth, payment]

  - id: OWN-003
    pattern: tests/**
    kind: support
    modules: []

  - id: OWN-004
    pattern: src/future/**
    kind: production
    modules: [payment]
    allow_empty: true
    empty_reason: Planned module anchored by docs/architecture/payment.md.
```

### 7.3 Module validation

每个 module 必须满足：

- `id` 唯一，匹配 `^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`；
- `name` 与 `responsibility` 为非空字符串；
- `depends_on` 无重复，引用存在 module；
- 禁止 self-dependency；
- dependency cycle 允许存在，因为该字段是声明关系，不是 build DAG；
- `evidence` 至少一项；
- evidence `type` 仅允许 `source | config | documentation`；
- evidence path 为 canonical repository-relative path，且 publication 时指向存在的 regular file；
- evidence path 拒绝 symlink、目录与仓库外解析；
- validator 不读取 evidence 文件正文。

### 7.4 Ownership validation

`kind` 仅允许 `production | shared | support`：

- ownership `id` 唯一，匹配 `^OWN-[0-9]+$`；
- `production`：必须恰好一个 module；
- `shared`：必须至少两个不同 module；
- `support`：modules 必须为空；
- module refs 必须存在；
- `allow_empty` 默认 `false`；
- `allow_empty: false` 时，publication 必须匹配至少一个 tracked 或 task-attributable path；
- `allow_empty: true` 时必须提供非空 `empty_reason`，且对应 module 必须已有 source/config/documentation evidence；
- `allow_empty: false` 的 rule 若被本任务 deleted record 命中，且当前 workspace 已无匹配 path，Gate 返回 `ARCHITECTURE_OWNERSHIP_EMPTY`；
- `allow_empty` 不授权创建目录、源码或 scope。

Architecture Model 不保存 `generated_at`、`repository_revision`、scan result 或 machine-local path。

### 7.5 Hard bounds

Schema 与 loader 固定以下上限，超过上限属于 Invalid Harness State：

- canonical YAML：1 MiB UTF-8；
- modules：256；
- ownership rules：1024；
- declared modules/task：64；
- dependencies/module：32；
- evidence records/module：16；
- module ID：64 code points；
- name：128 code points；
- responsibility：512 code points；
- path/pattern/empty reason：512 code points。

Context `relevant_modules` 去重后最多 256 项。全局 module 数已经限制为 256，因此合法 projection 的唯一项上界是 `min(256, 64 + 64 × 32) = 256`。达到上限仍执行完整确定性 projection；超过上限只能来自 malformed input，禁止截断或静默遗漏。

---

## 8. Architecture Semantic Fingerprint

Fingerprint 输入为规范化后的：

- `version`；
- modules 的 `id`、`name`、`responsibility`、sorted dependencies、sorted evidence records；
- ownership 的 `id`、`pattern`、`kind`、sorted module IDs、`allow_empty`、`empty_reason`。

规范化规则：

- mappings 按 key 排序；
- modules 按 ID 排序；
- dependencies 与 evidence records 排序；
- ownership rules 按 normalized tuple 排序；
- UTF-8 JSON 使用固定 separator；
- 输出格式为 `sha256:<64 lowercase hex>`。

YAML key order、array presentation order、comments 和 whitespace 不改变 fingerprint。任何 Architecture 语义字段改变都改变 fingerprint。

---

## 9. 单一 Alignment Freeze

Architecture 不拥有独立 freeze authority。v0.3 的 `harness align freeze` 对新 freeze 一律写 `alignment-freeze.yaml` v2。Required 示例：

```yaml
version: 2
task_id: TASK-123
contract_hash: sha256:...
architecture_mode: required
architecture_fingerprint: sha256:...
declared_modules: [auth, session]
decision_selections: {}
boundary_refs:
  interface: []
  permission: []
  persistence: []
frozen_at: "2026-10-01T00:00:00Z"
```

Off 示例：

```yaml
version: 2
task_id: TASK-124
contract_hash: sha256:...
architecture_mode: off
architecture_fingerprint: null
declared_modules: []
decision_selections: {}
boundary_refs:
  interface: []
  permission: []
  persistence: []
frozen_at: "2026-10-01T00:00:00Z"
```

`harness align freeze` 必须：

1. 读取并校验 `gate.architecture.mode`；
2. required 时加载 Architecture artifact，并在任何默认值归一化前要求 `current-task.yaml` 的 `scope` 中必须显式存在 `modules` key；显式 `modules: []` 才表示 support-only task；非空列表必须无重复且全部存在；缺失 key 返回 `ARCHITECTURE_SCOPE_DECLARATION_REQUIRED`；
3. off 时不读取 Architecture artifact，且 seal 固定 `architecture_fingerprint: null`、`declared_modules: []`；
4. 将 mode、Alignment contract、Architecture fields、Decision selections 与 boundary refs 原子发布到同一个 seal。

Compatibility/mode matrix：

| Current mode | Existing seal | Result before Architecture artifact read |
|---|---|---|
| off | missing，PLANNED → IMPLEMENTING 或 IMPLEMENTING → VERIFYING phase-entry | Architecture disabled；按既有兼容语义补一份 legacy v1 seal |
| off | missing，read-only Gate | Architecture disabled；按既有 Alignment read-only 语义报告 `CONTRACT_CHANGED`，不写 seal |
| off | legacy v1 | Architecture disabled；继续现有 Alignment 语义 |
| off | v2/off | Architecture disabled |
| off | v2/required | `CONTRACT_CHANGED` |
| required | missing or legacy v1 | `CONTRACT_CHANGED`；必须在 Gate 前迁移 |
| required | v2/off | `CONTRACT_CHANGED` |
| required | v2/required | 再比较 fingerprint 与 declared modules |

Legacy v1 只在 off 模式兼容；任何显式 v0.3 re-freeze 都升级为 v2，不静默修改既有 seal。`alignment-freeze.schema.json` 必须以 `oneOf` 同时接受既有 v1 与新 v2；只把 schema 常量从 1 改成 2 会令现有 v1 seal 在 Context 中错误变成 `CONTEXT_SCHEMA_INVALID`。required 模式在语义层拒绝 v1，而不是在共享 schema 层拒绝。

只有 `harness align freeze` 发布 v2 Architecture-aware seal。为保持现有 off-mode STANDARD/STRICT task 的 phase-entry 行为，P0 把隐式默认值改为显式无默认参数 `bootstrap_legacy_off`：

- off phase-entry（PLANNED → IMPLEMENTING、IMPLEMENTING → VERIFYING）在 seal missing 时传 `bootstrap_legacy_off=True`，只允许按 legacy `freeze_record` 原子补一份 version 1 seal；已有 v1/v2 seal 只读校验；
- required phase-entry 固定 `bootstrap_legacy_off=False`；missing 或 v1 返回 `CONTRACT_CHANGED`，零写入；
- Gate 与 Context 固定 `bootstrap_legacy_off=False`；off Context 不运行 Architecture seal assessment，required Context 与所有 Gate assessment 都不得发布 seal；
- v2 从不由 bootstrap 路径生成；`validate_sealed_freeze()`/`sealed_freeze_drift()` 必须按实际 seal version 比较对应字段，不能拿 v1 expected record 比较 v2 seal。

因此 phase-entry 的 legacy v1 completion 是唯一兼容例外，不是 Architecture freeze authority；显式 freeze、realignment 或 policy 变更仍只能由 `harness align freeze` 原子发布 v2。

Architecture mode、fingerprint 或 declared modules 与 v2 seal 不一致时返回现有 `CONTRACT_CHANGED`。Realignment 使用现有状态机、Decision threshold 与 seal publication，不新增授权流。

### 9.1 Task replacement 中的 repository policy

`gate.yaml` 会被 task template 整文件替换，因此 P0 必须同时修改 `task new` 与 `task recover`：

1. 替换前计算 trusted mode：存在 schema-valid 且 `task_id` 与被替换 task 相同的 trusted v2 seal 时取 `architecture_mode`；不存在 v2 seal 时取当前已校验的 `gate.architecture.mode`；seal task identity 不匹配则 replacement fail-closed；
2. 复制 gate template 后，把 trusted mode 写回新 task 的 `gate.architecture.mode`；
3. malformed gate 或 seal 令 replacement 原子失败，不发布部分 task；
4. `architecture.yaml` 继续保留，不移动 mode authority，也不新增配置文件。

因此，当前 task 直接把 required 改为 off 时，v2 seal 仍使 `CONTRACT_CHANGED` 终止该 task；后续 `task new` 会从 trusted v2 seal 恢复 required，不会因 template 默认 off 让 blocker 消失。用户若批准 mode 变更，必须在 replacement task 的 SPECIFYING 中修改 policy 并由新的 v2 freeze 封存。

---

## 10. Ownership Pattern Grammar

只接受 canonical POSIX repository-relative path：

- 禁止 absolute path；
- 禁止空 segment、`.`、`..`；
- 禁止反斜杠；
- 大小写敏感，不采用宿主文件系统 case folding；
- resolver 不跟随 symlink target，只处理 Git 记录的 repository path。

Pattern 只允许：

1. literal path：`src/auth/service.py`；
2. single-segment wildcard：`src/*/service.py`；
3. trailing recursive wildcard：`src/auth/**`。

禁止：

- `?`；
- character class `[]`；
- brace expansion `{}`；
- 非末尾 `**`；
- shell escape 或平台特定 glob。

`*` 匹配恰好一个非空 segment。末尾 `/**` 匹配该目录下一个或多个 path segments；changed-path records 始终表示文件路径，不把目录节点本身作为 change record。

---

## 11. Deterministic Resolver

### 11.1 Score

每个匹配规则计算：

```text
(
  exact_literal ? 1 : 0,
  literal_segment_count,
  total_segment_count
)
```

使用 lexicographic maximum：

1. exact literal 优先；
2. literal segments 更多者优先；
3. total segments 更多者优先。

### 11.2 Result

- 无匹配：`unresolved`；
- 唯一最高 score：`resolved`；
- 多个最高 score：`ambiguous`；
- shared rule 返回多个显式 modules，状态仍为 `resolved`；
- 不按 artifact 顺序、module ID 或字典序打破 tie。

示例输出：

```yaml
path: src/auth/service.py
status: resolved
kind: production
modules: [auth]
rule_id: OWN-001
pattern: src/auth/**
score: [0, 2, 3]
```

Validator 在 publication 时拒绝 duplicate rule IDs 和 duplicate rules，并使用第 13 节定义的同一份 canonical Git path index 检测同分冲突；不得另用目录遍历或宿主文件系统 case folding。未来新增路径仍可能形成新 ambiguity，因此 Gate 必须再次按 changed paths 执行 resolver。

---

## 12. Changed-path Semantics

现有 `changed_paths_since()` 只返回 path 集合，不能满足 Architecture 对 delete-side identity 的要求。P0 必须新增一个固定 Git adapter，返回：

```text
ArchitectureChangeRecord(kind, path)
kind = added | modified | deleted | untracked
```

`<base>` 固定取 `current-task.git.base_commit`（不是可移动的 `base_ref`），先通过现有 `verify_git_ref()` 拒绝 flag-like/不存在的值并解析为 commit。Adapter 只能通过现有 `git_query` seam 执行以下固定 argv；每条 path query 都复用 `workspace._PRODUCT_EXCLUDE` 的 `.harness` exclusions：

```text
git diff --name-status --no-renames --no-ext-diff --no-textconv -z <base>..HEAD -- . :(exclude).harness :(exclude).harness/**
git diff --name-status --no-renames --no-ext-diff --no-textconv -z HEAD -- . :(exclude).harness :(exclude).harness/**
git diff --cached --name-status --no-renames --no-ext-diff --no-textconv -z HEAD -- . :(exclude).harness :(exclude).harness/**
git ls-files --others --exclude-standard -z -- . :(exclude).harness :(exclude).harness/**
git ls-files -z -- . :(exclude).harness :(exclude).harness/**
git ls-files --deleted -z -- . :(exclude).harness :(exclude).harness/**
```

四个 change sources 分别是 `committed | staged | worktree | untracked`。这与现有 workspace authority 对 committed history、index-only change、worktree-only change 与 untracked path 的并集语义一致；单条 `git diff <base>` 不能覆盖“index 已改、worktree 恢复到 baseline”的 staged-only counterexample。

确定性规则：

- 禁用 rename/copy detection、external diff 与 textconv，不读取用户 Git rename threshold；
- Git `A`→`added`、`M`/`T`→`modified`、`D`→`deleted`；
- `U`、`X`、`B` 或未知 status 抛出 `WorkspaceError("ARCHITECTURE_CHANGESET_INVALID")`，由 Gate 转为 Invalid Harness State；不持久化 blocker、不猜测归属；
- rename 由 `--no-renames` 规范化为旧路径 `deleted` + 新路径 `added`；
- copy 规范化为 destination `added`；source 仅在自身内容变化时另有 `modified` record；
- untracked paths 由第四条命令补充为 `untracked`；最终 records 按 `(path, kind)` 排序、去重；
- 同一路径可以保留多个不同 kind record，不选择虚构的单一 final kind；resolver 对 path 去重一次，ownership-empty predicate 只在该 path 含 `deleted` 且 canonical current-path index 不再匹配 rule 时触发；
- committed add 后 worktree delete、cached modify 后 worktree restore 等相反 layer 仍保留各自事实；不得宣称 add-then-delete 或 delete-then-restore 一律无 record；
- path 使用 Git 输出的 repository-relative bytes 解码为 UTF-8 canonical POSIX path；非法编码、absolute、`.`、`..` 或反斜杠 fail-closed；
- 所有六条命令固定排除 `.harness` control-plane paths；docs/ 与 tests/、root Markdown 和 support paths 必须保留，禁止调用 `business_paths()`。

Task attribution 使用固定集合公式：

```text
preexisting_user_paths = set(task.risk.user_changes.paths)
owned_paths            = set(task.scope.owned_paths)
excluded_user_paths     = preexisting_user_paths - owned_paths
attributable_records    = records whose path is not in excluded_user_paths
```

显式 adopt 通过把 path 加入 `owned_paths` 使其进入 attribution；未 adopt 的 task-start user paths 保持排除。Architecture 不复用 `mechanical_surface_facts()` 的 aggregate-fingerprint branch，也不创建第二套 Git baseline 或 workspace fingerprint。

本设计不新增 File Scope Gate。现有 protected-path、review-scope、diagnosability 与 Plan checks 继续保持各自语义；Architecture Gate 只消费上述 attributable records 并验证 module scope。

---

## 13. Actual Module Derivation

对每个 task-attributable changed path：

- production：加入唯一 owner module；
- shared：加入全部显式 owner modules；
- support：不加入 module；该 path 仍留在 attributable records 与现有非 Architecture checks 中；
- unresolved：记录 path diagnostic；
- ambiguous：记录 path 与所有同分 rules。

Resolver 每个请求构造一次 canonical current-path index：`tracked_paths - deleted_paths + untracked_paths`，其中 tracked paths 来自第五条 `git ls-files -z`，deleted paths 来自第六条 `git ls-files --deleted -z`，untracked paths 来自第四条命令；不得从某一 change layer 的 `deleted` record 猜测最终文件存在性，也不读取文件正文。Publication 与 Gate resolver 必须复用同一份 canonical Git path index。Publication 对全部 `allow_empty: false` rules 执行 coverage validation；Gate 仅检查本任务 records 中含 `deleted` kind 且曾匹配的 rules。若该 rule 在应用当前 task workspace 后不再匹配 current-path index，产生 `ARCHITECTURE_OWNERSHIP_EMPTY`。无关 module 的既有 empty rule 不消耗当前任务 convergence iteration。该 index 仅 request-local，不持久化。

然后计算：

```text
actual_modules     = union(resolved production/shared modules)
unexpected_modules = actual_modules - declared_modules
```

support-only task 可以保持 `declared_modules: []`。shared path 要求 declared modules 包含全部显式 owners。Harness 不根据 `depends_on` 自动扩张 declared modules；dependency 仅用于 Context 与人工 impact reasoning。

---

## 14. Architecture Gate

### 14.1 Assessment 顺序

```text
validate gate policy
→ FAST/Q1 Architecture-local early return
→ compare sealed architecture_mode without reading Architecture artifact
→ mode off: Architecture-local early return
→ required artifact presence
→ parse/schema/semantic structure
→ required task scope.modules presence（首次 freeze 前缺失由 freeze 拒绝；sealed 后缺失属于 contract drift）
→ Alignment v2 seal fingerprint/modules match
→ evidence path validity
→ declared module references
→ typed changed-path collection
→ ownership resolution
→ actual vs declared module comparison
```

Architecture-local short-circuit 只停止依赖不可信 Architecture 输入的后续 Architecture checks。例如 missing artifact 不继续计算 ownership，fingerprint mismatch 不继续计算 drift。除 Invalid Harness State 必须终止整个命令外，requirements、evidence、diagnosability、findings、Plan 等 independent Gate checks 仍在同一次 assessment 中执行并合并 blockers，避免串行消耗 convergence iteration。

### 14.2 Missing 与 malformed

- required artifact 缺失是 blocker data：`ARCHITECTURE_REQUIRED`；
- present YAML parse/schema/reference corruption 是 Invalid Harness State；
- malformed present artifact 禁止 fallback 到 off、空模型或旧 Context；
- evidence path 在 freeze 后消失产生 `ARCHITECTURE_EVIDENCE_INVALID` blocker；
- Gate 不修改 Architecture、scope、Alignment 或 Finding。

### 14.3 Stable blockers、category 与 identity

所有可修复 Architecture blockers 使用 `category: implementation`。`GateBlocker.recover_to` 仅为展示字段；`harness resume` 的唯一 routing authority 是 `RECOVERY_POLICY`。

Stable identity 使用以下序列化值：

```yaml
source: path:<canonical-path>
source: module:<module-id>
source: path:<canonical-path>|module:<module-id>
source: ownership:<OWN-id>
source: artifact:.harness/architecture.yaml
```

| Code | 条件 | Stable `source` identity | `RECOVERY_POLICY` |
|---|---|---|---|
| `ARCHITECTURE_REQUIRED` | required artifact 缺失 | `artifact:.harness/architecture.yaml` | `IMPLEMENTING` |
| `ARCHITECTURE_SCOPE_INVALID` | schema-valid task 引用不存在的 declared module | `module:<module-id>` | `IMPLEMENTING` |
| `ARCHITECTURE_EVIDENCE_INVALID` | frozen module evidence path 不存在 | `path:<canonical-path>` | `IMPLEMENTING` |
| `ARCHITECTURE_OWNERSHIP_EMPTY` | 本任务 delete 后 rule 变空 | `ownership:<OWN-id>` | `IMPLEMENTING` |
| `ARCHITECTURE_OWNERSHIP_UNRESOLVED` | attributable changed path 无匹配 rule | `path:<canonical-path>` | `IMPLEMENTING` |
| `ARCHITECTURE_OWNERSHIP_AMBIGUOUS` | attributable changed path 出现最高分 tie | `path:<canonical-path>` | `IMPLEMENTING` |
| `ARCHITECTURE_SCOPE_DRIFT` | resolved path 包含未声明 module | `path:<canonical-path>|module:<module-id>` | `IMPLEMENTING` |
| `CONTRACT_CHANGED` | mode、fingerprint、declared modules 或 required seal version 不匹配 | `artifact:.harness/alignment-freeze.yaml` | `ESCALATED`（user authority；不可 resume） |

P0 必须在现有 map 中加入：

```python
{
    "ARCHITECTURE_REQUIRED": "IMPLEMENTING",
    "ARCHITECTURE_SCOPE_INVALID": "IMPLEMENTING",
    "ARCHITECTURE_EVIDENCE_INVALID": "IMPLEMENTING",
    "ARCHITECTURE_OWNERSHIP_EMPTY": "IMPLEMENTING",
    "ARCHITECTURE_OWNERSHIP_UNRESOLVED": "IMPLEMENTING",
    "ARCHITECTURE_OWNERSHIP_AMBIGUOUS": "IMPLEMENTING",
    "ARCHITECTURE_SCOPE_DRIFT": "IMPLEMENTING",
}
```

不同 path/module/rule 必须产生不同 `source`，因为 convergence fingerprint 不包含 message。Scope drift 每个 `(canonical path, unexpected module)` 产生一个 blocker；同一文件解析出的多个未声明 shared owners 分别记录。Ambiguity message 使用 ownership rule IDs，不使用不存在的 pattern ID。

Diagnostics 按 canonical path、code、module ID 排序，不输出 responsibility、evidence 文件正文或任意源码。

### 14.4 Single Gate Authority

只有 `harness gate` 评估并持久化产品 Gate 结果。Architecture commands 不打印竞争性的 convergence `DECISION:`，不增加 iteration，不修改 convergence metadata。

`harness gate preflight` 与 Context build 各自在单次命令请求内最多构造一个 Architecture assessment，并由该请求内的 Gate/projection consumers 复用；不同进程或不同命令之间不共享 cache。

---

## 15. Scope Expansion 与 Realignment

实现中发现新 module 时禁止：

```text
发现 gateway
→ 自动加入 scope
→ 继续实现
```

当 Architecture blocker 是 `select_recovery()` 按现有 category priority 选中的最高优先级 blocker 时，持久化 Gate 的合法流程为：

```text
harness gate                         # GATING → BLOCKED
harness resume                       # BLOCKED → IMPLEMENTING
harness transition SPECIFYING --reason SCOPE_DRIFT
                                     # IMPLEMENTING → SPECIFYING，清除旧 freeze/seal
→ 更新 Architecture model 或 current-task.scope.modules
→ 重评 Requirements / Invariants / Test Plan / Impact
→ 达到现有阈值时请求并持久化 Decision
→ harness align freeze
→ harness transition PLANNED
→ 校验既有 evidence/minimal-implementation.yaml
→ 若 approach 已变化或既有 evidence 无效：
  harness check minimal --file <decision.yaml>
→ harness transition IMPLEMENTING      # 重新校验 minimal、Test Plan、freeze 与 sealed freeze
```

既有 evidence/minimal-implementation.yaml 若仍能通过 `complexity.validate_minimal_decision()` 且 approach 未变化，不必重写；需要刷新时 CLI 必须带 `--file`，不能记录不可运行的裸 `harness check minimal`。

因此唯一回程是 `SPECIFYING → PLANNED → IMPLEMENTING`；`SPECIFYING → IMPLEMENTING` 不是合法 edge。

同次 assessment 若存在更高优先级 `defect` blocker，现有 `select_recovery()` 可先路由到 REPRODUCING；Architecture 不覆盖该优先级。更高优先级 blocker 关闭后，剩余 Architecture blocker 才按其 `RECOVERY_POLICY` 路由 IMPLEMENTING。

Read-only `harness gate preflight` 与 review PASS preflight 不持久化 BLOCKED state。CLI 必须按 blocker code 与当前 state 输出修复路径；非 evidence Architecture blocker 的标题使用 `GATE_PREFLIGHT_BLOCKED`，不得误报为 `GATE_PREFLIGHT_MISSING_EVIDENCE`。P0 在受控 review reason codes 中新增 `ARCHITECTURE_SCOPE_INCOMPLETE`。

| 当前 state | Repairable Architecture preflight 路径 |
|---|---|
| SPECIFYING | 在当前 state 修复并重新 freeze |
| IMPLEMENTING | `harness transition SPECIFYING --reason SCOPE_DRIFT` |
| VERIFYING | `harness transition IMPLEMENTING`，再进入 SPECIFYING |
| REVIEWING | `harness review outcome VERIFICATION_GAP --reason-code ARCHITECTURE_SCOPE_INCOMPLETE`，到 VERIFYING 后依次进入 IMPLEMENTING、SPECIFYING |
| GATING | `harness gate` 持久化 BLOCKED，再由 `harness resume` 按 priority 恢复 |
| BLOCKED | 使用既有 `harness resume`；不得按 preflight 文案直接跳 state |
| PLANNED | 先运行 `harness transition IMPLEMENTING`；成功后立即运行 `harness transition SPECIFYING --reason SCOPE_DRIFT`。若只缺/失效 minimal decision，可先用带 `--file` 的 check 修复后重试。`harness task recover` 仅作为 fallback：入口 prerequisites 无法在 PLANNED 合法补齐时才创建 replacement task |
| CONVERGED | 先 `harness transition DONE`，再使用 `harness task new` |
| DONE / ESCALATED | 使用 `harness task new` |

#### User-authority CONTRACT_CHANGED preflight continuation

本表只处理 preflight 已输出 `HALT_AND_WAIT`、随后取得用户授权的 `CONTRACT_CHANGED`；不复用 repairable blocker table：

| 当前 state | 用户授权后的合法续行 |
|---|---|
| SPECIFYING | 在当前 state 修复 contract，随后显式 freeze |
| IMPLEMENTING | 用户确认后运行 `harness transition SPECIFYING --reason SCOPE_DRIFT` |
| VERIFYING | 用户确认后先 `harness transition IMPLEMENTING`，再进入 SPECIFYING |
| REVIEWING | 用户确认后运行 `harness review outcome VERIFICATION_GAP --reason-code ARCHITECTURE_SCOPE_INCOMPLETE`，随后依次进入 VERIFYING、IMPLEMENTING、SPECIFYING |
| PLANNED | 用户确认后使用 `harness task recover` 创建 replacement task；不得重试注定被 required missing/v1 seal 拒绝的 PLANNED → IMPLEMENTING |
| GATING | 用户确认后运行 `harness gate`，持久化路径为 GATING → BLOCKED → ESCALATED，再使用 `harness task new` |
| BLOCKED | 按已持久化 blocker 运行 `harness resume`；没有 recovery route 时任务应已是 ESCALATED，不为 preflight 临时发明 route |
| REPRODUCING | 完成当前 Finding lifecycle，按 Finding 状态进入 REVIEWING 或 FIXING，再沿合法边到 VERIFYING 后使用其 authority route；不得跳过 Finding lifecycle |
| FIXING | 完成 fix 与 Finding 状态更新后运行 `harness transition VERIFYING`，再使用 VERIFYING authority route |
| CONVERGED | 使用 `harness task recover`；此时 `harness transition DONE` 会重新执行 Gate，并因新 `CONTRACT_CHANGED` 失败 |
| DONE / ESCALATED | 使用 `harness task new` |

IMPLEMENTING/VERIFYING/REVIEWING 可以在授权后沿合法回边进入 SPECIFYING；PLANNED 与 GATING 不能。BLOCKED 服从已持久化 recovery authority；REPRODUCING/FIXING 先完成 Finding lifecycle；CONVERGED 与 terminal states 使用 replacement commands。该 authority table 不改变 repairable Architecture blocker 的 `RECOVERY_POLICY`。

CREATED/CLASSIFIED 尚未进入 Architecture freeze；先沿既有正向 edge 到 SPECIFYING。PLANNED 不默认 recover 仅约束 repairable blocker table；不覆盖上面的 `CONTRACT_CHANGED` authority row。对 repairable blocker，`task recover` 会用模板覆盖 requirements、invariants、impact、observability 与 gate，并删除当前 Alignment/seal，因此只有 PLANNED → IMPLEMENTING 的 minimal、Test Plan 或 seal prerequisites 无法在该 state 合法补齐时才接受该破坏性 fallback。所有表中多步路径随后都必须执行上面的 `SPECIFYING → PLANNED → IMPLEMENTING` 完整回程。

`ARCHITECTURE_REQUIRED`、scope/evidence invalid、ownership empty/unresolved/ambiguous 与 scope drift 全部最终进入既有 IMPLEMENTING→SPECIFYING realignment。required 模式在首次 freeze 前缺少 `scope.modules` 时，`harness align freeze` 直接返回 `ARCHITECTURE_SCOPE_DECLARATION_REQUIRED` 且零写入；若已存在 v2 seal 后该 key 被删除，则按 sealed declared modules drift 返回 `CONTRACT_CHANGED`。它们不得把 `SPECIFYING` 写入 blocker 的 `recover_to` 或 `RECOVERY_POLICY`，因为 `BLOCKED → SPECIFYING` 不是合法 transition。

`CONTRACT_CHANGED` 保留现有 user-authority 语义。持久化 `harness gate` 从 GATING 经 BLOCKED 直接进入 terminal `ESCALATED`，当前任务不能 `resume` 或 realign；用户确认继续后，使用 `harness task new TASK-NNN` 创建替代任务。Preflight 检出时不改变 task state，只输出 `HALT_AND_WAIT`；确认后的续行严格使用上面的独立 authority table，不从 repairable table 推导“进入 SPECIFYING”。Missing/v1 seal 到 v2 的 migration 必须在进入实现和 Gate 前于 SPECIFYING 完成。

规则：

- Architecture 不定义新的用户确认阈值；
- 不自动接受 Decision；
- 不自动创建 canonical Finding；
- 不把 free-text reason 当作授权；
- accepted Decision 仍由现有 Decision artifact 与 seal selection 约束；
- 更新失败时旧 artifact 与旧 seal 必须保持字节不变。

---

## 16. CLI Contract

### 16.1 Mutation commands

```bash
harness architecture publish --file architecture.yaml
harness architecture scope add auth
harness architecture scope remove auth
```

共同规则：

- 在现有 telemetry lock 下执行；
- 使用 transaction atomic publication；
- 先完整校验 candidate，再写 canonical artifact；
- exact semantic retry 为 no-op，canonical bytes 不变；
- 所有 mutation 无论当前 mode 均仅允许 task state `SPECIFYING`；
- `IMPLEMENTING` 中返回 `ARCHITECTURE_REALIGNMENT_REQUIRED`，不写任何 artifact；
- scope mutation 只更新 `current-task.scope.modules`；
- 不自动运行 freeze，不自动创建 Decision。

`publish` 不扫描并生成模型，只发布操作者显式提供的 candidate。

### 16.2 Read-only commands

```bash
harness architecture validate
harness architecture resolve src/auth/service.py
harness architecture check
harness architecture summary
```

- `validate`：校验 canonical artifact、evidence refs、patterns 与可枚举冲突；
- `resolve`：解析一个显式 path；
- `check`：比较当前 frozen scope 与 task-attributable diff；
- `summary`：输出与 Context 相同的 bounded projection；
- read-only commands 不写 task、Gate、Finding、Context cache、telemetry iteration 或 seal；
- text/JSON 输出不得包含 evidence body 或源码 body。

---

## 17. Context Integration（P1）

### 17.1 Authoritative input

required Q2/Q3 Context source 加载一个已校验 Architecture object，并将其与现有 task、Alignment seal、workspace 和 Gate assessment 一起传入 builder。`AuthoritativeContext.architecture` 为 `dict | None`：required artifact 缺失时保留 `None`，由共享 assessment 投影 `ARCHITECTURE_REQUIRED`；present malformed Architecture/alignment/plan source 固定映射为 `CONTEXT_SCHEMA_INVALID`，禁止 fallback。Gate 顶层捕获的 `InvalidHarnessState` 仍使用 `INVALID_HARNESS_STATE`，两者不得混名。

FAST/Q1 与 mode off 可以经过静态 import 和现有 gate-policy validation，但不读取 `architecture.yaml`/Architecture schema、不执行 Architecture resolver 或 Git adapter，也不在 references 中登记 Architecture path。

### 17.2 Control Core projection

```yaml
architecture:
  status: current
  fingerprint: sha256:...
  declared_modules: [auth, session]
  relevant_modules:
    - id: auth
      name: Authentication
      responsibility: Authenticate users and authorize requests.
      depends_on: [session]
    - id: session
      name: Session
      responsibility: Manage session lifecycle.
      depends_on: []
```

Missing required artifact 的 projection 固定为：

```yaml
architecture:
  status: missing
  fingerprint: null
  declared_modules: []
  relevant_modules: []
  blockers: [ARCHITECTURE_REQUIRED]
```

Current projection 规则：

- 包含 declared modules；
- 包含它们的一层 direct dependencies；
- 不递归展开 dependency graph；
- 不注入无关 module；
- 不读取或复制 evidence 文件正文；
- 不在 Context build 中展开 ownership glob 或扫描 repository；
- 不把 projection 写成新的 canonical artifact；
- 不把 Context summary 当作 Gate 输入。

### 17.3 Freshness 与 integrity

Architecture artifact digest、Alignment v2 seal digest、sealed `architecture_mode` 和 task declared module IDs 加入现有 Context version input。Module IDs 是 domain identifiers，不是 repository paths：它们不得进入 `_declared_paths()`，不得接受 path existence 或 symlink 检查。任一 version input 变化使旧 Context projection stale。

接入必须同步更新：

- `AuthoritativeContext`；
- `ControlCore` 与 Context schema；
- `FileContextSource` canonical source list；
- read scope 与 `source_access` audit；
- dependency closure allowlist；
- freshness root/version inputs；
- lifecycle、restart、malformed-source tests。

不新增 persistent cache、manifest authority 或后台索引。

---

## 18. Failure Atomicity 与 Diagnosability

Mutation failure 必须满足：

- candidate schema error：零写入；
- evidence/path validation error：零写入；
- lock acquisition failure：零写入；
- atomic publication failure：保留旧 canonical bytes；
- seal publication failure：旧 seal bytes 保持不变；若 realignment 已开始，则 `alignment.yaml.freeze.frozen: false` 且 seal 已删除；Architecture artifact 本身没有 `unfrozen` 字段；
- exact retry：零 publication。

Gate diagnostics 必须稳定包含：

- blocker code；
- canonical path（适用时）；
- declared/actual/unexpected module IDs（适用时）；
- matched ownership rule ID 或 tied ownership rule IDs（适用时）；
- typed recovery target。

Diagnostics 不包含源码、evidence body、LLM explanation 或不稳定 traceback。Invalid Harness State 保留底层稳定错误 code，并由 CLI 映射为既有 invalid-state exit contract。

---

## 19. 分阶段交付

### P0 — Model、Resolver、Freeze、Gate

必须实现：

1. Architecture schema resource、loader、validator、package inclusion，以及 `gate.schema.json`/template mode extension；
2. semantic fingerprint；
3. restricted pattern parser 与 pure resolver；
4. typed changed-path adapter；
5. publish/validate/resolve/check/scope CLI；
6. `current-task.scope.modules` schema；
7. Alignment seal schema `oneOf` v1/v2、`harness align freeze` v2 writer、off phase-entry 的显式 legacy-v1-only bootstrap，以及 required/Gate/Context 的 read-only validation；
8. `task new`/`task recover` 的 trusted mode restoration；
9. Q2/Q3 required Gate blocker category、stable source identity、`RECOVERY_POLICY`、state-aware preflight guidance 与 existing realignment；
10. P0 dependency closure 注册：pure Architecture domain module 加入 `dependency_closure.ALLOWED`，不得加入 `ADAPTERS`；
11. lock、atomicity、no-op retry；
12. unit、integration、CLI、package tests。

P0 不实现 Context projection 或 benchmark claim。

### P1 — Context Projection

必须实现：

1. authoritative source integration；
2. declared + one-hop dependency projection；
3. Context schema与 body-bounded renderer；
4. freshness/version scope；
5. `harness architecture summary` bounded projection；
6. source-access、dependency-closure、restart 与 lifecycle tests；
7. request-local assessment reuse。

P1 不新增 cache 或 repository scan。

### P2 — Evaluation

必须实现人工标注 corpus 与重复实验：

1. normal ownership；
2. unexpected module；
3. unresolved new path；
4. equal-score ambiguity；
5. shared ownership；
6. support path；
7. rename 规范化 delete + add 后跨 modules；
8. adopted vs unrelated protected user paths；
9. Context recovery；
10. false-positive control。

每个独立实验的 baseline 与 adaptive 各至少运行三次。效率结论必须服从 correctness precedence。

---

## 20. Verification Matrix

### 20.1 Schema 与 model

- valid minimal model；
- duplicate/invalid module ID；
- missing responsibility/evidence；
- unknown/self dependency；
- allowed dependency cycle；
- invalid evidence type/path；
- production/shared/support cardinality；
- `allow_empty` / `empty_reason` 合法与非法组合；
- schema/module/ownership/context hard bounds。

### 20.2 Resolver

- exact path；
- single-segment wildcard；
- trailing recursive wildcard；
- longest literal match；
- total-segment tie-break；
- equal-score ambiguity；
- explicit shared owners；
- support no-module result；
- absolute、`..`、backslash、unsupported glob rejection；
- host filesystem case behavior不影响结果。

### 20.3 Changed paths

- fixed `--name-status --no-renames -z` parser；
- add、modify、delete、untracked typed records；
- rename → delete + add，copy → destination add；
- committed/staged/worktree/untracked 四层 merge；
- staged-only、worktree-only 与同 path 多 kind counterexamples；
- `git ls-files -z`、`git ls-files --deleted -z` 与 untracked 组成的 canonical path index；
- 每条 query 固定 `_PRODUCT_EXCLUDE`，docs/tests/support inclusion；
- `preexisting_user_paths - owned_paths` exclusion；
- unrelated protected user path exclusion与 adopted user path inclusion；
- stable sorted diagnostics。

### 20.4 Freeze 与 Gate

- FAST/Q1 对损坏 artifact 零读取；
- mode off 对损坏 artifact 零读取；
- required missing artifact blocker；
- present malformed artifact invalid state；
- off phase-entry missing seal 仅补 legacy v1，read-only Gate 不写 seal；
- legacy v1 seal off-mode compatibility；
- required phase-entry/Gate missing 或 v1 seal `CONTRACT_CHANGED` 且零写入；
- v2 seal 只由显式 align freeze 发布；
- sealed mode downgrade rejection before Architecture artifact read；
- fingerprint drift 与 declared module drift；
- required 模式缺失 `scope.modules` key 被拒绝，显式 `modules: []` 才表示 support-only；
- current-task delete caused ownership-empty；unrelated empty rule 不阻断；
- unresolved、ambiguous、unexpected module；
- every Architecture blocker has `implementation` category and stable subject-bearing `source`；
- blocker fingerprint distinguishes different paths/modules/rules；
- `BLOCKED → IMPLEMENTING → SPECIFYING --reason SCOPE_DRIFT` recovery；
- no automatic scope/Decision/Finding mutation；
- Architecture-local short-circuit preserves independent Gate blockers；
- Gate/preflight/check assessment parity；
- one Gate assessment per request。

### 20.5 Mutation

- unsupported state rejection before artifact read；
- publish candidate validation；
- lock serialization；
- atomic rollback；
- exact semantic retry byte stability；
- implementation-state realignment refusal；
- task-new/task-recover persistence of repository-level Architecture artifact；
- task replacement 从 trusted v2 seal 恢复 mode，或在无 v2 时保留当前 validated mode；
- off phase-entry 只可 bootstrap missing legacy v1 seal；required phase-entry、Gate 与 Context 不 bootstrap，且任何 bootstrap 不得生成 v2。

### 20.6 Context

- declared + one-hop projection；
- dependency cycle boundedness；
- no unrelated module；
- no evidence body；
- no glob expansion/repository scan；
- missing required source blocker projection；
- malformed present source fail-closed；
- architecture/scope/seal/mode freshness invalidation；
- module IDs enter version input but not `_declared_paths()`；
- FAST/Q1 and off-mode dependency closure isolation。

---

## 21. Benchmark 与可解释限制（P2）

P2 分成两个实验，不把不同 treatment 合并为一条 baseline/adaptive 结论。

### 21.1 Drift Detection Experiment

- baseline：同一标注 fixture、task scope、Git records 与现有非 Architecture Gate checks，`gate.architecture.mode: off`；
- adaptive：相同输入，唯一 treatment 是启用 required Architecture model/resolver/Gate；
- 比较 Drift recall、Diagnostic precision 与 False-positive rate；
- Missed-impact proxy 单独报告为 **declaration quality**，不计入 Gate detector correctness。

### 21.2 Context Recovery Experiment

- baseline：相同 required Architecture assessment、task facts 和 token budget，但 Control Core 省略 Architecture projection；
- adaptive：唯一 treatment 是加入 approved declared + one-hop Architecture projection；
- 比较 Context factual recovery、token 与 tool-call cost；
- 该 ablation 是 benchmark fixture 行为，不新增 production mode。

两个实验的 baseline/adaptive 各至少运行三次。

### 21.3 Metrics

指标与固定公式：

| Metric | Formula |
|---|---|
| Drift recall | correctly blocked drift cases / all labeled drift cases |
| Diagnostic precision | correct unresolved-or-ambiguous diagnostics / all emitted unresolved-or-ambiguous diagnostics；无 emitted diagnostics 时记 `not_applicable` |
| False-positive rate | incorrectly blocked clean cases / all labeled clean cases |
| Missed-impact proxy | expected modules absent from declared modules / all expected modules |
| Context factual recovery | exact-match projected `(id, responsibility, depends_on)` records / all expected projected records |
| Token/tool cost | 现有 benchmark 的 run-level token 与 tool-call 统计；不参与 correctness 判定 |

所有分子、分母与 `not_applicable` case count 必须随报告输出；不得用缺失分母的百分比。

评估规则：

- corpus 必须人工标注 expected modules 与 expected diagnostics；
- correctness 下降时 efficiency 结果无效；
- fixture benchmark 不证明外部 Agent 泛化；
- Context 文本出现 module 信息不证明 Agent 已理解；
- token 降低只报告实验样本，不写成 Gate 保证；
- benchmark 不修改 canonical task truth。

---

## 22. Compatibility 与 Migration

### Existing repository

- 缺少 `gate.architecture` 配置：off；
- 缺少 Architecture artifact：off 模式正常运行；
- 旧 task/schema 在 off 模式允许缺少 modules 字段，且不把缺失归一化为已声明 scope；
- required 模式必须显式声明 `scope.modules`；只有显式空列表表示 support-only；
- legacy v1 Alignment seal 在 off 模式继续有效；
- 切换 required 前必须显式 publish model、声明 modules、执行 realignment 并生成 v2 seal。

### New repository

`harness init` 不自动推断 Architecture model。Operator 可保持 off，或在 SPECIFYING 中显式 publish model 并启用 required。启用 required 是明确 policy change，不由风险分类隐式写入。

### Downgrade

`architecture_mode` 是 Alignment seal v2 字段。直接把 `gate.architecture.mode` 从 required 改为 off 会在读取 Architecture artifact 前产生 `CONTRACT_CHANGED` 并终止当前任务，不能让 blocker 静默消失。合法 policy downgrade 必须先取得现有用户 Decision，再从 IMPLEMENTING 使用 `harness transition SPECIFYING --reason NEW_REQUIRED_DECISION`。

该 IMPLEMENTING → SPECIFYING 会删除当前 `alignment-freeze.yaml` 并把 Alignment 置为 unfrozen；`architecture.yaml` 保留。更新 policy 后，`harness align freeze` 发布新的 v2 seal。不得为了“保留历史”跳过删除，否则 freeze 会返回 `ALIGNMENT_ALREADY_FROZEN`。Harness 不承诺当前 seal 自动进入 history；只有既有 task replacement/archive 流程产生历史副本。Downgrade 不证明 Architecture 风险消失。

---

## 23. Stable Invariants

1. Canonical YAML 是 Architecture 与 task scope 的唯一事实来源。
2. Architecture 与 task modules 共享现有 Alignment freeze authority。
3. FAST/Q1 和 mode off 可读取 gate policy，但在 Architecture artifact/schema read、resolver 与 Architecture Git adapter 前返回。
4. Resolver 对相同 artifact/path 确定且平台无关。
5. Tie 永远显式 ambiguous，不静默选择。
6. Shared ownership 永远显式列出全部 owners。
7. Scope expansion 永远不自动写入、不自动接受 Decision。
8. Gate 永远不自动创建 Finding。
9. Context projection 永远不是新权威，也不扫描仓库。
10. Mutation 使用现有 lock 与 atomic publication。
11. Missing required artifact 是 blocker；malformed present artifact 是 invalid state。
12. Architecture Gate 只证明声明 module scope 与 attributable changed paths 的一致性。

---

## 24. Acceptance Criteria

### P0

- [ ] `.harness/architecture.yaml` schema、loader、validator 已版本化并打包；
- [ ] module、dependency、evidence、ownership 与 hard bounds 语义完整校验；
- [ ] restricted pattern grammar 与 deterministic score 有纯函数测试；
- [ ] unresolved 与 ambiguity 不被静默忽略；
- [ ] production/shared/support、support-only empty scope 与 ownership-empty 行为固定；
- [ ] `current-task.scope.modules` 已进入 schema；
- [ ] Architecture mode、fingerprint 与 declared modules 进入 Alignment seal v2；
- [ ] Q2/Q3 required Gate 使用 task-attributable changed-path records；
- [ ] typed Git adapter 使用 `--no-renames`，保留 docs/tests，并按 adopted ownership 计算 attributable records；
- [ ] 设计不虚构独立 File Scope Gate；
- [ ] scope expansion 复用 realignment 与 Decision；
- [ ] FAST/Q1、off、legacy compatibility tests 通过；
- [ ] mutation lock、atomicity、retry tests 通过；
- [ ] package resource 与 CLI tests 通过。

### P1

- [ ] Architecture 进入 AuthoritativeContext；
- [ ] Control Core 仅投影 declared + one-hop dependency；
- [ ] Context build 不读取 evidence body、不展开 glob、不扫描 repository；
- [ ] freshness version input 覆盖 artifact、seal、mode 与 declared module IDs，module IDs 不进入 `_declared_paths()`；
- [ ] dependency closure 与 lifecycle tests 通过；
- [ ] request-local assessment 复用已验证。

### P2

- [ ] 标注 corpus 覆盖 normal、drift、unknown、ambiguous、shared、support、rename、protected-path 与 Context recovery；
- [ ] Drift Detection 与 Context Recovery 两个实验各自的 baseline/adaptive 至少三次；
- [ ] Missed-impact proxy 只报告 declaration quality，不并入 detector correctness；
- [ ] correctness precedence 生效；
- [ ] false-positive 与 missed-impact proxy 有明确分母；
- [ ] token/tool cost 不被表述为 Gate truth。

---

## 25. Definition of Done

v0.3.0 完成要求：

```text
Validated Architecture Model
        ↓
Frozen Architecture Fingerprint + Declared Modules
        ↓
Task-attributable Changed Paths
        ↓
Deterministic Ownership Resolution
        ↓
Actual Modules vs Declared Modules
        ↓
Typed Blockers / Existing Realignment
        ↓
Evidence + Review + harness gate PASS
```

最终原则：

> Architecture Scope 必须由 canonical declarations 与代码改动事实共同验证；Harness 不得把 Agent 推断包装成 Architecture truth。

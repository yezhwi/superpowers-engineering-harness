# Superpowers Engineering Harness v0.2.7 正式 Code Review

| 项 | 内容 |
|---|---|
| 审查日期 | 2026-09-04 |
| 固定点 | `8c536406`（v0.1 引导提交：仅 `docs/engineering-harness-v0.1.md` + `package.json`） |
| 审查对象 | HEAD `8763c6489f823776660c20b3a586da073028f164`（`pyproject.toml` 版本 **0.2.7**） |
| Diff | `git diff 8c536406...HEAD` — 210 个提交、242 个文件、+34299 / −3 |
| 范围 | `src/harness`、schemas、Skills、CLI 契约、相关 tests |
| 非范围 | 工作区未跟踪的历史文档 |
| 规格来源 | `docs/engineering-harness-v0.1.md`（铁律仍有效）；后续已提交 spec 覆盖更新。现行合同：`docs/Superpowers-Engineering-Harness-v0.2.7-实施规格.md`、`docs/architecture.md`、`docs/superpowers/specs/2026-09-04-control-plane-integrity-repair-design.md`、`docs/superpowers/specs/2026-09-02-v027-decision-interface-design.md`、CHANGELOG、`SKILL.md` |
| 结论 | **Request Changes** |

相对 `8c536406` 的空包，HEAD 已经有完整状态机、证据新鲜度、Finding 生命周期、FAST/STANDARD/STRICT、DIAG 原子发布、ownership、双轴 Gate、Decision / Interface、`resume-review`。这些是真实能力。

但 v0.1 铁律「没有 Quality Gate PASS，不允许进入 DONE / CONVERGED」在 CLI 上仍可被 `harness transition CONVERGED` 绕过；Test Plan 覆盖可自声明；证据写路径可逃出 `.harness/evidence`。威胁模型是 **agent 会抄近路**。这几条在合并前必须修。

正确性轴 **7 bugs**。规格轴：缺/残 5，实现错 4，无明显 creep。标准轴：无文档化标准硬违规；smell 均为判断。

严重级别：

| 标签 | 含义 |
|---|---|
| `[blocking]` | 必须修 |
| `[important]` | 应当修，不同意需讨论 |
| `[nit]` | 非阻塞 |
| `[suggestion]` | 可考虑的替代做法 |

审查沿两条独立轴进行，不跨轴排序：

- **Standards** — 是否符合仓库文档化编码标准 + Fowler smell baseline
- **Spec** — 是否忠实实现现行规格（后写 committed spec 覆盖先写的）

---

## Strengths

- **DIAG Gate 已按当前 Task scope 重算。** `diagnosability.gate_blockers` 用 `project_task_scope` 对比记录里的 `review_scope.files`，ownership 变化会使 DIAG 证明过期。
- **读侧证据引用收口。** `paths.evidence_path` 拒绝跳出 `evidence/*.json`；Finding 闭合走同一解析器。
- **Review 发布走 staging + 回滚。** complexity / diagnosability / interface 走 `transaction.publish`。
- **质量轴和发布轴已经拆开。** `assess_gate` 同时写 `quality` 和 `release_readiness`；`harness gate preflight` 只有 READY 才打印 `READY: yes`。
- **Finding 恢复入口存在。** `REVIEWING` 出口必须走 `review outcome`；`REPRODUCING → REVIEWING` 必须走 `finding resume-review`。
- **YAML 全是 `safe_load`，无 pickle/eval，无可变默认参数。** 依赖面仍只有 jsonschema + PyYAML。
- **风险档位配对在 Gate 入口 fail-closed。** `Q1↔FAST / Q2↔STANDARD / Q3↔STRICT` 不一致会 `RISK_PROFILE_INVALID`。
- **`harness gate` 的 stdout 契约本身是对的：** `DECISION: CONVERGED|CONTINUE|ESCALATED`，这三条都返回 0。

---

## Required Changes

### 1. `[blocking]` `harness transition CONVERGED` 不要求 Gate PASS

v0.1 LAW 1 / 收敛规则：`Gate PASS → CONVERGED`。`state_machine` 允许 `GATING → CONVERGED`。`cmd_transition` 对 `CONVERGED → DONE` 会跑 Gate，对 `REVIEWING` / `BLOCKED` 有专用拒绝，**唯独 `GATING → CONVERGED` 只过合法表然后写状态**：

```python
# src/harness/controlplane.py:334-342
    try:
        state_machine.require_legal(current, target)
    except state_machine.InvalidTransition as exc:
        print(exc)
        return 1
    task["state"] = target
    save_task(harness_dir, task)
```

`cli.py` 把 `harness transition CONVERGED` 派到这里。真正要求 `status == "PASS"` 的只有 `_cmd_gate_convergence`。没有测试断言这条边必须拒绝。`skills/convergence/SKILL.md` 仍写「Gate PASS → transition CONVERGED」。根 `SKILL.md` 还写每次状态变化走 `harness transition`。

`harness_status` 只在 `DONE` 时校验 Gate PASS，不拦 `CONVERGED`。

同类：`GATING → BLOCKED` 也可被空 blockers 的 `transition` 打出，污染 `resume`。

**建议：** 从通用 `transition` 拒绝 `GATING → CONVERGED` 和 `GATING → BLOCKED`（对照已有的 `RESUME_REQUIRED` / `REVIEW_OUTCOME_REQUIRED`）。这两条边只允许 `cmd_gate` 写。

---

### 2. `[blocking]` Test Plan 覆盖是自声明字段

`validate_test_coverage.covered()` 只看「新鲜记录的 `covered_tests` 里有没有这个 node id」，不看 evidence `type`、不看 pytest selector、不看 stdout：

```python
# src/harness/test_plan.py:145-149
    def covered(node_id: str) -> bool:
        return any(
            node_id in record.get("covered_tests", []) and evidence_is_fresh(record)
            for record in evidence_records
        )
```

`collect_evidence._collect` 把 `--covered-test` 写进每一种 evidence type。`pytest_selectors` 只在解析出非空 selector 时才拒绝；对非 pytest 返回 `None`，对无 `.py`/`::` 的 `pytest` 返回 `()`，两者都跳过检查。

可达捷径：

```bash
harness evidence --type lint --command true --covered-test tests/foo.py::test_bar
```

`tests/test_test_plan_lifecycle.py` 把 `build.json` 改成 `integration_test`、填上 `covered_tests`，就能 Gate PASS 并 `DONE`。这把洞锁进了通关路径。

**建议：** 自动化 binding 只接受 `unit_test` / `integration_test` / `contract_test`。pytest 必须有非空 selector 且覆盖每个声称的 node。`build` / `lint` / `custom` 禁止携带 `covered_tests`。空 selector 不能当证明。

---

### 3. `[blocking]` 证据写路径可逃出 `.harness/evidence`

`evidence_filename` 把原始 `finding_id` 拼进文件名；`main` 直接 `out_dir / filename` 再 `write_text`，没有 `resolve()` 父目录检查，也不走 `evidence_path`：

```python
# src/harness/collect_evidence.py:97
    return f"{finding_id}-{phase}-{stem}.json"
```

`--finding ../outside --phase red` 写出 `.harness/outside-red-….json`；更深的 `..` 离开 evidence 目录。`--finding /tmp/x` 在 pathlib 下会变成绝对路径写入。

同一 helper 被 attach 使用：`cmd_evidence_attach`（`controlplane.py:583-584`）。CLI `--type` 无枚举约束（`cli.py:82`），`--attach --type ../../tmp/pwned` 可经 `atomic_write` 的 `mkdir`+replace 逃逸。

`transaction.stage` 已经拒绝 `..` 和绝对路径。读侧 `paths.evidence_path` 是 fail-closed 的。写侧都没用它们。

**建议：** ID 用 `^FND-[0-9]+$` / `^CPLX-` / `^DIAG-`；`evidence_type` 限制在 `VALID_TYPES`；`Path(name).name == name`；`out_file.resolve().parent` 必须仍是 `evidence/`。

---

### 4. `[blocking]` 受保护路径会从 owned/contract scope 里减掉

2026-09-04 修复设计：`project_task_scope` 对 owned/contract **不做** protected 减法。v0.2.7 §9 只写并集。实现是并集后再减全部 `protected_user_paths`：

```python
# src/harness/workspace.py:128-142
    included = set(scope.get("owned_paths") or ())
    included.update(impact.get("contracts") or ())
    ...
    return tuple(sorted(included - set(scope.get("protected_user_paths") or ())))
```

`ignore-user-path` 可把任意非 owned 路径追加到 protected（`controlplane.py:1467-1468`），无 dirty-file 检查。因此 `add-contract src/api.py` 再 `ignore-user-path src/api.py` 会把 contract 从 complexity / diagnosability / `impact scope` 里拿掉。`current-task.yaml` 也可手改出 owned ∩ protected。

v0.2.7 §10 要求 contract path 不能被 ownership 意外排除。

**建议：** protected 只从非 owned、非 contract、非 inspected 成员里减。`ignore-user-path` 拒绝 contract/owned 路径。owned 赢。

---

### 5. `[blocking]` Complexity / Interface Gate 不重算 review scope

09-04：「Gate review blockers derive current project task scope and compare it with recorded review scope; post-review ownership or impact changes invalidate required review proof。」DIAG 做了（`diagnosability.py:274-281`）。

Complexity Gate 只对 `complexity-review.json` 做 schema + `validate_evidence`（HEAD / fingerprint / exit_code），**不**重算 `project_task_scope` / git `review_scope`，也不对比 `review_scope.files`（`quality_gate.py:798-826`）。workspace fingerprint 排除 `.harness/**`，所以 review 之后 `impact add-change` / `adopt-path` 不会让证明过期。

写入口：若 `task.scope` 存在（模板默认有），`cmd_review_complexity` 用 `project_task_scope` 覆盖 git files（`controlplane.py:505-508`）；声称的 `review_scope` 可选（`:509-513`），省略则可以持久化空文件列表。`tests/test_cli_complexity.py` 接受 `files: []` 而工作区有业务改动。`validate_complexity_checks` 在 `checks is None` 时直接返回；`harness review complexity` 不要求状态 `REVIEWING`。

Interface review 忽略 `base_ref`（`controlplane.py:451-464`；`write_review` 不算 git scope）。Gate（`quality_gate.py:544-563`）只检查新鲜 `type==review` 且无 `fail`，不要求 `review.contracts` 覆盖当前外部接口。

**建议：** Gate 重算期望 files/contracts，与记录逐字段相等，否则 `*_REVIEW_STALE`。拒绝业务文件已变但 complexity scope 为空。Interface review 像 DIAG 一样穿 `--base`。六个 complexity checks 必填。complexity review 限定 `REVIEWING`。

---

### 6. `[blocking]` Interface Finding 生命周期与 schema 打架

09-04：「Interface Finding schema must accept canonical Finding lifecycle states so a Finding can move from `PROPOSED` through existing closure states。」

`interface-finding.schema.json` 状态枚举有了，但 `additionalProperties: false`，且没有 `regression_test` / `evidence` / `confirmed_at`。Gate 对非 DIAG 的 `CONFIRMED`/`FIXED`/`VERIFIED` 仍要这些证明（`quality_gate.py:364-371`）。

结果：CONFIRMED 之后一写证明，schema 校验失败；不写证明，Gate 不过。这是 schema 错，不是生命周期完成。

**建议：** 与 adversarial / diagnosability finding schema 对齐，允许闭合字段；或 Gate 对 `category: interface` 走独立闭合证明，二者选一并测通。

---

## Important Suggestions

### 7. `[important]` 两条 Gate 入口、两套退出码

| 入口 | PASS | BLOCKED/CONTINUE | 非法状态 |
|---|---|---|---|
| `harness gate` → `cmd_gate` | 0 + `DECISION: CONVERGED` | 0 + `CONTINUE`/`ESCALATED` | **1** |
| `python scripts/quality_gate.py` → `quality_gate.main` | 0 + `QUALITY GATE: PASS`（**不迁状态**） | **1** | **2** |

`skills/quality-gate/SKILL.md` 仍写「In-harness-repo equivalent: `python scripts/quality_gate.py`」，frontmatter 还写「maps its exit code to state transitions」。根 `SKILL.md:178`、`skills/convergence/SKILL.md` 仍把脚本 PASS 接到 `transition CONVERGED`。

脚本 PASS 再 `harness transition CONVERGED` 就是 Issue 1 的现成捷径。`_cmd_gate_convergence` 把 `InvalidHarnessState` 映射成 1（`controlplane.py:787-791`），和 CLI 文档的 2、以及 `CONVERGED → DONE` 路径不一致。非法状态与「当前不是 GATING」无法区分。

**建议：** `quality_gate.main` 委托 `cmd_gate`，或不再作为产品入口。Skill 删除脚本等价声明。非法 harness 统一 exit 2。只有 `harness gate` + `DECISION: CONVERGED` 可以进入 `CONVERGED`。

---

### 8. `[important]` `resume-review` 加载 Finding 不 fail-closed

`cmd_finding_resume_review` 是唯一合法的 `REPRODUCING → REVIEWING` 路径（`cmd_transition` 在 237–252 拦截）。它用裸 `yaml.safe_load` 读每个 `findings/*.yaml`（`controlplane.py:902-905`），不用 `_findings()`（725–739，YAMLError / 非 mapping → `FINDING_STATE_INVALID`）。

缺少 `status`/`id` 的 mapping 不会进入 `blocking` 列表，拦不住恢复。列表/标量 YAML 会 `AttributeError` traceback，而不是 exit 2。`cmd_finding_transition`（941–945）同样未校验 glob。

09-04：Finding 加载把 YAML 解析错误和非 mapping 打成 `InvalidHarnessState`。

**建议：** 走 `_findings()` 或 `quality_gate.load_findings`；任何不可读或 schema 非法的 Finding 必须 exit 2，且不得 resume。

---

### 9. `[important]` 替换 Task 的 Git identity 不完整；`base_ref` 写成会动的 `HEAD`

`cmd_task_classify` 冻结 `base_ref` / `base_commit` / `head_at_start` / `head`（`controlplane.py:1080-1084`）。`initialize_task_git`（`task new` / `recover`）只写 `base_commit` + `head`（`controlplane.py:1203-1205`）。09-04 / v0.2.7 §6 要求三字段一起冻结。classify 会在 review/gate 消费前覆盖 `git`，所以这不是运行时崩溃，但是身份合同缺口。

classify 还把 `base_ref` 设成 `"HEAD"`。v0.2.7 §5 例子是 `origin/main`。`HEAD` 是会动的名字，不是冻结的分支身份。

**建议：** `initialize_task_git` 写与 classify 相同的四个字段；`base_ref` 冻结为真实 ref（如 `origin/main`），不要写 `"HEAD"`。

---

### 10. `[important]` `impact scope` 公式不完整；status 用缓存投影

v0.2.7 §9：`effective_scope = owned_paths + observability.inspected_paths + declared direct_dependencies + applicable contract paths`。`harness impact scope` 调用 `project_task_scope(task, impact)` 时不传 `inspected_paths`（`controlplane.py:1448`）。`task.scope is None` 时 complexity 仍走 `workspace.review_scope`，会并入全部 dirty path（`workspace.py:164-166`）。规格要求的 `test_review_scope*` 不存在。

09-04：「Gate/status recompute canonical Findings and assessment instead of treating cached task projection as authority。」`harness_status._render` 打印 `current-task.yaml` 里的 `findings`/`gate`（`harness_status.py:127-157`）。现场 `assess_gate` / `load_findings` 只在 `DONE` 时跑。

**建议：** `impact scope` 传入 observability inspected paths。status 对非 DONE 也投影 live Findings / Gate assessment（只读，不 `write_back`）。

---

### 11. `[important]` Evidence attach 没有 task binding；错误码折叠

09-04：「Evidence attach validates external result against evidence schema plus current task binding, exit/provenance coherence, and freshness before persistence。」`cmd_evidence_attach` 查字段/schema/新鲜度，从不碰 `task.id`（`controlplane.py:524-584`）。所有 schema/freshness/IO 失败都折叠成 `EVIDENCE_ATTACH_INCOMPLETE`。

v0.2.7 §24/§26 的 structured `input` / `accepted` / `candidates` 未实现；读侧是 `evidence_path` 的 `EVIDENCE_REFERENCE_INVALID; candidates: ...`。

**建议：** attach 绑定当前 `task.id`；按失败原因区分错误码；引用解析走同一 resolver。

---

## Standards

仓库没有 `CODING_STANDARDS.md` / `CONTRIBUTING.md`。Ruff（`pyproject.toml`）已覆盖的问题跳过。YAML 全程 `safe_load`。

**(a) 文档化标准硬违规：无。**

**(b) Smell baseline（均为判断；仓库无覆盖规则）：**

### Divergent Change

`controlplane.py`（约 1512 行）同时承担 transition、review、evidence、gate、finding、task、impact、benchmark、telemetry。`quality_gate._evaluate_gate`（`quality_gate.py:254`–`:888`）混 FAST、finding 证明、DIAG、decision、interface、requirement、invariant、test plan、complexity。

v0.2.7 非目标写明「不重构整个 `controlplane.py`」，09-04 写明「Do not split modules」。因此这是已知债务，不是本版本必须拆文件的违规。后续版本若再往这两个函数堆政策，会继续放大。

### Duplicated Code

Finding 加载四套、fail-closed 强度不一：

- `quality_gate.load_findings`（`:131`）— schema + mapping
- `controlplane._findings`（`:725`）— 仅 mapping
- `diagnosability.gate_blockers`（`:263`）/ `write_review`（`:367`）— 几乎不校验
- `interface_review._load_existing_findings`（`:18`）

`decision.py` 与 `interface_contract.py` 的 `_task_id` / `load_*` / `_write` / `_next_id` 同形。Q→profile 映射在 `risk.PROFILES`、`quality_gate.py:281`、`benchmark.py:9` 各写一份。`git_head` 包装：`collect_evidence.py:62`、`quality_gate.py:91` vs `workspace.git_head`。`cmd_task_new` 与 `cmd_task_recover` 的归档/重置几乎复制。

### Repeated Switches

FAST vs STANDARD/STRICT 在 `cmd_transition`（`controlplane.py:226`–`:320`）、`quality_gate.py:294`、`budget.py:35`、`cmd_impact:1473` 重复。应收口到 `risk.PROFILES` / 一个 policy 对象。

### Speculative Generality

`cmd_review_interface`（`controlplane.py:451`）接收 CLI `--base` 却不用。

### Message Chains

```python
# src/harness/quality_gate.py:911-917
release = _load_yaml(harness_dir / "gate.yaml").get("gate", {}).get("release", {})
(_load_yaml(harness_dir / "current-task.yaml").get("authorizations") or {})
    .get("full_suite", {})
    .get("granted")
```

同类：`fast_verification_policy`（`:149`–`:153`）。

### Data Clump / Primitive Obsession

`(current_head, current_workspace, expected_success)` 成对穿过 validator / DIAG / gate。task / finding / risk 仍是无类型 `dict` 加 `"Q1"` / `"FAST"` 字符串。控制面硬编码 `Path(".harness")`，只有 `status` 认 `--harness-dir`。

### Middle Man

`cmd_gate` → `_cmd_gate_convergence`；`cmd_authorize_full_suite` → `cmd_authorize`；`cmd_evidence` 把参数再拼成 argv 调 `collect_evidence.main`。

### Mysterious Name

`_impact()`（`controlplane.py:1412`）只是读 `impact.yaml`。`complexity._invalid` 用 `ValidationError` 抛领域消息。

### 过宽 `except Exception`（判断，但影响 fail-closed）

`controlplane.py` 约 20 处。最差是 `:244`（裸 `except Exception:`），把 `_findings` 的任意失败变成 `FINDING_STATE_INVALID`。同类：`203`、`272`、`364`、`460`、`686`、`1150`、`1274`。应收窄到 `InvalidHarnessState` / `WorkspaceError` / `YAMLError`。

`diagnosability.py:263` 把坏 YAML 收成 `DIAGNOSABILITY_REVIEW_STALE`。`write_back`（`quality_gate.py:955`）用未校验的 `yaml.safe_load`，不像 `load_task` / `_load_yaml`。

### `subprocess` `shell=True`

`collect_evidence.py:155-157` 跑原始操作员字符串。`_TrustedLocalCommand` 是类型标记，不是沙箱。本地操作员工具可接受；`command` 一旦非交互来源就是注入面。

没有可变默认参数、unsafe YAML、或 Refused Bequest。

---

## Spec

相对 **最新适用规格**（后写的 committed spec 覆盖先写的；v0.2+ 功能只要后续规格要过，就不算 creep）。

### (a) 规格有、实现缺或残

**Status 用缓存投影。** 09-04：「Gate/status recompute canonical Findings and assessment instead of treating cached task projection as authority。」实现见 Important #10。

**Gate 不因 ownership 变化作废 complexity/interface 证明。** 09-04：「post-review ownership or impact changes invalidate required review proof。」DIAG 对比了。Complexity / interface 没有。见 Required #5。

**共享 Gate API / quality CONTINUE。** v0.2.7 §33/§36/§37：`evaluate_gate_requirements(...)`，含 `ready_for_gating` / `missing_evidence` / `recommendations`；`quality.status: PASS | BLOCKED | CONTINUE`。实现是 `assess_gate` / `_evaluate_gate`，quality 只有 PASS/BLOCKED（`quality_gate.py:886-933`）。CONTINUE 只出现在 `DECISION:`（`controlplane.py:862`）。Preflight 的 `READY:` 把规格 §34 `ready_for_gating` 和修复设计「只有 release readiness READY 才 emit Ready」混在一起（`controlplane.py:706-707`）。

**Attach 没有 task binding。** 见 Important #11。

**替换 Task 的 Git 冻结不完整。** 见 Important #9。

**证据引用合同部分实现。** v0.2.7 §24：`resolve_evidence_reference(...)`。代码：`evidence_path`（`paths.py:10`）。§26 structured `input` / `accepted` / `candidates` 未实现。attach 不用 resolver。

**旧 DIAG 迁移。** v0.2.7 §47：无法推断类型则 `MIGRATION_REQUIRED`，「不得猜测 Finding 类型」。源码无 `MIGRATION_REQUIRED`。无 category 的 `requirement_violation` 被当成 adversarial（`quality_gate.py:122-127`）。`finding.schema.json` 仍 `oneOf` 全类型（与 §13 冲突）。

**CLI / Skill 契约滞后。** v0.2.7 §19/§27/§34：`finding resume-review`、`evidence run`/`attach`、`gate preflight`。`SKILL.md` 与 `skills/*/SKILL.md` 仍调度 `harness evidence --type`，几乎不提 resume-review / preflight / `impact scope`。legacy `evidence` 在 CLI 内部改写（`cli.py:33-41`）。

### (b) Scope creep

`src/harness` 里没有后列规格没要过的实质行为。Decision CLI、Interface Contract、`harness review interface`、ownership、双轴 Gate、evidence run/attach 都在 CHANGELOG 0.2.7 / 根 SKILL / 09-02 或 09-04 设计里。

08-30「拆 `controlplane.py`」已被 v0.2.7「不重构整个 `controlplane.py`」和 09-04「Do not split modules」取代。`paths.py` / `interface_*.py` / `decision.py` 是后续规格交付，不按实施规格「不为整洁提前拆模块」算 creep。

### (c) 看起来做了、行为不对

**Protected 减法。** 见 Required #4。引用 09-04：「`project_task_scope` computes effective owned scope without protected-path subtraction for owned/contract paths。」

**Interface Finding 无法闭合。** 见 Required #6。Interface 重复 proposal 映射到已有 ID 继续走（`interface_review.py:79-85`），DIAG 同类则 `DIAG_PROPOSAL_DUPLICATE` fail-closed（`diagnosability.py:383-389`）。

**`base_ref` 写成 `"HEAD"`。** 见 Important #9。引用 v0.2.7 §5 例子 `base_ref: origin/main`。

**Resume-review YAML。** 见 Important #8。引用 09-04：「Finding loading catches YAML parser errors and rejects non-mapping artifacts as `InvalidHarnessState`.」

**Review-outcome PASS vs CLOSED。** v0.2.7 §23：未闭合 Finding 时 `review outcome PASS` 必须拒绝。handler 不检查 CLOSED（`controlplane.py:416-438`），靠 Gate `FINDING_OPEN` 预检（含 `FIXED`，`quality_gate.py:45-51`）。报错面是 `GATE_PREFLIGHT_MISSING_EVIDENCE`，不是 Finding 未闭合。

---

## 与 v0.2.6 正式审查的关系

`docs/Superpowers-Engineering-Harness-v0.2.6-正式CodeReview报告.md` 的三条 blocking 在 0.2.7 **全部仍在**：

| v0.2.6 blocking | 0.2.7 状态 |
|---|---|
| `transition CONVERGED` 无 Gate | 仍在（Required #1） |
| Test Plan `covered_tests` 自声明 | 仍在；仅对带显式 selector 的 pytest 做了部分校验（Required #2） |
| `--finding` 写路径逃逸 | 仍在；attach `--type` 还扩大了写侧（Required #3） |

0.2.7 新增且必须修的：owned/contract 被 protected 吃掉、complexity/interface scope 不重算、Interface Finding 无法走完生命周期。

v0.2.6 的「可跳过 CLASSIFY」已修：`CREATED` 只能进 `CLASSIFIED`。DIAG 读侧 scope 信任问题已部分修（Gate 重算）。

---

## 裁决

**Request Changes。** 从 v0.1 空包到 0.2.7 的产品面已经立住；不能在「`transition CONVERGED` + 自声明 covered_tests + 写路径逃逸」仍可绕过铁律的情况下当生产控制面。

合并前优先：

1. 封 `GATING → CONVERGED|BLOCKED` 的通用 `transition`
2. Test Plan 只认测试类 evidence + 真实 selector
3. 证据写路径与 `evidence_path` / `transaction.stage` 同一套约束
4. `project_task_scope` 对 owned/contract 不做 protected 减法
5. Complexity / interface Gate 重算并对比 scope
6. Interface Finding schema 允许闭合字段，或 Gate 走独立闭合证明

然后处理双 Gate 入口、resume-review fail-closed、Git identity、`impact scope` / status 投影、attach task binding。

**轴汇总（不跨轴排序）：**

- 正确性 **7 bugs**，最严重是无 Gate 的 `CONVERGED`
- 规格轴最严重是 `project_task_scope` 减法 + Interface Finding 无法走完生命周期
- 标准轴无硬违规，最重 smell 是 `controlplane.py` / `_evaluate_gate` 的 Divergent Change（规格明确本版本不拆模块）

本次只读审查，未改生产代码。

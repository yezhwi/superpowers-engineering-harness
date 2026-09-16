# v0.2.8 契约—实现—测试映射

## 核对范围与证据等级

- 基线代码：`5540ca5`。映射文档刷新于 `be2e21b`。本轮补记 Product Done 测试包执行结果，不是仅审旧 HEAD `d6a2438`。
- 自 `d6a2438` 起已合入：`1772597` 版本对齐、`eafc69b` SRC-09 untracked Gate 读取、`a45d0fe` benchmark stdout、`d634990` POL-09、`5540ca5` Gate 错误域。
- 依据：[实施契约](./Superpowers-Engineering-Harness-v0.2.8-Implementation-Contract.md)、[59 项验收案例](./Superpowers-Engineering-Harness-v0.2.8-Contract-Acceptance-Cases.md)。
- 映射状态与执行证据分开：找到测试 ≠ 本轮跑过 ≠ 验收 PASS。
- 未运行全仓 `pytest`，不更新 `.harness`。
- `映射`：找到直接实现与对应测试；仍待正式执行/独立复核。
- `部分`：只有子场景或间接证据，不能据此关闭整项。
- `缺口`：未找到条款要求的机制或专属测试，不代表已复现运行时 bug。
- 全部 59 项均保持未签收。缺真实实验数据时 Experiment 为 INCONCLUSIVE，不能替代现场效率证明。

## 核对计划与进度

- [x] 读取契约、验收清单、实现入口与测试清单。
- [x] 为 59 项建立实现/测试入口，区分直接映射与未覆盖子场景。
- [x] 记录清单之外的契约缺口及后续顺序。
- [ ] 独立复核逐项断言和错误码；不是本轮已完成内容。
- [x] 在 `be2e21b` 运行 Product Done 相关测试包并记录结果（见 §执行记录）。
- [ ] 全仓 `pytest`；授权后另记。

下表文件简称：

| 简称 | 文件 |
|---|---|
| B | `tests/test_context_builder.py` |
| I | `tests/test_context_integrity.py` |
| S | `tests/test_context_selector.py` |
| C | `tests/test_context_cli.py` |
| E | `tests/test_context_expansion.py` |
| A | `tests/test_context_automatic.py` |
| R | `tests/test_context_remaining_triggers.py` |
| U | `tests/test_telemetry_usage.py` |

测试入口用 `简称::函数名` 表示，均需连同参数化值阅读。Context 实现位于 `src/harness/context/`。

静态检查结果：59 个唯一案例 ID 与冻结清单一致；31 项映射、25 项部分、0 项缺口、3 项已实现（MET-10/11/12，语义同映射，待独立复核）。这不是测试执行结果，也不是 Product Done。

## 1. Source manifest 与 freshness

| ID | 状态 | 实现 / 测试入口 | 未关闭内容 |
|---|---|---|---|
| SRC-01 | 部分 | `freshness.py`、`integrity.py`；I::test_derived_context_and_telemetry_do_not_self_stale；A::test_finding_auto_expansion_is_fresh_and_deduplicated | 补 CLI 连续 compact 的 hash 等值断言；自动事件写入后的稳定输入单独覆盖。 |
| SRC-02 | 部分 | `freshness.py::capture`；I::test_ci09_any_control_source_edit_stales_old_context | 当前参数含 task/requirements；逐项补 invariant、scope、authorization 修改后重生成的语义断言。 |
| SRC-03 | 部分 | `freshness.py::capture`；I::test_directory_membership_and_optional_presence_are_freshness_inputs | 现有测试为 evidence 新增；补 finding 新增/删除/reopen、decision accept/supersede 全路径。 |
| SRC-04 | 部分 | `freshness.py::ROOT_FILES`；I::test_ci09_any_control_source_edit_stales_old_context | gate/risk-boundaries/observability 有参数；config、interface、间接 Gate 读取集合仍须审计。 |
| SRC-05 | 部分 | `freshness.py::_declared_paths`；I::test_ci09_product_change_stales_old_context；I::test_explicitly_referenced_ignored_file_changes_stale_context | ignored 引用有 owned/requirement/finding/decision 参数；补 Context 专属 HEAD 变化测试。 |
| SRC-06 | 部分 | `freshness.py`；I::test_derived_context_and_telemetry_do_not_self_stale；I::test_temporary_artifact_write_does_not_stale_context | Context 忽略 telemetry/staging/history 有直接证据；product evidence 不受这些更新影响需联合断言。 |
| SRC-07 | 部分 | `freshness.py`；`tests/test_evidence_freshness_and_path_binding.py::test_requirement_verify_does_not_stale_product_evidence` | 补同一次 requirement verify 同时断言旧 Context STALE、product evidence 不 stale。 |
| SRC-08 | 部分 | `freshness.py`、`source.py`；I::test_directory_membership_and_optional_presence_are_freshness_inputs；B::test_fast_missing_contract_is_empty_but_not_created | optional 源出现/消失双向参数尚不齐。 |
| SRC-09 | 部分 | `read_scope.py`、`workspace.py::_fingerprint`；`tests/test_context_read_scope.py::test_untracked_product_file_cannot_be_read_as_gate_input`；`test_untracked_product_file_does_not_block_context_generation` | `eafc69b`：仓库根 untracked 产品文件不再预授权给 Gate；未登记 `read_text` 拒绝发布。workspace fingerprint 经 `_package_open` 哈希，不开放给 Gate。原生 `exists`/`stat` 审计仍按设计不拦截；`file_version` 仍有原生 Path。不关闭 SRC-09。 |
| SRC-10 | 部分 | `store.py`、`evidence.py`；I::test_derived_context_and_telemetry_do_not_self_stale | generated_at 在 sidecar，不进 Context hash；补受控变更时间戳的直接等值测试。 |

## 2. Policy 与 expansion

| ID | 状态 | 实现 / 测试入口 | 未关闭内容 |
|---|---|---|---|
| POL-01 | 映射 | `policy.py::policy_for_risk`；S::test_risk_policy_mapping | 等待独立复核。 |
| POL-02 | 映射 | `escalation.py`；E::test_reported_expansion_changes_policy_not_risk_or_authority；E::test_expansion_is_monotonic_even_at_maximum | 等待独立复核。 |
| POL-03 | 映射 | `escalation.py`；E::test_expansion_is_monotonic_even_at_maximum | 等待独立复核。 |
| POL-04 | 部分 | `integrity.py`、`escalation.py::active_expansions`；I::test_ci12_risk_and_policy_must_match_authoritative_task；E::test_corrupt_expansion_authority_fails_closed | 补 base_policy 独立篡改及合法形状但无正确依据的事件链负例。 |
| POL-05 | 部分 | `escalation.py::effective_policy`；E::test_higher_risk_remains_policy_floor_after_expansion；R::test_risk_escalation_event_follows_risk_without_extra_policy_step | 补真实 `task escalate` CLI 到旧 Context stale 的端到端链路。 |
| POL-06 | 映射 | `escalation.py`；A::test_finding_auto_expansion_is_fresh_and_deduplicated；A::test_accepted_decision_outside_scope_expands_once；R::test_failed_tests_outside_working_set_expand_once | 三类均有重复测试；独立审计指纹是否只绑定判定输入及是否受自身写入影响。 |
| POL-07 | 映射 | `cli.py`、`escalation.py`；E::test_cli_does_not_accept_unknown_or_core_only_reports；E::test_blank_reason_fails_without_writes；E::test_expansion_publication_failure_restores_event_and_budget | 等待独立复核。 |
| POL-08 | 部分 | `escalation.py`、`integrity.py`；E::test_new_task_does_not_inherit_old_expansion | 已测旧 expansion 不继承；补旧 current 对新 task 的 CLI validate 拒绝断言。 |
| POL-09 | 映射 | `escalation.py::FAIL_CLOSED_TRIGGERS`、`store.py`；A::test_context_integrity_unproven_rejects_compact_without_expansion；E::test_cli_does_not_accept_unknown_or_core_only_reports；A/R 其余自动 trigger | `CONTEXT_INTEGRITY_UNPROVEN` 不进入 AUTOMATIC/REPORTED；compact 与 CLI `--compact` 失败且不写 expansions。等待独立复核。 |
| POL-10 | 映射 | `escalation.py::REPORTED_TRIGGERS`；E::test_reported_expansion_changes_policy_not_risk_or_authority | 五枚举参数化。 |

## 3. 分类与兼容

| ID | 状态 | 实现 / 测试入口 | 未关闭内容 |
|---|---|---|---|
| CMP-01 | 部分 | `SKILL.md`、`skills/engineering-harness/SKILL.md` 的 Q0 表；`tests/test_readme_docs.py::test_skill_q0_bypasses_harness_before_session_startup` | 新增 `tests/test_context_skill_routing.py::test_q0_and_unclassified_tasks_bypass_context_generation` 静态回归；不能替代宿主行为证明。 |
| CMP-02 | 部分 | `store.py::_require_task`、`source.py`；C::test_context_requires_task_and_never_initializes_one | 参数覆盖 generate/validate/explain；补 expand 无 task 的相同错误码断言。 |
| CMP-03 | 部分 | `source.py`；B::test_unclassified_task_fails_without_fabricating_risk | 缺失/null 拒绝有测试；补 CLI 的先 classify 提示与零发布断言。 |
| CMP-04 | 映射 | `source.py`、`schemas/task.schema.json`、`telemetry.py`；B::test_classified_old_task_loads_without_new_budget_fields；U::test_unreported_usage_is_null | 等待独立复核。 |
| CMP-05 | 映射 | `source.py`；B::test_fast_missing_contract_is_empty_but_not_created；B::test_existing_invalid_fast_contract_is_not_treated_as_empty | 等待独立复核。 |
| CMP-06 | 映射 | `source.py`；B::test_non_fast_missing_contract_fails_closed | Q2/Q3 × 两份 contract 参数。 |
| CMP-07 | 部分 | `harness_status.py`、`quality_gate.py`、`evidence_validator.py`；`tests/test_status_projection.py`、`tests/test_quality_gate.py`、`tests/test_evidence_validator.py` | `5540ca5`：schema-resource `ContextBuildError` 映射为 `InvalidHarnessState`；`harness gate` stderr 为 `INVALID_HARNESS_STATE`。仍需独立审查是否引入额外 ceremony。 |

## 4. Control Core、候选集与引用

| ID | 状态 | 实现 / 测试入口 | 未关闭内容 |
|---|---|---|---|
| REF-01 | 部分 | `builder.py`；B::test_seeded_requirement_subsets_always_preserve_all_must_records；B::test_core_includes_complete_accepted_decisions_and_open_findings；B::test_core_keeps_must_statement_invariant_scope_and_authorizations | 随机化只看到 requirements；补 invariant/open finding/accepted decision 随机子集。 |
| REF-02 | 映射 | `selector.py`、`integrity.py`；S::test_optional_requirements_need_path_or_open_finding_binding；S::test_closed_finding_and_nonaccepted_decision_are_omitted；I::test_omission_cannot_be_deleted_or_invented_with_valid_ref | 等待独立复核 raw evidence omission。 |
| REF-03 | 映射 | `selector.py`；S::test_local_does_not_list_broad_repo_docs_or_test_scope | 指 Working Set/omitted 候选集；不宣称底层 workspace fingerprint 完全不枚举产品文件。 |
| REF-04 | 映射 | `selector.py::path_is_owned`；S::test_path_binding_uses_segments_not_raw_string_prefix | 参数边界测试。 |
| REF-05 | 映射 | `selector.py`；S::test_path_binding_uses_segments_not_raw_string_prefix；`tests/test_evidence_freshness_and_path_binding.py::test_coverage_rejects_unexecuted_selector_even_when_path_suffix_matches` | Context 路径绑定与产品测试执行覆盖分开。 |
| REF-06 | 映射 | `integrity.py`；I::test_fragment_resolution_requires_exactly_one_record | 独立复核重复 ID 在 loader/schema 提前拒绝与 ref 阶段错误码差异。 |
| REF-07 | 映射 | `source.py`、`integrity.py`、`store.py`；I::test_invalid_reference_path_is_rejected；C::test_context_destination_cannot_be_an_external_symlink | 等待独立复核。 |
| REF-08 | 部分 | `freshness.py`、`selector.py`；S::test_declared_but_unselected_test_and_file_paths_are_accounted；I::test_ci08_bad_reference_is_rejected | 补“删除/未创建文件仍保留 missing 声明”的专属端到端断言。 |
| REF-09 | 部分 | `freshness.py::file_version`、`selector.py`；S::test_local_does_not_list_broad_repo_docs_or_test_scope | 补目录对象不递归展开、显式展开文件分别绑定 hash 的专属测试。 |
| REF-10 | 映射 | `integrity.py`、`schemas/context.schema.json`；I::test_ci10_omission_requires_reason_and_ref；S::test_compact_omitted_mandatory_record_cannot_pass_even_with_ref | 等待独立复核。 |

## 5. Integrity、并发与派生快照

| ID | 状态 | 实现 / 测试入口 | 未关闭内容 |
|---|---|---|---|
| INT-01 | 部分 | `integrity.py`；I 中 CI-01～12 负例；S::test_compact_omitted_mandatory_record_cannot_pass_even_with_ref | 尚非每条 CI × compact/full × CLI exit 2 的完整参数矩阵。 |
| INT-02 | 部分 | `builder.py`、`integrity.py`；B::test_live_blocked_gate_is_projected_without_mutation；S::test_compact_validates_and_keeps_control_identical_to_full | 补 blocked compact CLI 的 typed blocker 全量断言。 |
| INT-03 | 映射 | `source.py`；B::test_gate_failure_never_falls_back_to_persisted_pass；B::test_malformed_control_artifact_is_never_silently_ignored | 等待独立复核。 |
| INT-04 | 部分 | `integrity.py`、`store.py`；I::test_build_rejects_source_mutation_during_gate_assessment；C::test_source_change_during_publication_rolls_back_new_bundle | requirement 受控写入已测；补目录新增、HEAD 变化的构建中插入。 |
| INT-05 | 映射 | `store.py::load_context`；C::test_mixed_or_tampered_companion_is_rejected；C::test_context_evidence_cannot_forge_included_facts | 等待独立复核。 |
| INT-06 | 映射 | `store.py`、`transaction.py`；C::test_publication_failure_restores_last_complete_bundle；C::test_failed_integrity_does_not_publish_or_print_partial_context | 覆盖异常/KeyboardInterrupt，不含 SIGKILL 或断电恢复；不得宣称崩溃原子性。 |
| INT-07 | 映射 | `store.py::load_context`；C::test_cli_validate_is_read_only_and_detects_stale_without_regenerating | 等待独立复核。 |
| INT-08 | 部分 | `cli.py`、`store.py`；C::test_cli_validate_is_read_only_and_detects_stale_without_regenerating；I::test_generated_full_context_validates_without_writes | 补连续 validate 的 task/telemetry/counter 全字节不变断言。 |
| INT-09 | 映射 | `store.py`、`evidence.py`；C::test_cli_generation_saves_matching_bundle_and_prints_only_document；C::test_context_reads_wait_for_complete_bundle_publication | 证明最新成功快照，不证明 Agent 消费或历史保存。 |

## 6. Usage 与 Benchmark

| ID | 状态 | 实现 / 测试入口 | 未关闭内容 |
|---|---|---|---|
| MET-01 | 映射 | `telemetry.py`；U::test_unreported_usage_is_null；U::test_report_total_only_and_save_task_preserve_usage | 等待独立复核。 |
| MET-02 | 映射 | `telemetry.py`、`controlplane.py`；U::test_report_total_only_and_save_task_preserve_usage；U::test_update_preserves_existing_host_fields | 等待独立复核。 |
| MET-03 | 映射 | `telemetry.py`；U::test_reports_are_idempotent_snapshots_and_clear_omitted_fields | 等待独立复核。 |
| MET-04 | 映射 | `telemetry.py`；U::test_invalid_usage_leaves_telemetry_unchanged | 参数化类型、范围、来源与合计检查。 |
| MET-05 | 映射 | `telemetry.py`、`task_replacement.py`；U::test_wrong_task_is_rejected_and_new_task_does_not_inherit | 等待独立复核。 |
| MET-06 | 映射 | `telemetry_lock.py`、`task_replacement.py`；U::test_report_and_local_update_serialize_read_modify_write；U::test_queued_report_rechecks_identity_after_directory_replacement | 等待独立复核。 |
| MET-07 | 映射 | `benchmark.py::_experiment_verdict`、`controlplane.py::cmd_benchmark_compare`；`tests/test_benchmark.py::test_cli_benchmark_compare_writes_correctness_report` | 缺 usage 时 `experiment=INCONCLUSIVE`；stdout 分列 `overall:` 与 `experiment:`。历史 `overall` 仍可 `CORRECTNESS_PRESERVED`。等待独立复核。 |
| MET-08 | 映射 | `benchmark.py::_experiment_verdict`；`tests/test_benchmark.py::test_experiment_failure_overrides_missing_usage_metrics`；`test_experiment_integrity_failure_overrides_estimated_usage` | 已知 Integrity/correctness 失败 → `experiment=FAIL`，不被缺 usage 或 estimated 抵消。等待独立复核。 |
| MET-09 | 映射 | `benchmark.py::_experiment_verdict`；`tests/test_benchmark.py` 缺 usage / 单 run / 非有限 elapsed 等 INCONCLUSIVE 用例 | 无已知失败但必要证据缺失 → INCONCLUSIVE；禁止 null→0。等待独立复核。 |
| MET-10 | 已实现 | `src/harness/benchmark.py`, `tests/test_benchmark.py` | 全部尝试 token / 成功数；100+900/1=1000 测试。 |
| MET-11 | 已实现 | `src/harness/benchmark.py`, `tests/test_benchmark.py` | 空/未知/零成功纯计算与 report 聚合零成功均为 INCONCLUSIVE。 |
| MET-12 | 已实现 | `src/harness/benchmark.py`, `tests/test_benchmark.py` | required correctness regression 优先于缺 usage/estimated/token 降幅，experiment=FAIL。历史 AC16–20 保持分列。 |
| MET-13 | 部分 | `src/harness/{benchmark,telemetry}.py`, `tests/test_benchmark.py` | estimated→低可信 INCONCLUSIVE；完整 runtime Q1 判定；artifact usage 复用 telemetry schema。多运行/聚合实验证据仍待补。 |

## 7. 清单之外的契约核对

1. **§14/§19 SKILL 路由已补**：根 `SKILL.md` 与 `skills/engineering-harness/SKILL.md` 对活跃已分类 mutating task 优先 compact，不再默认 status/全量读取；保留 Q0、CREATED/缺失风险先 classify、禁止手改 state、Integrity 失败不回退、Layer 2 按需读取。新增 `tests/test_context_skill_routing.py`，与既有文档测试合计 29 项通过。此为静态路由验证，外部 Agent 行为测试及独立复核未做。
2. **§13 接口**：`telemetry.py` 已有 `AgentUsage`/`UsageProvider` 和 `report_provider_usage` 注入测试；benchmark artifact 已复用 `normalize_usage`。
3. **§9.2 SRC-09**：`eafc69b` 已拒绝仓库根 untracked 产品文件作为未登记 Gate 输入；`.harness/` 内 extra-policy 负例仍在。原生 `exists`/`stat` 不在 open audit 范围内，SRC-09 保持部分。见 [SRC-09 审计](./Superpowers-Engineering-Harness-v0.2.8-SRC09-Audit.md)。
4. **§16 集成/属性测试**：已新增真实 CLI classify → compact → requirement 修改 → validate STALE → regenerate → Context Evidence/reload 的端到端路径。非 requirement 控制记录的随机子集属性测试仍待补。
5. **§19 文档**：双语 README 已介绍 Context/expansion；愿景规格第 10 行已有实施契约链接。CLI 的完整帮助/错误码验收尚待逐项签收。
6. **快照边界**：README 已说明异常回滚不等于进程强杀恢复。独立复核 §9.3/§12 对“最近成功完整快照”的要求是否接受该边界；未经批准不得把更强保证自动延期。
7. **§19 版本**：`pyproject.toml` / `package.json` / README H1 / CHANGELOG `## 0.2.8` 已对齐（`1772597`）。
8. **Gate 错误域**：产品 Gate 将 schema/source 的 `CONTEXT_*` 收为 `InvalidHarnessState`（`5540ca5`）；Context 未登记读取仍为 `CONTEXT_REFERENCE_BROKEN`。

## 8. 执行记录

日期：2026-09-16。工作树：`be2e21b`（代码基线 `5540ca5` + 本映射文档）。命令与结果：

| 命令 | 结果 |
|---|---|
| `python -m pytest tests/test_version_consistency.py tests/test_readme_docs.py tests/test_telemetry_usage.py tests/test_benchmark.py -q --tb=line` | **136 passed** in 13.29s |
| `python -m pytest tests/test_quality_gate.py tests/test_context_*.py tests/test_context_skill_routing.py -q --tb=line` | **308 passed** in 539.77s |

合计 **444 passed，0 failed**。覆盖版本一致性、README、usage、benchmark、quality_gate、全部 `test_context_*.py` 与 skill routing。

这不是全仓 `pytest`，不是 59 项签收，不是 Product Done，也不证明 Experiment 效率。缺真实宿主 usage 时 Experiment 仍为 `INCONCLUSIVE`。

## 9. 后续建议顺序

1. 正式审查列出的发版阻塞 Spec 项已合入 `5540ca5`，Product Done 测试包已在 `be2e21b` 绿；仍须独立复核，不视为 Product Done。
2. SRC-09 剩余：原生 `exists`/`stat` 与 `file_version` 原生 Path；按设计不扩沙箱，除非契约改威胁模型。
3. 补上表“部分”项的专属测试，以及非 requirement 控制记录的随机子集属性测试。
4. 授权后跑全仓 `pytest`；独立复审完成前不声称 Product Done / Gate CONVERGED，不打 `v0.2.8` tag。

本报告是覆盖盘点，不是正式代码审查结论，不是新产品 evidence，也不授权提交或推进现有无关任务。

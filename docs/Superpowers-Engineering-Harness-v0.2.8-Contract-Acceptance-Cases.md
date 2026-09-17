# v0.2.8 契约验收用例清单

> 依据：[实施契约](./Superpowers-Engineering-Harness-v0.2.8-Implementation-Contract.md)。
> 状态：59 项均待正式签收；已建立[契约—实现—测试映射](./Superpowers-Engineering-Harness-v0.2.8-Acceptance-Mapping.md)，区分已有映射、部分覆盖与实现缺口。不代表 Product Done 或实验通过。
> 范围：保留冻结验收要求；映射盘点不等于重新执行测试，本轮不新增产品代码或可执行测试。

## 1. Source manifest 与 freshness（§9）

| ID | 场景 | 必须观察到的结果 |
|---|---|---|
| SRC-01 | 同一输入连续 compact 两次，再 validate | context_hash 相同；派生文件写入不造成 self-stale |
| SRC-02 | 修改 requirement/invariant/task/scope/authorization | 旧 Context STALE；重生成准确反映修改 |
| SRC-03 | 新增、删除、重开 finding；accept/supersede decision | 集合与记录变化均使旧 Context STALE |
| SRC-04 | 修改 Gate 配置、risk boundaries、interface/observability 或实际读取的间接依赖 | 旧 Context STALE；不得漏掉 Gate 依赖 |
| SRC-05 | 修改 product 文件、直接引用的 ignored 文件、HEAD | 对应源 hash 变化，旧 Context STALE；不宣称覆盖未引用 ignored 文件 |
| SRC-06 | 仅更新 telemetry、临时 staging 或未引用历史归档 | 旧 Context 不因此 STALE；不改变 product evidence freshness |
| SRC-07 | 仅修改控制面 requirement 验证记录 | Context STALE；既有 product evidence 不报 EVIDENCE_WORKSPACE_STALE |
| SRC-08 | optional 源缺失后出现，或已存在源消失 | 集合/存在性变化使旧 Context STALE；FAST 空集规则单独校验 |
| SRC-09 | projection/Gate 读取未登记控制输入 | Integrity 无法证明，拒绝发布，不使用不完整 source manifest |
| SRC-10 | 相同输入仅 generated_at 不同 | context_hash 稳定，时间不参与语义 hash |

## 2. Policy 与 expansion（§7、§10）

| ID | 场景 | 必须观察到的结果 |
|---|---|---|
| POL-01 | Q1/Q2/Q3 已分类 task | base_policy 分别 LOCAL/BOUNDED/EXPANDED |
| POL-02 | Q1 显式 expand 一次、再次 expand | effective policy 单调变为 BOUNDED、EXPANDED；risk/profile 和授权不变 |
| POL-03 | 已 EXPANDED 再显式 expand | 记录合法事件，policy 不变；budget 按事件计数 |
| POL-04 | 篡改 base/effective policy，缺合法 expansion 依据 | CONTEXT_POLICY_MISMATCH |
| POL-05 | task risk 升级 | base 跟随 risk，effective 不降低；旧 Context STALE |
| POL-06 | 同一 finding/decision/失败 evidence 连续触发自动 expansion | 相同依据去重，不重复升档或计数；输出绑定 expansion 写入后的源 |
| POL-07 | 非法 trigger 或空 reason | exit 2，无 expansion/budget 部分写入 |
| POL-08 | 新 task 遇到旧 task expansion/current | 不继承旧 policy；旧 Context 不得通过新 task 校验 |
| POL-09 | 自动 trigger 枚举逐项构造 fixture | FINDING_OUTSIDE_SCOPE、DECISION_OUTSIDE_SCOPE、TEST_FAILURE_OUTSIDE_WORKING_SET、RISK_ESCALATED、CONTEXT_INTEGRITY_UNPROVEN 均覆盖；最后一项拒绝 compact |
| POL-10 | 上报 trigger 枚举逐项调用 | SYMBOL_UNRESOLVED、REQUIREMENT_UNMAPPED、CROSS_MODULE_DEPENDENCY、API_OR_CONFIG_CHANGE、INSUFFICIENT_CONTEXT 均接受；不要求 Core 自行语义发现 |

## 3. 分类与兼容（§5、§18）

| ID | 场景 | 必须观察到的结果 |
|---|---|---|
| CMP-01 | Q0 问答 | SKILL 不创建 task、不读取 .harness、不调用 context/status；这是路由检查，不是 Core 对任意宿主行为的保证 |
| CMP-02 | 缺 current-task | context 各入口 INVALID_HARNESS_STATE / exit 2 |
| CMP-03 | 合法旧 task 缺 risk 或 risk=null | 提示先 classify；不推断 profile，不发布 compact |
| CMP-04 | 已分类旧 task 缺新增 budget optional 字段 | 可生成 Context，无迁移；budget 默认值不传播成宿主 metrics 的 0 |
| CMP-05 | FAST 缺 requirements/invariants | 空集合法，无坏 ref；已有文件 schema 非法仍拒绝 |
| CMP-06 | Q2/Q3 缺 requirements/invariants | fail-closed |
| CMP-07 | status、FAST Light Gate、旧 evidence 使用既有 fixture | 输出/校验契约保持原状，不因 Context 新增强制 ceremony |

## 4. Control Core、候选集与引用（§6、§7）

| ID | 场景 | 必须观察到的结果 |
|---|---|---|
| REF-01 | 随机 MUST/invariant/open finding/当前 task 的 accepted decision 子集 | 全记录进入 Layer 0，原枚举/statement 无损；protected paths 永不遗漏。其他 task 的 accepted decision 不进入 Layer 0 |
| REF-02 | should/could 无绑定，或 closed finding/raw evidence 未内联 | 在候选集内逐项 omitted，含非空 reason 和可解析 ref |
| REF-03 | Q1 仓库包含大量未声明 docs/代码 | 不为 omitted 全仓枚举；manifest 明确集合边界 |
| REF-04 | owned=src/foo，候选 src/foo/a.py 与 src/foobar/a.py | 前者包含，后者不包含 |
| REF-05 | tests/foo.py::test_case 路径绑定 | 原 selector 保留；路径比较只取文件部分，不伪造执行覆盖 |
| REF-06 | 正确 fragment、缺失 fragment、重复 id | 正确引用通过，后两项 CONTEXT_REFERENCE_BROKEN |
| REF-07 | 绝对路径、..、仓库外 symlink | 拒绝越界引用，stdout 不输出损坏 compact |
| REF-08 | 删除文件或尚不存在测试 | 控制事实保留为 missing，引用现存声明记录；直接坏 ref 被拒绝 |
| REF-09 | 目录引用 | 单个对象，不默认递归枚举；展开文件分别绑定内容 hash |
| REF-10 | omitted 缺 reason/ref，或删掉必须保留的控制事实 | 分别触发 schema/完整性校验失败，不静默通过 |

## 5. Integrity、并发与派生快照（§9、§12）

| ID | 场景 | 必须观察到的结果 |
|---|---|---|
| INT-01 | CI-01～CI-12 各破坏一个字段/引用/源版本 | 每条 invariant 有独立负例；错误码符合契约，compact/full 均 exit 2 |
| INT-02 | 业务 Gate BLOCKED，但源合法 | compact 成功，完整输出 live typed blockers |
| INT-03 | loader/Gate 抛异常或源非法 | fail-closed，不回退 persisted gate/status 摘要 |
| INT-04 | 构建过程中受控插入源写入/目录新增/HEAD 变化 | CONTEXT_STALE，不发布混合版本；不靠时间 sleep 猜竞态 |
| INT-05 | manifest/evidence/current hash 不一致 | 读者拒绝，不把部分文件组合成有效 Context |
| INT-06 | 注入发布失败 | 最后一份完整快照不被半写产物替代；无损坏 stdout |
| INT-07 | 修改源后执行 validate | 校验旧 current 并报告 STALE；不自动生成新快照掩盖问题 |
| INT-08 | 连续 validate | 不写 task/telemetry/派生产物，不增加 command counter |
| INT-09 | 两次成功生成不同 Context | 最新三份派生文件关联同一 hash；不承诺历史保留或 Agent 消费证明 |

CI 完整映射：CI-01/02/03/04 → REF-01；CI-05 → REF-01 与篡改 scope；CI-06 → INT-02；CI-07 → 原枚举/状态篡改；CI-08 → REF-06/07/08；CI-09 → SRC-01～10；CI-10 → REF-10；CI-11 → 非法 schema；CI-12 → POL-01/04。正例之外都需对应负例。

## 6. Usage 与 Benchmark（§8、§15）

| ID | 场景 | 必须观察到的结果 |
|---|---|---|
| MET-01 | 未上报；只上报 total_tokens | 未知保持 null；合法 source 下接受 total-only，不推算 input/output |
| MET-02 | 上报后 save_task/本地 telemetry 更新 | agent/usage 保留，local facts 正常更新 |
| MET-03 | 相同累计快照上报两次；随后新快照省略 optional 字段 | 不累加；省略字段规范化 null，不残留旧值 |
| MET-04 | 负数、布尔值、浮点计数、缺 source、token 合计不一致 | 拒绝且原文件不变 |
| MET-05 | 不同 task_id 上报；切换新 task | 拒绝错任务上报；新 task 不继承旧 usage |
| MET-06 | ingest 与本地更新受控并发；提交前 task 切换 | 无丢更新，无跨 task usage；身份变化时拒绝该次上报 |
| MET-07 | 旧 artifact 缺新 metrics | 新实验比较 INCONCLUSIVE；历史 AC 独立保留 |
| MET-08 | correctness regression 或已知 Integrity 失败，但成本下降或 metrics 缺失 | 新总判定 FAIL，不受历史 AC PASS 抵消 |
| MET-09 | 无已知失败但必要证据缺失 | 新总判定 INCONCLUSIVE，不把 null 变 0 |
| MET-10 | 一个成功消耗 100 tokens，一个失败消耗 900 tokens | tokens_per_success=1000，不是 100 |
| MET-11 | 零成功、空输入、任一未知 token/成功状态 | tokens_per_success INCONCLUSIVE，不输出 0 或 Infinity |
| MET-12 | 成功率下降但平均 token 下降 | 实验不能 PASS |
| MET-13 | estimated usage 显示成本下降 | 标记低可信；真实 runtime 效率结论 INCONCLUSIVE |

## 7. 执行与完成边界

1. 先为实际代码变更新增对应可执行测试，再实现；本文件不替代 RED/GREEN 证据。
2. 先做 usage，再做完整 Core，随后 Integrity/freshness，最后 selector/CLI/expansion/SKILL。
3. Product 测试使用合成 fixture 和受控并发，不依赖外部 Agent。
4. 实验需真实宿主 usage、明确 baseline、成功率和完整比较输入；尚无数据时标记 INCONCLUSIVE。
5. 本次文档验收只检查链接、条款一致性和用例覆盖，不运行完整产品测试，也不声称 Harness Gate CONVERGED。

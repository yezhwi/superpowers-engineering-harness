# 原生批次回执 Finding 闭环：短设计

状态：方案 A 及评审修订已确认，已完成原生范围登记并开始实施；后续批准的 Q3 续跑前置项记于本文。不是 Gate 放行、Finding 关闭或实际存储操作授权。

## 目标与边界

TASK-117/FND-001 的修复已有真实 RED/GREEN、独立修复复审及 54 文件/1437 项当前源码批次证明，但当前闭环只接受单份回执。增加原生多回执闭环，使合法有界批次能够证明同一 Finding 的完整相关回归；不伪造聚合 `test_execution`，不放宽原有证明。

保留旧单回执的实际读取/验证行为、Finding 状态机和独立 RED/GREEN；所有新批次强制当前任务 required_tests 覆盖；仅 severity == critical 的新批次另需显式批准，major 批次不读取、不要求 finding.closure。无新依赖、无完整测试套件回退、无自动修改 requirement/invariant 关联、无自动 PASS/Gate/DONE。真实 store 激活/迁移/删除仍不授权。现有 main 与未提交工作区保留，不 commit/push/release。

## 方案选择

- **A（用户选择）**：`finding transition FND-nnn VERIFIED --evidence A.json --evidence B.json`；原生读取每份真实回执，验证后计算覆盖并集，Finding 自身记录引用和原始字节摘要。少一个清单文件/发布协议。
- **B（不选）**：新增外置批次 manifest，闭环再间接解析该清单；审计直观，但增加一致性和身份边界，当前没有必要。

不是把多个回执的字段拼成一份“执行结果”，也不改写已有回执。派生审计清单不能冒充测试执行。

## 接口与持久格式

CLI 只在 adversarial Finding 的 `VERIFIED` 接受 2–64 个 `--evidence`。其他状态和 diagnosability 的重复参数拒绝，不扩大合规闭环语义；旧的 0/1 参数行为不顺手收紧。直接 Python 调用原有字符串参数仍兼容。`VERIFIED -> CLOSED` 不重新接收一批证明：0 个 `--evidence` 时原样保留既有 `closure_evidence`，2 个以上拒绝；不能要求重新提交回执。

单回执继续持久化 `evidence: <ref>`：transition 保持现有 `Path.read_text()` 读取、Gate 保持现有 `source_access.read_text()` 读取，随后都调用原有 `validate_finding_closure_evidence`；该函数 `scope != related` 直接返回、不检查 required_tests 的行为也保持。不把新批次的 no-follow、字节上限或身份绑定套到旧分支。共享 dispatch 只识别格式并拒绝混合，旧格式仍委托原调用点，不统一改成新加载器。多回执持久化互斥字段：

```yaml
closure_evidence:
  version: 1
  receipts:
  - ref: canonical-receipt-a.json
    sha256: sha256:<原始回执字节摘要>
  - ref: canonical-receipt-b.json
    sha256: sha256:<原始回执字节摘要>
```

新批次的 inode 绑定指每次 preparation/校验/发布内的源快照及重校，不给旧单份加持久 inode 约束；Gate 也在本次检查内捕获并重校批次源身份。持久集合记录原始字节摘要，不宣称跨调用固定回执 inode。

多回执不得同时保留 `evidence`；两种格式混合、字段缺失或未知版本均拒绝，不 fallback。旧原生 schema 在 VERIFIED/CLOSED 要求单回执 `evidence`，因此拒绝新批次格式，不能静默只校验第一份。不以包版本、忽略未知字段或伪造代表性第一份回执兼容旧 reader。需要用实际旧 schema 的兼容反例验证。

保留既有 `finding.closure` 作为批准位置，回执集合只放在 `closure_evidence`，摘要不是批准。**选择最小兼容方案：仅新批次强制 critical 批准；旧单回执行为不变。** 当前旧 validator/Gate 不强制读取 closure、transition 缺省不拒绝未批准 critical related 的缺口单独记录，本增量不修复、不追溯使旧 VERIFIED/CLOSED Finding 变红。仅 `severity == critical` 的新批次检查现有 `closure.mode == related`、`critical_related_approved is True`、`source == user` 及非空 `approved_at`，不另外规定批准时间的新鲜度；major 批次不读取、不要求 `finding.closure`。新的 VERIFIED 分支如收到现有 `--critical-related-approved` 参数，先在内存中的候选 Finding 上写入这个 `closure`，再对候选记录做策略检查；不能只读取原 FIXED 记录上尚未产生的批准字段。校验及发布成功前不写回原 Finding。批准是当前 Finding 级而不是这一组回执摘要级。已存在的本 Finding 批准可继续用于新鲜且覆盖充分的替换批次，不要求另一次批准；不得从其他 Finding、major 或 migration grant 推断批准。不新增一个可绕过现有用户授权流程的批准来源。

## 验证不变量

1. **仅新批次分支**在当前 publication owner 内读取 Finding、impact 和回执：回执经现有 evidence_path 及 no-follow source_access；Finding/impact 也用 no-follow 读取并捕获原文。不新增任务状态门槛或额外 current-task.yaml 读取；当前 HEAD/workspace 和当前 impact 由现有调用环境提供，本增量不把 task_id 新检查藏进兼容分支。重复/别名归一化后重复的引用拒绝。
2. 每份回执都必须通过现有 `validate_evidence(... expected_success=True, require_test_execution=True)`：实际执行、成功、当前 HEAD、前后 workspace 一致且等于当前源码。任意一份失败即整体失败，不能只挑有效子集。
3. 新批次只接受已有 related test evidence（unit/integration/contract），不能借 build/custom/review、缺 scope、full/related 混合或手工 coverage 字符串补足证明。原单回执非 related 行为保留；不得利用混合批次进入该兼容分支。
4. required_tests 必须非空且当前完整包含在验证通过的 `covered_tests` 并集内。覆盖的执行真实性仍由现有单份执行验证判定；不把文件名猜测或跳过的参数化测试算作证明。
5. 每次 Gate 检查采用 `closure_evidence` 的 VERIFIED/CLOSED，使用相同新加载器重新打开全部回执，校验持久原始字节摘要、新鲜度、实际执行、当前 required_tests 和批次 critical 批准；required_tests 后续增加不能沿用旧覆盖结论。旧 `evidence` 仍走旧验证函数。摘要不是授权，也不是新鲜度替代品。
6. 新批次 preparation 和 Gate 重读均使用 **2–64 个引用、单份 <= 4 MiB、总原始回执 <= 16 MiB**；超过上限或读取不完整即拒绝，不截断后当成功，不返回成功空集合。精确等于上限允许，并测试边界及多 1 项/字节反例。这些限制不改变旧单份读取语义。
7. 当前 transition 末尾只有 `transaction.atomic_write`，不存在可复用的 after_publish。**新增批次 VERIFIED 发布分支**显式改走 `transaction.stage/publish`（参考 finding_refresh），不改变旧单回执及其他状态写入路径：`expected_sources` 仅固定 Finding 原文，`expected_artifacts` 固定新 Finding；回执和 impact 不进入写集。提交前、以及新设的 `after_publish` 提交前回调重校回执/impact 原始字节和 inode、workspace；回调对已发布 Finding 使用预期新字节，不拿旧 inode 错判本次合法替换。发布前校验失败 Finding 原样；apply 后回调失败走既有中止/恢复协议，若外部冲突使回滚阻断则明确报告部分副作用并保留对象，不承诺无条件原样、不吞异常或伪造成功。不改写、删除或重新署名历史回执。
8. RED/GREEN 仍为同一 Finding/测试节点的独立生命周期证明。回归批次并集不代替 reproduction proof，不自动推进多个状态。

## 已批准的原生 Q3 续跑前置项

用户随后批准将重规划续跑准入纳入必要前置项。`validate_plan_initialization` 保留空 v2 首次入口及所有原 schema/fingerprint/replay 校验；非空入口只在当前 PLANNED、无 active item、存在未启动后缀、已执行部分全为可重放的终结前缀，且存在同任务、有效 frozen hash 和 revisions 的 Alignment 时允许。完整封存与边界仍由原 transition 调用方验证。缺修订、未封存、任务不符、活动项、全终结、乱序前缀或坏日志拒绝，不改输入。旧证明仍不被视为当前新鲜证明，运行时不更新 Plan 指纹或清空日志。

该必要自举先以临时测试复现旧规则拒绝，再在真实任务仍 PLANNED 时，仅修改准入 helper 和对应测试；用户已明确批准此前置范围。195项相关测试通过后，真实任务才通过原生命令进入 IMPLEMENTING 并开始 P-009；没有手工改任务状态。之前单次 DEC-051 Plan 元数据迁移是独立审计操作，不被包装为新的通用迁移 API。该前置代码也必须纳入独立增量审查。

## 模块与消费者

- `evidence_validator.py` 保留原单份闭环函数不变；新增批次先拒绝非 related、缺 scope、full、build/custom/review 及混合记录，再逐份调用基础 `validate_evidence`（不是逐份调用会早退的旧闭环函数），最后计算并集及批次 critical 策略。
- 新 `finding_closure.py` 只为新批次集中有界读取、归一引用、摘要及重校；提供格式选择器，旧单份由原调用点读取并调用旧闭环函数，混合/未知格式不 fallback。
- `controlplane.py` 新批次 VERIFIED 在现有 owner 内使用上述新模块，再明确通过 `transaction.stage/publish` 发布 Finding；不是假设 atomic_write 有回调。
- `quality_gate.py` 新批次 VERIFIED/CLOSED 使用同一边界和策略，单份及诊断类保持各自原路径。
- Finding schema 的 VERIFIED、CLOSED 两个条件都更新为互斥 oneOf；diagnosability 保持原合规格式，保留各自其他生命周期必填字段。CLOSED 0 参数保留批次字段。Context 的新格式识别与 traceability 用测试验证，不放宽 schema/resource access。

## 验收与工作流

测试先观察有意义的 split-coverage RED，再实现。覆盖：旧单份兼容、多份成功、参数化执行不足、缺失/失效/失败/替换回执、摘要变化、重复/越界/超预算、缺/扩展 required_tests、恶意降级/混合格式、critical 批准、Gate 与 CLI 一致、失败零写入、Context 及 installed schema。

先在临时仓库验证；不能为过关先把当前 FND-001 改成 VERIFIED。功能代码变化会使当前全部源码证明失效，后续按新的准确受影响范围采证；不得把当前1437项改指纹后重用。TASK-117 是未完成原任务，新增验证接口涉及公开 CLI 与 Gate：开发前必须通过原生合同/接口/范围与合法任务状态流程登记增量，而不是直接在 VERIFYING 改代码。若原生范围流程无法安全容纳，停止并报告，不换任务逃避检查。

本增量也需要独立审查。关联维护、Finding VERIFIED/CLOSED、原任务最终审查、Gate 与 DONE 是后续各自原生步骤，不由本设计授权自动完成。

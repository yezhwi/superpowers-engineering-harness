# Harness 稳定存储与回收生命周期设计 v0.2

状态：完整设计草案，独立builder检查已完成，8项问题已分类处置并在§15明确；待用户审批。方案B方向已确认，不等于本完整设计或实现/迁移/删除获批。
基线：main / dc4cd9d9c72f509287910f7baa3884832a91e51b。
本阶段仅写/tmp文档，不创建真实.harness-store，不改代码、任务、授权、历史证据或恢复存储。

## 1. 目标、非目标和授权边界

采用已选方案B：仓库本地`.harness-store/`是长期稳定真实目录；`.harness/`仍是当前任务入口。

G1 新任务只增加本任务归档/保留对象，不复制历史全集；平铺保留根深度不随主任务次数增长。
G2 旧树、被位移对象、真实证据和引用仍可定位；移动保留inode，不用内容相同替代对象所有权。
G3 所有真实迁移和删除均独立显式plan/apply；默认只读。授权设计、实现或创建新任务不自动授权搬动现有4.2GiB数据。
G4 未知对象、身份/内容漂移、未决操作、混合版本、越界路径均fail-closed。
G5 保持现有Gate/风险/证据freshness及失败保留规则，不以清理豁免验证。

非目标：自动全盘去重、tar替代inode保留、远程存储、跨设备copy+delete、Linux/网络FS支持、删除原始失败证据、永久保留所有可重跑环境、全局进程/文件句柄沙箱、保证任意旧CLI无法写目录。

本设计要求macOS本地受支持同设备文件系统；每个Git工作区独立store，不绑定Git common-dir，不跨worktree共享。工作区物理根移动/复制须显式重新绑定，不能静默认领。后端平台/设备检查须在创建store或探针前完成。

## 2. 事实与来源

完整只读诊断report.md/inventory.json显示约4.207GiB、199277普通文件，retention约4.200GiB；约95.4%为实验产物与运行环境。当前48组终态事务及48组stage仅约3.40MiB。已存在路径55层、59symlink、1历史FIFO、72嵌套fixture pending目录。

普通全路径扫描曾触发ENAMETOOLONG；所有布局/迁移/清理遍历须descriptor-relative、no-follow，特殊对象不能作为普通文件读取。诊断的文本引用命中不是完整依赖图；lsof无匹配不是FD静止证明。

现有seam：task_replacement进行根目录替换，publication_journal保护常规多文件事务，task_identity从历史/决策保留ID，task_prune管理特定history组，workspace/context/source_access管freshness和读取授权。新存储职责集中在一个storage module外部Interface中，不让每个caller自行拼接新路径。

## 3. Approaches

A 只加GC：小改动，但不阻止history复制及旧树嵌套，否决。
B 稳定store+当前入口：用户已选。保留现有常规文件事务，增加明确的跨根目录周转协调；同步适配历史引用/身份/prune。采用。
C 全面改为固定根与任务命名空间：长期清晰，但需重写任务定位和众多消费者，本轮否决。

## 4. 布局与所有权

```text
repo/
  .harness/                         当前任务规范文件；不使用目录symlink
    current-task.yaml
    gate.yaml
    storage-binding.yaml            新布局绑定，参与控制面freshness
    .transactions/                  当前根常规文件事务恢复权威
    .publication-retained/          当前根常规事务/stage保留；任务切换后随旧根移动
    ...
  .harness-store/                    稳定根，不被task new/recover移动或复制
    store.yaml                      schema=1, store_id, workspace binding, min reader
    operations/                     跨根迁移/任务切换/清理的活动协调记录
    history/
      archives/<archive_id>/        单份规范任务归档（目录真实对象）
      index.yaml                    已登记对象/alias/任务ID/摘要，权威而非随意重建缓存
    retained/
      roots/<operation_id>/previous 旧任务根原对象，不含对外store的嵌套
    experiments/
      <experiment_id>/manifest.yaml 新实验输入、结果与runtime分类声明；不自动收编旧fixture
    receipts/                       迁移/周转/删除的不可覆盖终态回执
    quarantine/<operation_id>/      仅受协调协议定位的待处置对象，不等于已释放空间
```

目录0700、新文件0600；已有对象mode不擅改。store/header/binding固定相对路径，不接受任意外部root字符串。绑定包含store UUID、workspace真实根、store/root设备inode、layout/min-reader身份；文件哈希做完整性而非真实性/防本地恶意修改认证。

已有同名用户目录、文件、symlink、未知部分布局一律拒绝认领。无owner header的`.harness-store`不能因名字相同就从product指纹排除。header/binding不匹配必须阻断，而不是只把该目录当普通数据后继续执行。

store创建/绑定也是显式activation操作；init/Context/diagnostic不能偷偷迁移。Git忽略不等于源访问授权；workspace exclusion、architecture path discovery、read_scope/Context capture及Git query allowlist必须共同适配，固定识别合法store。未绑定的同名用户路径不被忽略，或遇保留名冲突明确拒绝。

## 5. 对外Interface及拒绝语义

建议storage module对caller只暴露四类能力：

1. `inspect_layout(repo_root)`：返回legacy/bound/blocked和精确身份，零写入。
2. `admit_storage(harness_root)`：使用稳定共享owner，检查本工作区store/header/binding及活动协调操作；只检查自己的权威操作，不递归恢复旧fixture。
3. `resolve_archive(reference, scope)`：解析限定历史alias，返回被授权的单个安全ArchiveHandle及其来源/内容身份；不授予整个store读取权限。
4. `plan_operation/apply_operation`：生成或验证operation-specific计划与授权；task周转、真实迁移、终态清理互不通授权。

工具命令名称由实现者沿现有CLI风格选定（建议storage inspect/migrate/prune），但动词不得混淆recover与prune。只读plan可输出到stdout，调用者显式重定向；不能为了dry-run自动写operations、探针、索引或Context。

至少稳定区分：STORE_UNOWNED、STORE_IDENTITY_CHANGED、STORE_READER_UNSUPPORTED、STORE_RECOVERY_REQUIRED、STORE_PLAN_STALE、STORE_REFERENCE_AMBIGUOUS、STORE_UNSAFE_NODE、STORE_AUTHORITY_REQUIRED、STORE_CLEANUP_PARTIAL。新错误分类必须被status/Context/evidence/CLI各入口处理，错误不泄漏原始敏感payload。遇部分副作用需明确标记实际路径及已完成阶段，不输出可盲重试建议。

## 6. 锁与跨根协调

沿用以本工作区规范`.harness`路径为key的现有进程共享锁；store操作不能改用store路径派生另一把锁。读者在该owner内从读取layout、检查pending到消费全部权威事实，避免先检查再无锁读取。先拿唯一owner，再开descriptor/校验；不得进入旧tree的同名锁或多把逆序锁。

常规文件事务仍由.harness/.transactions管理；跨根目录周转由store/operations管理，两者相互admission：普通写入与Gate看到任一当前活动/未知协调记录必须拒绝；操作入口看到当前普通pending必须拒绝并要求显式正常恢复。诊断只解释，不隐式恢复。

目录周转不得直接假借当前publication_journal跨根发布：该引擎绑定单一root/parent/member身份，不能扩大路径接受范围绕过它。新协调器是最小必要directory lifecycle，不是第二套Gate或task状态机。

operation记录固定以下身份：operation/store/workspace ID、kind、源/目标设备inode、成员清单摘要、原始layout/header/binding/hash、每步intent及结果identity、原task、新task、授权计划digest。每帧不可覆盖，哈希链/合法进展校验，完成回执只记录事实，不生成任务完成/授权。

目录操作必须同设备native no-replace，通过持有父fd及目标fd校验；对存在的未知canonical不覆盖、不unlink。prepare、intent、rename、sync、ack、终态边界逐个有process-kill验证。崩溃恢复只能依据identity和实际layout定位已知对象；不按内容hash相同就认领未知inode。

## 7. 新任务周转（止增长）

只在layout已activation且当前pending为空时进入；沿用task new/recover的任务状态和ID权限规则。

1. owner内读取当前task、store/index与Git基线，验证新task ID（包括历史leading-zero别名）未占用，记录源root身份。
2. 新候选根生成本任务规范模板；不复制history或store。决策、接口契约与项目策略暂保持现有显式继承语义，不趁本项目删减长期约束。候选根自己的scope genesis正常创建。
3. 发布单份旧任务档案：只包含task-owned契约/证据/审计等既定归档形状，排除store、完整history、实验运行树。档案的生成与用户保护路径不混淆。
4. 当前旧root经无覆盖rename移至store/retained/roots/<operation>/previous；候选根再经无覆盖rename成为.harness。整个old root原inode及孩子保留；外部held-FD写入仍落在原对象。无需把old root里的既有全历史再次复制到新根。
5. 检查新根绑定、task/schema/最低reader、ID索引、scope genesis、项目策略、archive alias和freshness来源；成功才提交协调终态。更新task中的Git元数据不授予commit/push。

结构图状态（只描述存储，不是task state）：PREPARED → ARCHIVE_READY → OLD_ROOT_RETAINED → NEW_ROOT_INSTALLED → VALIDATED → COMMITTED。每个阶段有明确intent与身份。失败允许显式ABORTING→ABORTED或BLOCKED，不把调用返回异常当没有副作用。

在old root已移走但新根未安装窗口，`.harness`可能暂时不存在；所有新读者必须先检查稳定store/operations，不能把缺失根解释为可init的新仓库。外部竞争者创建同名根则停止，原树留在报告的retained路径。需要回滚已安装候选时，先把属于该操作的候选根无覆盖保留到本operation quarantine，再恢复原root；不覆盖外部root。历史index/alias始终只指完整已验证归档；未完成周转的已准备档案由operation保护，不能被GC。

新布局保留深度相对store固定；旧fixture内部55层历史形状不自动压平，绝不把假pending当真实事务恢复。旧数据迁移下一节单独授权。

## 8. 单份历史与旧引用兼容

新archive ID保留任务ID+唯一时间/随机身份，不覆盖；history/index包含archive task ID、对象身份、descriptor/hash、origin、aliases、引用分类。重复task记录允许不同archive ID，但一个alias最多指一个对象；冲突阻断，不能挑第一个。

兼容解析限定三种既有形式：`history/<archive>/...`、`.harness/history/<archive>/...`、本工作区旧绝对history路径；识别既有sha256片段语法。存储新alias映射，历史receipt的command/ref/payload不改写。

兼容的承诺是Harness内的受支持历史查阅、引用解析、身份保留与prune引用检查；**不承诺直接用旧shell命令访问迁走后的绝对路径，也不自动运行它们**。新CLI应提示原位置/受支持定位方法。不得用symlink让旧命令悄悄访问新位置。

task_identity的所有历史名/文档来源统一走resolver/index；持久化已使用ID登记保留当前语义并只增强防碰撞，不因prune/迁移释放task ID。实现时需版本化ID注册与历史目录原始证据，两者冲突拒绝。

task_prune现有默认最近10任务ID策略不自动授权retained/experiment删除；history新索引/直接目录统一引用扫描，alias/digest模糊引用挡住候选。历史查阅按需加载，Context不扫描所有归档，只捕获当前真实依赖的索引条目/清单身份及其成员引用。store变化不应无差别stale产品测试；影响当前权威解析的变更应stale控制面Context。

## 9. 显式activation与旧布局迁移

迁移分两个独立计划，不能一个含糊apply全做：

M1 activation/以后止增长：claim新store；登记当前history的单份档案和alias；把旧根层retention中的旧task replacement包移至稳定retained位置；新task周转以后不再套娃。每个源目录及目标owner/alias需要无覆盖身份记录，过程中不可隐式删除重复历史。

M2 旧树实验/历史整理：对既有嵌套树只登记实际位置与来源，第一版不递归抽取/压平其中每个嵌套retained根。需要迁出的明确实验或history对象各自列入计划，映射原logical位置，保持字节/inode；不默认拆解fixture。移动旧根包即可阻止以后整体再嵌套，旧内部最大深度不会凭空消失。

真实apply只允许经过确认的维护窗口，store/CLI版本核对、旧Harness会话停止。无活动普通或协调事务；源/目标同设备、祖先no-follow、输入head/内容/namespace清单与计划相符。每一步intent先落盘后move与sync，再ack。执行途中Head/身份变化，保留现场并停止后续调度。先做fixture验证再请求真实仓库迁移授权。

计划hash是内容寻址，不是授权凭据；授权绑定workspace/store/operation kind/候选集合及范围，不能把迁移grant用于删除。dry-run枚举旧对象必须有遍历上限，达到上限返回incomplete而非无候选成功；descriptor-relative可读取长路径，不跟随symlink/FIFO。

M1本身不释放4.2GiB，也不自动修正旧回执原路径。一次转换可能在准备阶段暂增小量元数据/单份当前任务档案；空间不足拒绝，不能先删除旧数据腾地方。

## 10. reader兼容和无法承诺的旧writer防护

store.yaml与storage-binding明确layout=1/required capability集合；新reader仅在全部能力支持时启用新布局。gate.yaml加入闭合schema字段storage_layout，使v0.3.2旧Gate读者拒绝，不能静默按旧路径PASS。新Context/schema/资源枚举/最低reader选择作为同批feature激活，具体发布版本在实现计划按当时版本确定，不虚构已发布tag。

**重要限制：仅加版本字段无法使任意旧writer安全。** 当前load_task不统一验证新layout，某些旧命令可能忽略未知task字段；旧init也可能不检查store。不能承诺所有历史二进制被机器强制阻断。

因此真实activation前强制人工确认已升级所有参与者并停止旧会话/子进程；新CLI/launcher检查已支持该capability，但该检查不证明任意外部脚本不存在。对于不能满足此运营前提的环境，第一版禁止activation/apply，继续legacy布局，不提供自动向后写兼容。旧Gate的拒绝需要测试，但不冒充旧writer的强安全隔离。用户不接受维护前提时必须另选更大规模的入口隔离设计。

## 11. 实验生命周期与回收策略

新实验manifest按对象列出inputs/results/runtime/opaque分类；包含实验ID、源task、工具/环境身份、对象路径和来源、预期再生方式、必须保留的回执与引用。目录名venv或多个相同hash不能自动授予runtime资格。

Inputs和results默认保留；runtime仅在明确可再生声明、相关任务终结、无当前/保留must-keep依赖且有效范围grant下成为候选。无法完整解析的动态/历史引用标为unknown，不自动解引用后删除。人工可以在单独grant中接受放弃某实验环境的原位重放能力，必须保留此决定及原证据，不暗示仍可复现。

第一版优先提供**read-only分类+dry-run**。GC apply须下一份独立设计/授权，不随M1或新任务周转自动启用。候选报告给出逻辑字节、对象数量、类别、原/现位置、identity/内容摘要、明确保留/阻塞原因、已知引用及扫描范围、估计不确定性。

删除门槛：
- 当前活跃规范文件/必要证据/普通与协调pending/未知元数据永不作为GC候选。
- 终态COMMITTED/ABORTED需验证合法链、退休descriptor、slot归属和与活动协调/回执的关系；历史stage复制后的inode不符先unknown，不能用hash替代所有权。
- 有效引用、未知引用、symlink/特殊/多硬链接或源目录跨设备默认阻断（可单独专项处置，不能通用force）。
- 维护窗口及对象持有风险资格明确；lsof只作辅助，不能凭无匹配自动判断无人持有。无法承诺不丢外部继续写入的字节时不执行unlink。
- apply再次持owner核对计划及文件内容/identity；若选择quarantine，先保留对象映射和回执，未unlink就不声称释放。最终删除是独立不可逆动作确认，回执是审计不是数据备份。
- 幂等性：重复请求只报告原结果，不扩大集合；部分失败报告PARTIAL并保留未处理对象及operation，不回滚为“全未执行”。

不同阶段确认必须描述具体动作：移动/放弃环境重放/最终unlink分别授权，避免“同意方案”被扩张为生产删除权。

## 12. 验证与验收（实现计划必须逐项绑定）

V1 legacy无store完全保持现有行为；unknown/user同名文件/目录/链接不认领、不忽略、不覆盖。
V2 连续至少20次new/recover，历史旧对象identity稳定，既有档案集合不重复复制，新增归档量只随新任务产物增长；retained主任务根深度上界固定。
V3 HEAD/工作区freshness：合法store元数据变化不stale产品证明；依赖history引用/index变化stale相应Context；未绑定同名用户代码不能隐身。
V4 每个directory intent/move/sync/ack/terminal处真实进程kill；显式恢复定位原对象、拒绝未知目标，不能自动init；held-FD写入仍保留原inode。
V5 history旧路径/绝对alias/片段/重复ID/leadingzero/dangling/模糊引用正确处理；历史receipt字节不改。prune只作用获权范围。
V6 reader测试：旧v0.3.2 Gate拒绝新storage字段；新所有入口pending/layout检查前置；不得声称旧任意writer都拒绝。
V7 long-path/55层树/symlink/FIFO/多链接/跨设备/目录替换竞争有限扫描，不阻塞特殊流、不越界，不将fixture pending恢复。
V8 migration dry-run零运行目录写入；真实move保留inode；失败与重试不覆盖未知对象，重复apply不重复归档。
V9 runtime分类缺失/错误/被引用/未知依赖拒绝；相同二进制hash不直接触发删除；lsof无匹配不自动授权；quarantine不宣称回收。
V10 macOS原生文件系统fixture测试、相关集成、构建、独立检查、正式Gate分别说明覆盖；不跑全仓库suite或真实GC来冒充fixture验收。

## 13. 实现交付切片与停止条件

D1 layout/resolver/受控读取与admission，legacy兼容、schema、fingerprint、锁资格；未完成前真实activation禁用。
D2 可恢复task turnover+单份history，端到端普通任务循环与kill验证；复用现有regularfile事务，不修改其single-root路径安全含义。
D3 read-only M1/M2规划与显式迁移机制，完整回执/维护前提；真实生产apply需另外授权。
D4 实验manifest与候选dry-run；GC apply后续独立设计。不要为干掉4.2GiB而同时实现不必要的cache/CAS/全局去重系统。

出现同名用户目录、跨设备、未决权威事务、未知角色、HEAD变化、旧writer无法停用或scope/授权不足时停止；不换task逃避、不改Gate策略、不自动授权Decision/commit/push/release。

## 14. 用户决策与实现者可定事项

已确认：方案B、新增仓库本地稳定运行目录`.harness-store/`、先止增长再回收的方向。
待批准：本完整设计，尤其维护窗口/旧writer限制，Harness内逻辑引用兼容但不保证旧shell绝对路径原位执行，以及D1-D4不包含真实迁移/删除/GC apply。
实现者可定：私有类型/模块文件名、CLI具体帮助文本、UUID编码、测试batch划分，在不改变上述语义前提下选择最小实现。不能自行扩大FS/跨worktree/老writer安全承诺或可删集合。

独立builder检查输出与处置记录附于同目录。§15是对§4–13的规范性收敛，发生歧义时以§15为准。获用户批准后才写实施计划、通过新Harness任务契约和TDD实现。当前文档不授权任何真实数据移动或删除。

## 15. 独立builder检查后的规范性澄清

### 15.1 Activation启动与恢复权威

首次activation的权威不是尚未存在的store header，而是当前已验证.harness/.transactions中的一个新版本、显式kind=storage_activation的协调descriptor。它在创建任何store对象前独占当前publication owner，拒绝任何现有pending，绑定已读root/parent设备inode、task/HEAD、用户授权计划digest和目标名；schema/min-reader dispatch是D1必要内容。旧版对未知journal version拒绝是辅助，不替代旧writer停用前提。

Activation期间禁止任务root周转；新ordinary admission先检查此descriptor，显式storage recovery才能解释它，不能由普通事务recover猜测。Activation先在同父目录私有唯一prepare名下生成header/index，再无覆盖安装已记录身份的真实store根，最后发布.harness binding/门禁标记。每一步intent先durable，完成ack记录identity。若进程死在对象创建与identity ack之间，且无法依descriptor及已记录身份严格认领，恢复进入BLOCKED并保留所有对象，要求精确人工处置；不为保证自动恢复率而认领未知同名目录。未知预存.harness-store从第一步就拒绝。

终态提交前当前任务普通操作均阻断；失败可在严格所有权下逆序恢复，无法证明所有权就不继续。Activation descriptor退休到store receipts后才解除协调pending。已有合法store仍有activation pending时走同一显式恢复，不能二次init覆盖。prepare/半初始化目录都纳入报告与回收保护，不因无header当缓存。

### 15.2 引用freshness的精确对象

历史成员引用绑定：(workspace_id, origin_generation_id, logical_archive_alias, selected_alias_record_digest, archive_object_id, archive_descriptor_digest, relative_member_path, member_device_inode, member_content_digest)。安全祖先目录设备inode须实际检查；Context中的身份字段不是授权本身。相同字节的inode替换也必须stale或broken，而不是接受为原对象。迁移必须有显式重绑定回执，旧证据payload不改。

索引read仍观察真实字节，不能缓存隐瞒同路径变化。Context有效性按选定alias条目的语义digest与成员身份判断；仅追加不相关档案不应自动stale产品证明或不依赖它的Context。可在单次受锁构建中重读索引全文件确认所选映射稳定，但不把整个不断追加的索引hash当所有Context的永远freshness条件。活动协调/布局绑定/当前依赖变化仍阻断或stale。

### 15.3 周转的commit、abort和暂存可见性

每次周转有不可复用operation_id；唯一parent/coordinator字段绑定旧active_generation和候选generation。准备归档与alias/ID变更写入operation-owned overlay，不立即进入canonical history/index。OLD_ROOT_RETAINED/NEW_ROOT_INSTALLED都仍是pending，普通读写不可消费。

VALIDATED必须完整校验新root绑定、候选task、archive overlay及所有权；COMMIT intent先落盘，再以无覆盖帧/受控指针把candidate generation及相应历史alias overlay提升为committed，随后完成receipt/retire。恢复检查journal合法进展与实际identity：若commit帧已确认则只允许幂等finish，不自动倒退；无commit帧可在严格拥有所有相关对象时显式abort。索引指针若已经切到candidate但commit尚未确认，仍由pending遮蔽，恢复可按已登记prior identity重置；遇外部替换BLOCKED。

Abort时由本operation生成的档案/alias overlay保留在该operation的retained或quarantine，不作为已接受历史公开，不删除失败输入。候选root同样保留；原active generation与原alias视图恢复。持久化seen/reserved ID记录不撤销：abort不能释放已观察任务身份供重用。ID保留与accepted archive visibility是两个不同事实。

只有一个活动目录协调operation；普通file journal和协调operation不能同时开始。新事务和准备写入不得绕过该admission；协调器内部只有受该operation owner保护的private步进adapter可执行自身协议，不借普通用户命令绕过pending。

### 15.4 M1中已有history的具体处理

M1对当前.harness/history已认可的每个archive目录：记录源identity和原logical alias，将其原目录整体no-replace move到store/history/archives/<archive_id>，不重新copy，不按hash与其他目录合并。保留原空history目录作为非symlink兼容占位是允许的；真实读取/身份检查/prune依赖resolver而非裸Path枚举。M1失败时按manifest身份逆序返还，未知目标则BLOCKED；旧目录移入store不等于历史已经可删除。

旧retained previous树里已有的history副本仍在原位置，M1只记录它们所在generation，不全部抽出或去重。这些副本不是canonical store archive的第二份同义authority；有明确origin的历史引用可按各自generation定位。初次activation不为当前task额外造一份已完成档案；以后真正new/recover才归档其当时快照。

### 15.5 同ID、多次快照与幂等

archive_object_id是独立不可复用ID，source snapshot由origin_generation_id、源档案/root身份、选定规范成员identity+bytes manifest digest描述。只有同一个operation_id重复apply相同计划，才能返回既有归档结果；换operation必须重新判断是否已对该source snapshot归档。

在来源generation、成员身份与内容清单均相符且有原归档receipt时，后续操作引用已有archive_object_id，不再复制。仅task ID相同、仅hash相同或仅目录名相同不能合并。相同task ID的不同状态/证据/manifest产生不同archive_object_id，索引保存各自origin；recover归档的是当时实际源快照。已有archive对应当前task但缺少同一source snapshot所有权/receipt时保留两者并报告，不能猜为重复。

### 15.6 相对/绝对引用的origin

所有新archive descriptor及解析请求携带origin_generation_id。相对history引用以引用记录所属generation解析，不用workspace全局同名fallback。读取legacy对象时origin来自显式登记的所属旧树/任务档案，不来自路径字符串猜测；同名跨代档案可以共存，缺少origin且可能多义则STORE_REFERENCE_AMBIGUOUS。

旧绝对路径保留原字节，按(origin_generation, original_workspace_root, original_logical_path)查询显式迁移alias；包含整个replacement包的move不会改变其origin。工作区rebind必须明确记录旧workspace根与新store/root identity映射，不能悄悄把旧绝对路径替换成当前路径。嵌套fixture的workspace/origin独立，不继承主工作区映射；第一版对没有登记的fixture内部引用只报告unknown，不自动修复/运行。

### 15.7 维护资格需用户批准

真实activation和每次legacy迁移计划包括已声明参与者集合：工作区所有Harness CLI/Agent会话、CI任务、相关测试/构建/fixture/编辑器运行进程及已知外部数据写入者；记录停用/升级方式、工具capability身份及操作者维护确认。没有此确认拒绝apply。该声明与lsof辅助输出不是对未知进程的机器证明。

Activation之后维持“仅兼容reader/writer运行此工作区”的运营约束；普通new/recover在此已确认的兼容参与者约束和共享锁内运行，不要求每个正常任务切换再次做全系统lsof或人工停机。若观察到新旧版本冲突、未知writer或绑定变化，立即停止并要求重新建立维护资格；不宣称能够检测所有任意旧脚本。

后续真实物理删除的资格比普通task turnover更严格：需另行批准可接受的对象持有风险/维护窗口及删除范围，本设计未授权。用户若不能接受兼容参与者约束，B不能按当前设计安全启用，须回到入口隔离方案选型。

### 15.8 history prune在本交付的限制

D1-D4对store-backed history只实现resolution与read-only prune规划；既有task_prune的删除能力继续限于完全legacy布局及原本合法归档形状/授权，bound布局上的destructive legacy prune明确返回unsupported/authority required，不静默转向store路径。

迁移前生成的prune plan、旧路径grant不能作用于迁移后的新object/alias。store-backed archive删除及retained/runtime GC apply均是后续独立设计/明确授权；本轮不以兼容旧命令为理由扩大删除权限。被保留旧树的副本不因为canonical archive被列为候选就一并删除。

## 16. 审查结果与成本说明

独立builder提出8个重大待定义点，无不可避免的基础矛盾。§15.1–6、15.8是作者根据项目实际接口作出的选择，非用户逐项既定要求；§15.7维护资格及兼容语义需随完整设计一起明确批准。

这些选择的代价：strict origin/inode绑定要求合法迁移也显式rebind；M1移动真实history后裸shell旧路径不保证继续可用；新增directory协调协议有必要的kill/竞争测试成本；ID保留登记单调增长；bound布局暂不支持destructive history prune，因此不能靠启用布局立即释放磁盘。若不接受任何一项，应在实施计划前调整，不在实现中偷偷放宽。

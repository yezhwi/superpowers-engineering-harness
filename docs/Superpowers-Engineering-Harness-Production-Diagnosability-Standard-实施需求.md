# Superpowers Engineering Harness - Production Diagnosability Standard 实施需求

> 建议版本：v0.2.x / 后续版本  
> 文档状态：Draft  
> 功能名称：Production Diagnosability Standard  
> 中文名称：生产可诊断性规范  
> 核心原则：**怀疑第三方，防备使用方，做好自己**

---

# 1. 背景

Superpowers Engineering Harness 当前主要解决 AI Coding 过程中的工程正确性问题，包括但不限于：

- Requirement Contract
- 状态机约束
- Test Plan
- Verification
- Evidence
- Adversarial Review
- Gate
- Finding
- Git / Workspace Evidence Binding

这些机制能够回答：

> “AI 修改的代码是否满足当前需求？”

但是对于生产环境的软件，仅仅“当前测试通过”是不够的。

代码上线之后还需要面对：

- 用户异常输入；
- 调用方错误使用；
- 第三方服务超时；
- 数据库异常；
- Redis / MQ / ES 等基础设施异常；
- 外部接口返回异常；
- 网络抖动；
- 重试失败；
- 状态机异常；
- 数据不一致；
- 异步任务失败；
- 偶发生产问题；
- 无法本地复现的问题。

当生产问题发生时，维护人员通常无法直接使用 Debugger，而主要依赖：

```text
业务日志
+
Trace
+
业务 ID
+
错误码
+
上下文
```

进行问题定位。

因此，Harness 不仅需要保证：

```text
代码现在是正确的
```

还需要保证：

```text
代码未来发生异常时是可诊断的
```

本需求旨在将 **Production Diagnosability（生产可诊断性）** 纳入 Engineering Harness 的工程质量体系。

---

# 2. 目标

本需求的目标不是给 Harness 自身增加日志。

目标是：

> Harness 在 AI 开发新需求、修复 Bug、重构业务代码时，自动识别需要可诊断性的代码路径，并要求生成的业务代码具备合理、必要、可维护的日志。

最终使 Harness 管理的代码同时具备：

```text
Correctness
Maintainability
Diagnosability
```

即：

```text
Correctness

现在是否正确？
        │
        ▼
       Test


Maintainability

未来是否容易修改？
        │
        ▼
     Review


Diagnosability

未来发生问题是否容易定位？
        │
        ▼
 Logging / Trace / Context
```

三者共同组成 Engineering Quality。

---

# 3. 核心设计原则

整个 Production Diagnosability Standard 使用三个原则：

```text
怀疑第三方
防备使用方
做好自己
```

英文可定义为：

```text
Distrust External Dependencies

Validate Callers

Observe Yourself
```

这三个原则分别覆盖：

```text
                  使用方
                    │
                    │
               防备使用方
                    │
                    ▼
             ┌──────────────┐
             │ Business App │
             │              │
             │   做好自己    │
             └──────┬───────┘
                    │
                    │
               怀疑第三方
                    │
                    ▼
               外部依赖
```

---

# 4. 原则一：怀疑第三方

## 4.1 定义

任何当前业务代码无法完全控制的组件，都必须认为可能发生异常。

包括但不限于：

- HTTP API
- RPC
- Database
- Redis
- Kafka / MQ
- Elasticsearch
- MinIO / S3 / OSS
- 文件系统
- 第三方 SDK
- LLM
- MCP
- 邮件服务
- 短信服务
- 支付接口
- 外部业务系统
- 操作系统命令
- 网络服务

---

# 5. 第三方调用日志要求

关键第三方调用 SHOULD 能够通过日志回答：

```text
调用了谁？
调用了什么？
操作哪个业务对象？
耗时多少？
结果是什么？
失败原因是什么？
是否超时？
是否重试？
是否降级？
```

推荐结构：

```text
event
trace_id
business_id
dependency
operation
duration_ms
result
error_code
retry_count
```

示例：

```text
event=customer_api_failed
trace_id=T001
customer_id=C1024
dependency=customer-center
operation=query_customer
duration_ms=2134
error_code=TIMEOUT
retry_count=1
```

禁止仅记录：

```text
调用失败
```

或者：

```text
Exception occurred
```

这种日志缺乏诊断价值。

---

# 6. 第三方异常分类

外部依赖失败 SHOULD 尽可能区分：

```text
TIMEOUT
CONNECTION_FAILED
RATE_LIMITED
PERMISSION_DENIED
INVALID_RESPONSE
BUSINESS_REJECTED
SERVICE_UNAVAILABLE
UNKNOWN_EXTERNAL_ERROR
```

禁止将所有异常统一记录为：

```text
REMOTE_ERROR
```

如果底层依赖已经提供稳定错误码，应优先保留原始错误码。

---

# 7. 重试日志

存在重试机制时，必须能够识别：

```text
第几次调用
第几次失败
最终是否成功
最终是否放弃
```

例如：

```text
event=payment_api_retry

payment_id=P001
attempt=2
max_attempts=3
reason=TIMEOUT
```

最终失败：

```text
event=payment_api_exhausted

payment_id=P001
attempts=3
final_reason=TIMEOUT
```

避免每次 retry 都输出完整异常堆栈。

---

# 8. 原则二：防备使用方

## 8.1 定义

业务系统不能假设调用方一定正确使用系统。

调用方包括：

- 用户；
- Browser；
- App；
- 其他微服务；
- MQ Producer；
- 定时任务；
- 第三方系统；
- 管理员；
- Agent；
- LLM；
- MCP；
- 自动化程序。

---

# 9. 入口诊断要求

重要业务入口 SHOULD 能够识别：

```text
谁调用？
调用什么能力？
操作哪个业务对象？
请求是否被接受？
如果拒绝，为什么？
```

例如：

```text
event=refund_request_rejected

trace_id=T001
order_id=ORD001
operator_id=U001
reason_code=REFUND_STATE_INVALID
current_state=SETTLED
```

而不是：

```text
退款失败
```

---

# 10. 业务拒绝必须可解释

对于重要业务操作，应使用稳定 Reason Code。

例如：

```text
REFUND_ORDER_NOT_FOUND

REFUND_ALREADY_COMPLETED

REFUND_AMOUNT_EXCEEDED

REFUND_PERMISSION_DENIED

REFUND_STATE_INVALID
```

Reason Code 应满足：

- 稳定；
- 可搜索；
- 可统计；
- 不依赖自然语言；
- 能映射具体业务原因。

禁止只有：

```text
操作失败

请求异常

业务错误
```

等无意义错误描述。

---

# 11. 参数校验日志

不是所有参数错误都需要 ERROR 日志。

正常业务校验失败通常 SHOULD 使用：

```text
INFO
或
WARN
```

例如：

```text
event=request_rejected
reason_code=INVALID_AMOUNT
order_id=O001
```

只有真正的系统异常才 SHOULD 使用 ERROR。

---

# 12. 原则三：做好自己

系统内部必须能够解释关键业务流程发生了什么。

重点关注：

- 业务状态变化；
- 关键业务决策；
- 关键数据变更；
- 异步任务；
- 补偿；
- 重试；
- 降级；
- 关键流程节点；
- 异常边界。

---

# 13. 关键业务事件

对于关键业务流程，SHOULD 使用业务事件日志，而不是普通方法日志。

例如退款：

```text
refund_requested

refund_validation_passed

refund_record_created

payment_refund_requested

payment_refund_succeeded

order_state_changed

refund_completed
```

发生问题时可以形成：

```text
refund_requested
        │
        ▼
refund_validation_passed
        │
        ▼
payment_refund_requested
        │
        ▼
payment_refund_succeeded
        │
        ▼
order_state_update_failed
```

由此快速判断：

```text
第三方支付退款成功

但是

本地状态更新失败
```

---

# 14. 状态变化日志

关键状态机变化 SHOULD 记录：

```text
business_id
from_state
to_state
trigger
operator
trace_id
```

例如：

```text
event=order_state_changed

order_id=ORD001
from=PAID
to=REFUNDING
trigger=refund_requested
operator_id=U001
trace_id=T001
```

禁止只记录：

```text
状态修改成功
```

---

# 15. 业务关联标识

关键业务日志必须具备可关联能力。

SHOULD 优先包含：

```text
trace_id
request_id
business_id
user_id / operator_id
```

其中：

```text
business_id
```

非常重要。

Business ID 可以是：

```text
order_id
refund_id
project_id
contract_id
document_id
customer_id
task_id
payment_id
```

Harness SHOULD 检查关键业务流程是否存在至少一个可搜索的业务关联标识。

原因：

生产问题通常不会以：

```text
trace_id=T89213
```

的形式反馈。

用户通常会说：

```text
订单 O20260829001 为什么失败？
```

因此维护人员必须能够：

```text
search O20260829001
```

快速获得整个业务轨迹。

---

# 16. 日志等级规范

推荐等级：

| 场景 | Level |
|---|---|
| 正常关键业务事件 | INFO |
| 正常状态变化 | INFO |
| 正常业务拒绝 | INFO/WARN |
| 参数异常 | INFO/WARN |
| 可恢复第三方异常 | WARN |
| Retry | WARN |
| Fallback | WARN |
| 系统内部异常 | ERROR |
| 数据一致性异常 | ERROR |
| 不应该发生的 invariant violation | ERROR |

必须避免：

```text
业务失败 = ERROR
```

例如：

```text
余额不足
权限不足
状态不允许
```

通常属于正常业务结果，不应该产生 ERROR。

---

# 17. 禁止无价值日志

Harness MUST NOT 鼓励 AI 为了满足日志规范而大量增加日志。

以下日志 SHOULD NOT 添加：

```text
进入 xxx 方法

开始执行 xxx

执行 xxx

执行成功

离开 xxx 方法
```

例如：

```java
log.info("进入 createOrder");

log.info("开始创建订单");

...

log.info("创建订单成功");

log.info("离开 createOrder");
```

默认认为属于低价值日志。

---

# 18. 禁止 Debug-style Logging

禁止通过日志模拟 Debugger：

```text
a={}
b={}
c={}
list={}
result={}
```

尤其禁止：

```text
循环中打印每个对象
```

除非存在明确诊断需求。

---

# 19. 禁止完整对象日志

默认禁止：

```text
log.info("request={}", request);

log.info("response={}", response);

log.info("user={}", user);
```

原因包括：

- 日志量过大；
- 敏感信息泄漏；
- JSON 序列化成本；
- 日志可读性差；
- 字段变化导致日志污染。

应该只记录诊断所需字段。

---

# 20. 敏感信息保护

以下内容 MUST NOT 默认写入日志：

```text
password
token
Authorization
Cookie
Secret
API Key
身份证
银行卡
完整手机号
完整邮箱
个人隐私数据
完整客户资料
```

必要时必须：

```text
mask
hash
truncate
```

例如：

```text
138****1234
```

而不是：

```text
13812341234
```

---

# 21. Exception Logging

禁止重复记录同一个异常。

典型反模式：

```java
try {

    service.execute();

} catch (Exception e) {

    log.error("execute failed", e);

    throw e;
}
```

如果上层仍然会记录异常，会造成：

```text
同一个 Exception

Service ERROR
Controller ERROR
GlobalHandler ERROR
```

重复出现。

原则：

> Exception SHOULD 在最有上下文价值的边界记录一次。

---

# 22. 日志价值判断

每增加一条日志，AI SHOULD 判断：

```text
如果半年后线上发生问题，

这条日志是否能够帮助回答：
```

### What happened?

发生了什么？

### Where?

发生在哪个组件/阶段？

### Why?

为什么发生？

### Which business object?

影响哪个业务对象？

### What next?

下一步应该调查什么？

如果日志无法帮助回答上述任何问题，应考虑删除。

---

# 23. Logging Quality ≠ Logging Quantity

本规范明确规定：

```text
日志质量

≠

日志数量
```

目标不是：

```text
更多日志
```

而是：

```text
更高诊断价值的日志
```

---

# 24. Harness Specification 阶段

Harness 在 Requirement / Specification 阶段 SHOULD 判断当前需求是否存在 Production Diagnosability 要求。

判断维度包括：

```text
□ 是否新增业务入口

□ 是否修改关键业务流程

□ 是否存在业务状态变化

□ 是否调用外部依赖

□ 是否存在异步处理

□ 是否存在 Retry

□ 是否存在 Fallback

□ 是否存在补偿逻辑

□ 是否涉及数据一致性

□ 是否涉及权限

□ 是否涉及关键业务对象
```

如果全部为：

```text
false
```

可以：

```text
observability.required = false
```

避免无意义增加日志。

---

# 25. Observability Contract

如果需求涉及可诊断性，应生成结构化约束。

例如：

```yaml
observability:

  required: true

  business_keys:
    - order_id
    - refund_id

  critical_events:
    - refund_requested
    - refund_rejected
    - refund_completed

  state_transitions:
    - PAID -> REFUNDING
    - REFUNDING -> REFUNDED

  external_dependencies:
    - payment_gateway

  failure_boundaries:
    - payment_refund
    - order_state_update
```

注意：

这里定义的是：

```text
诊断需求
```

而不是：

```text
要求具体在哪一行打印 log.info
```

Implementation Agent 仍然拥有合理的实现自由度。

---

# 26. Implementation 阶段

Implementation Agent MUST 根据 Observability Contract 检查：

```text
关键入口

关键业务事件

状态变化

外部依赖

异常边界

业务关联 ID

Reason Code

敏感字段
```

并添加必要日志。

禁止机械地：

```text
每个方法增加日志。
```

---

# 27. Verification 阶段

Harness 不应该要求所有日志进行 Snapshot Test。

例如不建议：

```text
assert log ==
"refund order ORD001 failed..."
```

因为日志文案容易变化。

应该优先验证结构化语义，例如：

```text
reason_code

business_id

event

state

dependency
```

对于高风险代码，可以增加：

```text
敏感字段未进入日志
```

相关测试。

---

# 28. Adversarial Review

Review 阶段增加：

```text
Production Diagnosability Review
```

Reviewer 必须回答：

> 假设该功能半年后在线上失败，只有生产日志，没有 Debugger，是否能够合理定位问题？

至少检查：

```text
□ 是否能够定位关键业务对象

□ 是否能够串联业务流程

□ 是否能够识别调用方错误

□ 是否能够识别第三方异常

□ 是否能够识别系统内部异常

□ 是否记录关键状态变化

□ 是否存在稳定 Reason Code

□ 是否存在敏感信息泄漏

□ 是否存在大量无价值日志

□ 是否存在重复 Exception Logging
```

---

# 29. Finding

如果 Production Diagnosability Review 发现问题，应产生 Finding。

建议 reason code：

```text
DIAG_MISSING_BUSINESS_ID

DIAG_MISSING_CRITICAL_EVENT

DIAG_MISSING_STATE_TRANSITION

DIAG_MISSING_EXTERNAL_FAILURE_CONTEXT

DIAG_MISSING_REASON_CODE

DIAG_UNDIAGNOSABLE_EXCEPTION

DIAG_DUPLICATE_EXCEPTION_LOG

DIAG_SENSITIVE_DATA_LOGGED

DIAG_EXCESSIVE_LOGGING

DIAG_LOW_VALUE_LOGGING
```

---

# 30. Gate

对于关键 Production Diagnosability Finding：

```text
HIGH
CRITICAL
```

Gate SHOULD BLOCK。

例如：

```text
DIAG_SENSITIVE_DATA_LOGGED
```

应该直接阻止完成。

对于：

```text
DIAG_LOW_VALUE_LOGGING
```

可以根据风险等级决定：

```text
WARN
或
BLOCK
```

---

# 31. Bug Fix 特殊规则

Bug Fix 是 Production Diagnosability 最重要的场景之一。

Harness 在修复 Bug 时除了询问：

```text
Root Cause 是什么？
如何修复？
Regression Test 是什么？
```

还 SHOULD 判断：

```text
为什么现有系统没有更早发现/定位这个问题？
```

形成：

```text
Bug
 │
 ▼
Root Cause
 │
 ▼
Fix
 │
 ▼
Regression Test
 │
 ▼
Observability Gap Analysis
 │
 ▼
Logging Improvement
```

---

# 32. Observability Gap

Bug Fix SHOULD 判断是否存在：

```text
observability_gap
```

例如：

```yaml
bug_fix:

  root_cause:
    payment succeeded but local state update failed

  observability_gap:
    true

  missing_information:
    - payment_id
    - order_id
    - state transition failure

  improvement:
    add order state transition failure event
```

如果：

```text
observability_gap = false
```

则不需要为了 Bug Fix 强制增加日志。

---

# 33. 避免“修 Bug 必加日志”

本规范明确禁止：

```text
Bug Fix
=
必须增加日志
```

正确逻辑是：

```text
Bug Fix
        │
        ▼
Observability Gap?
       / \
     YES  NO
      │    │
      ▼    ▼
 Improve  Keep
```

只有确实存在诊断缺口时才修改日志。

---

# 34. 风险分级

Production Diagnosability 应与 Harness Risk Classification 结合。

## Q0

例如：

```text
文案修改
注释修改
简单配置
```

默认：

```text
Diagnosability Review = SKIP
```

---

## Q1

例如：

```text
简单 CRUD
局部逻辑修改
```

执行轻量检查：

```text
business ID
exception
sensitive data
```

---

## Q2

例如：

```text
业务流程
状态机
第三方调用
异步任务
```

执行完整 Diagnosability Review。

---

## Q3

例如：

```text
支付
资金
权限
安全
数据一致性
关键基础设施
```

执行严格检查：

```text
Observability Contract
+
Implementation Review
+
Verification
+
Adversarial Review
+
Gate
```

---

# 35. Harness 推荐行为

当 Harness 发现开发者存在多个合理实现方案时，可以给出推荐。

例如：

```text
检测到 payment gateway 外部调用。

推荐：
记录 dependency / operation / duration / error_code，
而不是完整 request/response。

理由：
能够定位第三方故障，同时避免敏感信息和日志膨胀。
```

推荐必须：

```text
基于当前代码
基于当前需求
基于当前风险
```

不能输出泛化的 Logging Best Practice。

---

# 36. 非目标

本版本明确不实现：

```text
OpenTelemetry 平台

ELK

Loki

Prometheus

Grafana

APM

日志采集系统

日志查询平台

Trace Backend

统一日志 SDK

日志框架替换
```

Harness 只负责：

> 确保生成/修改的业务代码具备合理的生产可诊断性。

---

# 37. 技术栈中立

Production Diagnosability Standard MUST 与语言和日志框架解耦。

例如：

Java：

```text
SLF4J
Logback
Log4j2
```

Python：

```text
logging
structlog
loguru
```

Node.js：

```text
pino
winston
console wrapper
```

Harness 不应该：

```text
强制项目使用某个日志框架
```

应该：

```text
优先遵循项目现有日志体系。
```

---

# 38. Existing Code First

修改代码之前 MUST 首先检查项目已有：

```text
logging framework

logging style

MDC / context

trace_id mechanism

exception handler

reason code convention

masking utility

audit framework
```

原则：

> Harness 应增强现有工程规范，而不是重新发明一套不兼容规范。

---

# 39. 最小修改原则

Harness MUST 避免：

```text
为了日志规范大规模重构已有代码。
```

默认策略：

```text
Minimal Sufficient Diagnosability
```

即：

> 使用最小必要代码变化，使关键故障路径具备足够诊断能力。

---

# 40. Token Optimization

Production Diagnosability Review 必须考虑 Agent Token 消耗。

禁止：

```text
扫描整个仓库所有日志
```

默认只分析：

```text
Changed Files
+
Direct Dependencies
+
Relevant Existing Logging Pattern
```

只有 Q3 或发现系统性问题时才扩大范围。

---

# 41. Acceptance Criteria

实现完成后，以下场景必须通过。

## AC-01 普通代码修改

给定：

```text
修改一个纯计算函数
```

不存在：

```text
外部依赖
业务状态
关键业务流程
```

Harness 不应强制增加日志。

---

## AC-02 外部 API

给定：

```text
新增支付接口调用
```

Harness 应识别：

```text
External Dependency
```

并检查：

```text
dependency
operation
business_id
duration
failure context
```

---

## AC-03 状态变化

给定：

```text
订单 PAID -> REFUNDED
```

Harness 应检查：

```text
order_id
from_state
to_state
trigger
```

是否可诊断。

---

## AC-04 用户错误

给定：

```text
用户重复退款
```

系统返回业务拒绝。

Harness 不应要求 ERROR 日志。

应推荐：

```text
INFO/WARN
+
stable reason_code
```

---

## AC-05 Exception

存在：

```text
catch → log.error → throw
```

且 Global Exception Handler 再次记录异常。

Review 应发现：

```text
DIAG_DUPLICATE_EXCEPTION_LOG
```

---

## AC-06 敏感信息

存在：

```text
log.info("request={}", loginRequest)
```

其中包含 password。

Gate 必须发现：

```text
DIAG_SENSITIVE_DATA_LOGGED
```

并 BLOCK。

---

## AC-07 无价值日志

AI 为每个方法增加：

```text
enter
start
success
exit
```

Review 应识别：

```text
DIAG_LOW_VALUE_LOGGING
或
DIAG_EXCESSIVE_LOGGING
```

---

## AC-08 Bug Fix

给定生产 Bug：

```text
第三方支付成功，
本地订单状态更新失败。
```

现有日志无法判断故障边界。

Harness 应识别：

```text
observability_gap=true
```

并要求补充必要诊断能力。

---

## AC-09 可诊断 Bug

如果现有日志已经可以完整定位 Bug：

```text
observability_gap=false
```

Harness 不应强制增加新日志。

---

## AC-10 Business ID

关键业务流程中日志完全无法通过：

```text
order_id
project_id
refund_id
```

等业务对象关联。

Review 应产生：

```text
DIAG_MISSING_BUSINESS_ID
```

---

# 42. Definition of Done

本需求完成不能仅以：

```text
代码实现完成
```

为标准。

必须提供 Evidence 证明：

```text
1. Specification 能识别 Diagnosability Requirement

2. 普通低风险代码不会被强制增加日志

3. 外部依赖能够触发诊断检查

4. 状态变化能够触发诊断检查

5. Business ID 缺失能够被发现

6. Sensitive Data Logging 能够被发现

7. Duplicate Exception Logging 能够被发现

8. Excessive Logging 能够被发现

9. Bug Fix 支持 Observability Gap Analysis

10. observability_gap=false 时不会强制修改日志

11. Review 能产生结构化 DIAG_* Finding

12. 严重 Finding 能进入 Gate

13. 所有新增测试通过

14. Harness 原有测试无 Regression
```

---

# 43. 最终工程原则

Production Diagnosability Standard 最终必须遵守以下原则：

```text
                    生产可诊断性

                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
       ▼                 ▼                 ▼

   怀疑第三方          防备使用方          做好自己

 External             Caller             Internal
 Dependency           Validation         Business

 timeout              input              event
 failure              rejection          decision
 retry                reason             state
 fallback             identity           exception
 latency              business_id        context
```

并遵循：

```text
Logging Quality ≠ Logging Quantity
```

以及：

> 不为“有日志”而打日志，只为未来能够定位问题而记录日志。

---

# 44. 最终验收问题

Production Diagnosability Review 最终必须能够回答一个问题：

> **假设这段代码明天在线上失败，我们没有 Debugger，只有生产日志，是否能够合理判断发生了什么、问题在哪一层、为什么发生，以及下一步应该调查什么？**

如果答案是：

```text
NO
```

并且该代码属于关键业务路径，则：

```text
Engineering Done = false
```

如果答案是：

```text
YES
```

同时不存在：

```text
敏感信息泄漏
重复日志
过量日志
低价值日志
```

则满足 Production Diagnosability 要求。

---

# 45. 与 Harness 现有能力的关系

本能力不替代：

```text
Test
Evidence
Review
Gate
```

而是补充新的工程质量维度：

```text
Requirement
     │
     ▼
Implementation
     │
     ├───────────────┐
     │               │
     ▼               ▼
Correctness     Diagnosability
     │               │
    Test            Logs
     │               │
     └───────┬───────┘
             ▼
           Review
             │
             ▼
          Evidence
             │
             ▼
            Gate
             │
             ▼
            DONE
```

最终 Harness 的目标从：

> AI 写出的代码通过测试。

进一步提升为：

> AI 写出的代码不仅当前正确，而且具备未来生产维护所需要的可诊断性。

这也是 Production Diagnosability Standard 的最终目标。
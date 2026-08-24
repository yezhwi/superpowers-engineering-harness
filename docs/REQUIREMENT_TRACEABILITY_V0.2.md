# Requirement Traceability v0.2 设计文档

> 状态：规划  
> 优先级：P2 / 不阻塞 v0.1  
> 目标：将 Requirement 与可执行断言、fresh evidence 建立可验证链路。

## 1. 问题

v0.1 已要求 must requirement 有 evidence：

```yaml
- id: REQ-001
  status: verified
  evidence:
    - unit-test.json
```

Gate 能证明：

```text
evidence 存在
→ command exit_code == 0
→ HEAD match
→ workspace fingerprint fresh
```

但无法证明 `unit-test.json` 中的哪个测试验证了 REQ-001。

```text
build PASS
≠
duplicate request does not create duplicate side effect
```

## 2. v0.2 目标模型

```text
Requirement
→ Executable Assertion
→ Evidence Record
→ HEAD + Workspace Snapshot
```

推荐 YAML：

```yaml
requirements:
  - id: REQ-001
    statement: duplicate request does not create duplicate side effect
    priority: must
    status: verified
    evidence:
      - ref: unit-test.json
        assertion: tests/test_order.py::test_duplicate_request_is_idempotent
```

`ref` 指向 `.harness/evidence/unit-test.json`。
`assertion` 是可执行测试 node-id、测试名称或项目定义的 assertion key。

## 3. Schema 演进

v0.2 requirement evidence item：

```json
{
  "type": "object",
  "required": ["ref", "assertion"],
  "properties": {
    "ref": {"type": "string"},
    "assertion": {"type": "string", "minLength": 1}
  },
  "additionalProperties": false
}
```

兼容策略：

```text
v0.1 string evidence refs
→ deprecated warning
→ v0.2 major release 后拒绝
```

不要在 v0.1 silently reinterpret string 为 assertion。

## 4. Evidence 扩展

Evidence 可选存储 machine-readable assertion results：

```json
{
  "type": "unit_test",
  "command": "pytest --junitxml=.harness/reports/unit.xml",
  "exit_code": 0,
  "workspace_fingerprint": "sha256:...",
  "assertions": [
    {
      "id": "tests/test_order.py::test_duplicate_request_is_idempotent",
      "status": "passed"
    }
  ]
}
```

v0.2 初期可支持 assertion manifest，而非强制解析所有测试框架报告：

```yaml
# .harness/assertions.yaml
assertions:
  - id: tests/test_order.py::test_duplicate_request_is_idempotent
    command: pytest tests/test_order.py::test_duplicate_request_is_idempotent
```

## 5. Gate 规则

对 `priority: must` 且 `status: verified` 的 requirement：

```text
1. evidence[] 非空
2. 每项有 ref + assertion
3. ref 对应 evidence 存在
4. evidence exit_code == 0
5. evidence HEAD + workspace fingerprint fresh
6. assertion 出现在 evidence assertions[]，status == passed
```

任一步失败：

```text
QUALITY GATE: BLOCKED
- REQ-001 assertion ... not verified by unit-test.json
```

文档/schema 格式错误：

```text
INVALID_HARNESS_STATE
exit 2
```

## 6. 框架适配

| Framework | Assertion 标识建议 |
|---|---|
| pytest | `path::test_name` |
| Jest/Vitest | `file > suite > test` 或稳定 node id |
| Go test | `package.TestName` |
| JUnit | `class#method` |
| 自定义脚本 | 项目定义的 assertion key |

Harness 不应猜测 assertion 语义；项目 adapter 或 manifest 是权威来源。

## 7. 实施顺序

```text
M1  requirement schema 支持 {ref, assertion}
M2  assertion manifest + CLI collect support
M3  pytest adapter（最小参考实现）
M4  Gate assertion validation
M5  legacy string evidence deprecation
M6  其他 framework adapters
```

## 8. Definition of Done

```text
✓ must requirement 映射到至少一个 executable assertion
✓ Gate 验证 assertion status=passed
✓ assertion 所属 evidence HEAD/workspace fresh
✓ 缺 assertion mapping 时 Gate BLOCKED
✓ schema invalid 时 exit 2
✓ pytest reference adapter 有端到端测试
✓ legacy v0.1 evidence refs 有明确迁移策略
```

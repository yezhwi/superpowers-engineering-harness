# Harness Init 实施手册

> 版本：v0.1  
> 模块：`harness init`  
> 所属项目：Superpowers Engineering Harness  
> 目标：在任意 Git Repository 中安全、幂等地初始化 `.harness/` 工作目录，并为后续 State / Evidence / Gate / Convergence 提供统一入口。

## 1. 模块目标

`harness init` 是 Engineering Harness 的第一个确定性 CLI 命令。

目标：

```text
任意 Git Repo
    ↓
harness init
    ↓
检测 Repo Root
    ↓
创建 .harness/
    ↓
复制默认模板
    ↓
保护已有状态
    ↓
输出初始化结果
```

初始化结果：

```text
.harness/
├── current-task.yaml
├── requirements.yaml
├── invariants.yaml
├── gate.yaml
├── findings/
└── evidence/
```

核心要求：

```text
Deterministic
Idempotent
Safe
Repo-aware
Non-destructive
Testable
```

## 2. 非目标

v0.1 的 `harness init` 暂时不要实现：

- 自动创建业务 Task
- 自动调用 LLM
- 自动生成 Requirements
- 自动生成 Invariants
- 自动执行 Tests
- 自动执行 Quality Gate
- 自动修改 Git 配置
- 自动提交 Git Commit
- 自动安装 Superpowers
- Web UI
- 数据库
- 多项目管理
- Remote Repository 管理

`harness init` 只负责初始化 Harness 的本地控制目录。

## 3. CLI 最终形态

开发完成后，应支持：

```bash
harness init
```

允许在 Repo 根目录执行，也允许在 Repo 子目录执行。CLI 必须自动查找 Git Repository Root。

## 4. 推荐项目结构

```text
superpowers-engineering-harness/
├── pyproject.toml
├── src/
│   └── harness/
│       ├── __init__.py
│       ├── cli.py
│       ├── init.py
│       ├── repository.py
│       └── templates.py
├── templates/
│   ├── current-task.yaml
│   ├── requirements.yaml
│   ├── invariants.yaml
│   └── gate.yaml
├── tests/
│   ├── test_cli_init.py
│   ├── test_init.py
│   └── test_repository.py
└── docs/
    └── HARNESS_INIT_IMPLEMENTATION_GUIDE.md
```

职责：

```text
cli.py
= CLI 参数解析和 Exit Code

init.py
= 初始化流程

repository.py
= 查找 Git Repo Root

templates.py
= 模板定位与复制
```

## 5. pyproject.toml

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "superpowers-engineering-harness"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
harness = "harness.cli:main"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.setuptools.packages.find]
where = ["src"]
```

开发安装：

```bash
pip install -e .
```

安装完成后：

```bash
harness --help
```

应该可用。

## 6. CLI 设计

v0.1 先支持：

```bash
harness init
```

暂时不要增加：

```text
--force
--reset
--repair
--template
--remote
```

尤其不要增加危险的 `--force`，避免覆盖正在使用的 Harness 状态。

## 7. Repo Root 检测

实现：

```python
find_git_root(start: Path) -> Path
```

行为：

```text
当前目录
  ↓
检查 .git
  ↓
没有
  ↓
parent
  ↓
检查 .git
  ↓
...
```

找到就返回 repo root，找不到则抛出 `RepositoryNotFoundError`。

v0.1 应把存在 `.git` 文件或目录都视为 Repo Root：

```python
if (path / ".git").exists():
    return path
```

这样兼容 worktree。

## 8. 初始化行为

核心伪代码：

```python
def init_harness(repo_root: Path, templates_dir: Path) -> InitResult:
    harness_dir = repo_root / ".harness"

    create_directory(harness_dir)
    create_directory(harness_dir / "findings")
    create_directory(harness_dir / "evidence")

    for template in REQUIRED_TEMPLATES:
        target = harness_dir / template.name

        if target.exists():
            mark_skipped(target)
            continue

        copy(template, target)
        mark_created(target)

    return result
```

必须遵循：

```text
不存在 → 创建
已存在 → 保留
绝不默认覆盖
```

## 9. 幂等性 Iron Law

`harness init` 必须是幂等操作。

第一次：

```bash
harness init
```

创建文件。

第二次：

```bash
harness init
```

必须成功，但不能覆盖任何已有状态。

关键测试：

```text
第一次生成文件
人工修改 current-task.yaml
第二次执行 harness init
current-task.yaml 内容不能改变
```

## 10. 默认模板

### current-task.yaml

```yaml
task:
  id: null
  title: ""
  description: ""

state: CREATED

iteration: 0
max_iterations: 5

requirements:
  total: 0
  verified: 0
  uncovered: []

invariants:
  total: 0
  verified: 0
  violated: []

verification:
  build: unknown
  unit_test: unknown
  integration_test: unknown

findings:
  critical: 0
  major: 0
  minor: 0
  confirmed: 0
  proposed: 0

gate:
  status: unknown
  blocked_by: []

git:
  head: null

timestamps:
  created_at: null
  updated_at: null
```

`harness init` 不应自动创建具体 `TASK-001`。

### requirements.yaml

```yaml
requirements: []
```

### invariants.yaml

```yaml
invariants: []
```

### gate.yaml

```yaml
gate:

  requirements:
    must_verified: true
    uncovered_allowed: 0

  invariants:
    violated_allowed: 0

  verification:
    build: required
    unit_test: required
    integration_test: optional

  findings:
    critical_allowed: 0
    major_allowed: 0

  regression:
    confirmed_finding_without_test: 0

  evidence:
    must_match_head: true

  convergence:
    max_iterations: 5
```

## 11. findings/ 和 evidence/

初始化：

```text
.harness/findings/
.harness/evidence/
```

目录允许为空。若希望空目录进入 Git，可以增加 `.gitkeep`，但不是强制项。

## 12. InitResult

建议返回结构化结果：

```python
@dataclass
class InitResult:
    repo_root: Path
    harness_dir: Path
    created: list[Path]
    skipped: list[Path]
```

让领域逻辑与 CLI 输出分离。

## 13. 推荐异常模型

```python
class HarnessError(Exception):
    pass

class RepositoryNotFoundError(HarnessError):
    pass

class TemplateNotFoundError(HarnessError):
    pass

class HarnessInitError(HarnessError):
    pass
```

## 14. Exit Code

```text
0 = SUCCESS
1 = OPERATION_FAILED
2 = INVALID_USAGE
```

Repo 不存在时返回 1；错误 CLI 参数返回 2。

## 15. Repo 外执行

在非 Git repo 中执行：

```bash
harness init
```

应输出明确错误并返回 1。不要自动执行 `git init`。

## 16. 已存在部分 Harness

若只存在：

```text
.harness/
├── current-task.yaml
└── findings/
```

再次 `harness init` 应保留已有内容，并补齐缺失文件和目录。

## 17. 模板缺失

若安装损坏导致模板不存在，不要生成空文件。必须报错并返回 1。

## 18. 文件编码

所有 YAML 使用 UTF-8，不生成 BOM。

## 19. 安全规则

`harness init` 禁止：

```text
删除已有文件
覆盖已有 YAML
清空 findings/
清空 evidence/
修改业务代码
修改 .gitignore
执行 git add
执行 git commit
执行 Tests
调用模型
网络请求
```

初始化命令必须保持 Small / Predictable / Local / Deterministic。

## 20. CLI 推荐实现

`src/harness/cli.py` 负责：

```text
parse args
→ call init service
→ render result
→ return exit code
```

不要把初始化核心逻辑写进 CLI。

## 21. Init Service

建议：

```python
def init_current_repository(cwd: Path | None = None) -> InitResult:
```

默认使用 `Path.cwd()`，测试时允许传 `tmp_path`。

## 22. Template Locator

不要写死本地绝对路径。应从 package/repository 位置定位 templates。后续若发布到 PyPI，再把 templates 作为 package data。

## 23. 测试策略

使用 pytest。

至少：

```text
tests/
├── test_repository.py
├── test_init.py
└── test_cli_init.py
```

## 24. Repository Tests

至少覆盖：

```text
find repo root from root
find repo root from nested directory
accept .git file
fail outside repository
```

## 25. Init Tests

必须覆盖：

```text
creates harness directory
creates required files
creates findings directory
creates evidence directory
is idempotent
does not overwrite existing current-task.yaml
does not overwrite existing gate.yaml
completes partially initialized harness
fails if required template missing
```

## 26. 最重要的测试：不覆盖

必须永久保留一个测试：

```text
init
→ 修改 current-task.yaml
→ 再次 init
→ 内容完全不变
```

## 27. CLI Tests

至少：

```text
success returns 0
outside repo returns 1
prints created files
reports existing harness
```

领域逻辑优先直接调用 Python API；仅少量 CLI 端到端测试使用 subprocess。

## 28. 推荐 TDD 顺序

```text
RED
↓
GREEN
↓
REFACTOR
```

顺序：

```text
1. test find_git_root
2. implement repository.py
3. test creates .harness
4. implement init.py
5. test does not overwrite
6. implement idempotency
7. test CLI
8. implement cli.py
9. end-to-end test
```

## 29. Milestone 划分

### M1 — Repository Detection

实现：

```text
src/harness/repository.py
tests/test_repository.py
```

验收：

```text
Repo Root 正确发现
Nested path 正确发现
Repo 外正确失败
```

### M2 — Init Core

实现：

```text
src/harness/init.py
src/harness/templates.py
templates/*
tests/test_init.py
```

验收：

```text
创建全部 Harness 文件
重复执行安全
已有文件不覆盖
部分初始化可以补齐
```

### M3 — CLI

实现：

```text
src/harness/cli.py
pyproject.toml
tests/test_cli_init.py
```

验收：

```bash
pip install -e .
harness init
```

可正常执行。

### M4 — End-to-End

创建临时 Repo：

```bash
mkdir /tmp/harness-demo
cd /tmp/harness-demo
git init
harness init
```

验证目录，然后修改 `current-task.yaml`，再次 `harness init`，确认内容保留。

## 30. 最终验收命令

```bash
pytest -q
pip install -e .
```

然后：

```bash
tmpdir=$(mktemp -d)
cd "$tmpdir"
git init
harness init
find .harness -maxdepth 2 -print
harness init
```

第二次必须成功且不覆盖。

## 31. Definition of Done

`harness init v0.1` 只有全部满足才完成：

```text
✓ 可通过 harness init 调用
✓ 自动查找 Git Repo Root
✓ 子目录执行有效
✓ Repo 外执行失败
✓ 创建 .harness/
✓ 创建 current-task.yaml
✓ 创建 requirements.yaml
✓ 创建 invariants.yaml
✓ 创建 gate.yaml
✓ 创建 findings/
✓ 创建 evidence/
✓ 使用预定义模板
✓ 重复执行幂等
✓ 已有状态绝不覆盖
✓ 部分 Harness 可以安全补齐
✓ 模板缺失时明确失败
✓ CLI Exit Code 稳定
✓ 核心行为有自动测试
✓ pytest 全部通过
```

## 32. 推荐 Commit

```text
feat: add git repository discovery
feat: add harness initialization core
test: cover idempotent harness initialization
feat: add harness cli init command
test: add harness init end-to-end coverage
docs: document harness init command
```

## 33. 交给 Codex 的实施 Prompt

把本手册放入：

```text
docs/HARNESS_INIT_IMPLEMENTATION_GUIDE.md
```

然后在 Pi / Codex 中执行：

```text
阅读：

docs/HARNESS_INIT_IMPLEMENTATION_GUIDE.md

实现 Engineering Harness 的 `harness init` 命令。

必须严格按照文档中的 M1 → M2 → M3 → M4 顺序实施。

要求：

1. 使用 TDD。
2. 不一次性实现所有逻辑。
3. 先实现并测试 Git Repository Root 检测。
4. 再实现初始化核心。
5. 再实现 CLI。
6. 最后执行端到端测试。
7. `harness init` 必须幂等。
8. 已存在的 `.harness` 文件绝对不允许覆盖。
9. 在 Repo 子目录执行时必须初始化到 Repo Root。
10. Repo 外执行必须失败，不能自动 `git init`。
11. 不实现 `--force`。
12. 不修改 Git 配置。
13. 不执行 git commit。
14. 不调用 LLM。
15. 所有核心行为必须有 pytest 自动测试。

最终必须实际运行：

pytest -q

pip install -e .

并在临时 Git Repo 中实际执行：

harness init

验证第一次初始化和第二次幂等初始化。

不要只汇报实现方案，必须实际修改代码和运行测试。

先给出不超过 10 行的实施计划，然后立即开始 M1。
```

## 34. 后续 CLI 演进

完成 `harness init` 后，可以自然扩展：

```text
harness init
harness status
harness transition VERIFYING
harness evidence unit-test -- pytest
harness gate
harness finding list
harness finding show F-001
harness converge
```

推荐职责：

```text
Pi / Codex
= Worker

Superpowers
= Development Workflow

Engineering Harness Skill
= Orchestration

Harness CLI
= Deterministic Control Plane
```

## 35. 核心原则

`harness init` 虽然只是一个小命令，但它确定了后续 Engineering Harness 的基础边界：

```text
Agent 不负责创建“真相”

CLI 创建 Durable State Container

Repo 保存长期状态

Skill 负责 Orchestration

确定性代码负责 State / Evidence / Gate
```

第一版宁可简单，也必须保证：

> Safe、Idempotent、Non-destructive、Deterministic。

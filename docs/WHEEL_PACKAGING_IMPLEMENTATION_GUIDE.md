# Wheel 独立安装实施手册

> 版本：v0.1.1 规划  
> 目标：`superpowers-engineering-harness` 从 wheel 安装后无需源码 repo，`harness init/status/transition/evidence/gate/converge` 全部可运行。

## 1. 问题

当前 editable install 正常：

```bash
pip install -e .
```

因为 runtime 可向上找到源码 repo 根目录：

```text
<repo>/templates/
<repo>/scripts/
```

但 wheel 安装：

```bash
pip wheel .
pip install dist/*.whl
```

默认只包含 `src/harness/` Python package。repo 根的 `templates/` 和
`scripts/` 不保证进入 wheel。

结果：

```text
harness init        → TemplateNotFoundError
harness status      → 找不到 scripts/
harness gate        → 找不到 scripts/
```

这是发布质量 P1，不是 Harness gate correctness P0。

## 2. 已解决项

运行时依赖已在 `pyproject.toml` 声明：

```toml
dependencies = ["jsonschema>=4.0", "PyYAML>=6.0"]
```

因此干净环境不会因 `import yaml` 或 `import jsonschema` 缺包失败。

## 3. 目标结构

```text
src/harness/
├── __init__.py
├── cli.py
├── init.py
├── repository.py
├── templates.py
├── controlplane.py
├── runtime/
│   ├── __init__.py
│   ├── state_machine.py
│   ├── collect_evidence.py
│   ├── quality_gate.py
│   └── harness_status.py
└── resources/
    ├── __init__.py
    └── templates/
        ├── current-task.yaml
        ├── requirements.yaml
        ├── invariants.yaml
        └── gate.yaml
```

Compatibility scripts may remain at repo root during migration, but must become
thin wrappers around `harness.runtime.*`. Runtime code must never scan upward
for the repo root.

## 4. Template Loading

Use package resources, not filesystem parent traversal:

```python
from importlib.resources import files


def templates_dir():
    return files("harness.resources.templates")
```

`init_harness()` copies each resource using `read_text(encoding="utf-8")`.
No absolute path and no editable-install assumption.

## 5. Runtime Imports

Replace dynamic script loading:

```text
controlplane.py → scans upward → scripts/*.py
```

with direct package imports:

```python
from harness.runtime import quality_gate, state_machine
```

Rules:

- `harness.runtime` may import only package dependencies and stdlib.
- Root `scripts/*.py` import the package runtime; never reverse dependency.
- CLI behavior and raw script behavior must share the same functions.

## 6. Packaging Configuration

Include YAML files as package data:

```toml
[tool.setuptools.package-data]
"harness.resources.templates" = ["*.yaml"]
```

Ensure `resources/`, `resources/templates/`, and `runtime/` contain
`__init__.py` files.

## 7. TDD Order

1. RED: installed wheel cannot locate template.
2. GREEN: move templates into package resources; `harness init` works from wheel.
3. RED: installed wheel `harness status` cannot resolve runtime script.
4. GREEN: move runtime modules; direct imports work.
5. Refactor root scripts into compatibility wrappers.
6. Run full suite plus isolated wheel test.

## 8. Required Tests

### Wheel End-to-End

Run in a fresh virtual environment outside the source checkout:

```bash
python -m build
python -m venv /tmp/harness-wheel-venv
/tmp/harness-wheel-venv/bin/pip install dist/*.whl

repo=$(mktemp -d)
cd "$repo"
git init
/tmp/harness-wheel-venv/bin/harness init
/tmp/harness-wheel-venv/bin/harness status
```

Assert:

```text
.harness/current-task.yaml exists
.harness/requirements.yaml exists
.harness/invariants.yaml exists
.harness/gate.yaml exists
.harness/findings/ exists
.harness/evidence/ exists
```

### Control Plane Smoke Tests

From same temporary git repo:

```bash
harness transition SPECIFYING
harness evidence --type build --command true
harness gate
harness finding list
```

Commands may return expected gate/state errors, but must never fail because
`templates/` or `scripts/` cannot be found.

## 9. Definition of Done

```text
✓ pip install dist/*.whl succeeds in clean venv
✓ harness init works outside source checkout
✓ package resources contain all YAML templates
✓ all control-plane subcommands import runtime modules directly
✓ root scripts are wrappers or removed intentionally
✓ full pytest suite passes
✓ isolated wheel E2E test passes
```

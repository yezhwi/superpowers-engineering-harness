# Package Self-Contained Design

## Goal

Fix CR-004: installed Harness wheel works outside source repository. Runtime must not depend on root `scripts/`, `schemas/`, or `templates/` layout.

## Runtime layout

Move all runtime modules into `src/harness/`: state machine, evidence collection/validation, complexity, quality gate, status renderer, schemas, and templates. `controlplane.py` uses ordinary package imports; it removes parent-directory scanning and dynamic script imports.

Schemas and templates are package data. Runtime reads them through `importlib.resources`, never paths derived from repository root.

Root `scripts/*.py` remain compatibility wrappers only:

```python
from harness.<module> import main

if __name__ == "__main__":
    raise SystemExit(main())
```

CLI, state machine, schemas, user `.harness/` layout, and commands remain unchanged.

## Packaging

Configure setuptools package-data in `pyproject.toml` to include `schemas/*.json` and `templates/*.yaml`. No new dependencies; build wheel with `python -m pip wheel . --no-deps --wheel-dir <tmp>/dist`.

## Verification

Add wheel integration test: build wheel, create fresh venv, install wheel, initialize external Git repository, run `harness --help`, `harness init`, `harness status`, and minimal Gate fixture. Update unit tests to import package modules; retain wrapper coverage for root scripts.

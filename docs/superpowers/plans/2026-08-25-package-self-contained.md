# Package Self-Contained Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make installed wheel self-contained outside source repository while preserving existing CLI and root script compatibility.

**Architecture:** Runtime modules/resources move under `src/harness`; package imports replace dynamic root-script loading; root scripts become wrappers; setuptools includes package JSON/YAML data.

**Tech Stack:** Python 3.11+, setuptools, pytest, pip wheel, venv.

**Spec:** `docs/superpowers/specs/2026-08-25-package-self-contained-design.md`

## Global Constraints

- No new dependency; build with `python -m pip wheel . --no-deps`.
- No CLI, state-machine, schema, or user `.harness/` behavior change.
- Root scripts remain callable wrappers.
- Runtime imports must not search source repository paths.

---

### Task 1: Package resources and state machine

**Files:**
- Move: `scripts/state_machine.py` → `src/harness/state_machine.py`
- Move: `schemas/*.json` → `src/harness/schemas/`
- Move: `templates/*.yaml` → `src/harness/templates/`
- Modify: `src/harness/templates.py`
- Modify: `pyproject.toml`
- Create: `tests/test_package_resources.py`

**Interfaces:**
- `harness.state_machine` exports existing `STATES`, `is_legal`, `require_legal`.
- `harness.templates.templates_dir()` returns traversable package template directory.

- [ ] Write RED tests importing `harness.state_machine` and checking all required template/schema resources exist.
- [ ] Run `python -m pytest tests/test_package_resources.py -q`; expect failure.
- [ ] Move files without semantic edits; use `importlib.resources.files("harness")`; configure setuptools package data.
- [ ] Run focused tests GREEN.
- [ ] Replace root `scripts/state_machine.py` with wrapper and test `python scripts/validate_state.py CREATED SPECIFYING` still passes.
- [ ] Commit: `git commit -m "refactor: package harness resources"`.

### Task 2: Move runtime modules and simplify control plane

**Files:**
- Move: `scripts/{collect_evidence,evidence_validator,complexity,quality_gate,harness_status}.py` → `src/harness/`
- Modify: `src/harness/controlplane.py`
- Replace: corresponding root `scripts/*.py` with wrappers
- Modify: tests importing `scripts/`

**Interfaces:**
- `harness.controlplane` imports runtime via normal package imports.
- Every moved module retains existing public functions and `main(argv=None)` behavior.

- [ ] Write RED test monkeypatching source-root discovery absent and calling CLI `status`/`gate`; expect package import path to work.
- [ ] Run focused control-plane tests RED.
- [ ] Move modules; replace filesystem `SCHEMAS_DIR` with resource-reader helper; remove `_scripts_dir`/`_load`.
- [ ] Add thin wrappers importing `harness.<module>.main` only.
- [ ] Run `python -m pytest tests/test_control_plane.py tests/test_quality_gate.py tests/test_evidence.py -q` GREEN.
- [ ] Commit: `git commit -m "refactor: run control plane from package modules"`.

### Task 3: Wheel isolation test

**Files:**
- Create: `tests/test_wheel_install.py`
- Modify: test helpers only if required

**Interfaces:**
- Wheel installs into fresh venv and exposes `harness` independently of checkout.

- [ ] Write test using temporary `dist`, `venv`, and external Git repo.
- [ ] Build with `python -m pip wheel . --no-deps --wheel-dir <dist>`.
- [ ] Install only produced wheel into venv.
- [ ] Assert `harness --help`, `harness init`, and `harness status` return zero outside source checkout and `.harness/current-task.yaml` exists.
- [ ] Run RED before package-data/runtime migration complete, then GREEN after Tasks 1–2.
- [ ] Commit: `git commit -m "test: verify installed wheel outside repository"`.

### Task 4: Compatibility and full verification

**Files:**
- Modify only for test-exposed defects.

- [ ] Run root wrappers: `python scripts/validate_state.py CREATED SPECIFYING`, `python scripts/collect_evidence.py --help`, `python scripts/quality_gate.py --help`.
- [ ] Run `python -m pytest tests/ -q`.
- [ ] Search `src/harness` for `parent / "scripts"`, `parent / "schemas"`, `parent / "templates"`; expect no repository-layout discovery.
- [ ] Commit verification-only corrections.

## Plan self-review

Tasks 1–2 implement package-contained runtime; Task 3 proves wheel isolation; Task 4 preserves wrappers and verifies no source-layout dependency. CR-004 only; no unrelated behavior changes.

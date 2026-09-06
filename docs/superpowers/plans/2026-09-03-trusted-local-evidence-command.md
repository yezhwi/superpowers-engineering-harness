# Trusted-local Evidence Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make shell-capable evidence execution explicit trusted local-operator behavior.

**Architecture:** Introduce immutable `TrustedLocalCommand` in `collect_evidence`; only CLI parsing creates it, and `collect` requires it before retaining `shell=True`. Preserve command text and current shell syntax.

**Tech Stack:** Python stdlib dataclasses, argparse, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-trusted-local-evidence-command-design.md`

## Global Constraints

- Preserve local shell syntax and evidence command text.
- Never claim remote/config/API command values are trusted.
- No argv-only or dual-mode interface.

---

### Task 1: Trusted command boundary

**Files:**
- Modify: `src/harness/collect_evidence.py`
- Create: `tests/test_collect_evidence.py`

**Interfaces:**
- Produces: `TrustedLocalCommand(value: str)`.
- Produces: `collect(..., command: TrustedLocalCommand, ...) -> dict`.

- [ ] Write failing test requiring `collect` to reject raw string command input.
- [ ] Run `pytest tests/test_collect_evidence.py::test_collect_requires_trusted_local_command -q`; expect failure because raw string executes.
- [ ] Add frozen `TrustedLocalCommand`; reject non-wrapper input with deterministic `ValueError`; execute wrapper `.value` with existing `shell=True` call.
- [ ] Run focused test; expect pass.

### Task 2: CLI-local construction and compatibility

**Files:**
- Modify: `src/harness/collect_evidence.py`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Test: `tests/test_collect_evidence.py`

**Interfaces:**
- Consumes: argparse-local `args.command`.
- Produces: evidence retaining original command string.

- [ ] Write failing test showing trusted wrapper preserves `echo one && echo two` execution and evidence command field.
- [ ] Run test; expect failure before CLI creates wrapper.
- [ ] Construct wrapper only in `main`; document trusted-local shell boundary in both READMEs.
- [ ] Run focused tests; expect pass.

### Task 3: Regression proof

**Files:**
- Test: `tests/test_collect_evidence.py`

- [ ] Add timeout regression proving byte stdout/stderr decode into string tails under trusted wrapper.
- [ ] Run exact focused suite; expect pass.
- [ ] Record impact, Q3 reviews, related test/build proof, and Gate.

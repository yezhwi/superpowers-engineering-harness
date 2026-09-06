# Control-plane Import and Readability Refactor Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove generic dynamic module dispatch and expand dense handlers without behavioral change.

**Architecture:** Import direct Harness dependencies at `controlplane` module boundary. Preserve local YAML imports only where necessary. Expand dense handler bodies while retaining existing helper calls, error strings, returns, and persistence operations.

**Tech Stack:** Python stdlib, existing Harness modules, pytest.

**Spec:** `DEC-006 controlplane-import-refactor`

## Global Constraints

- No CLI text, exit code, transition, or persistence semantic changes.
- No formatting outside touched handler blocks.
- Use existing atomic persistence helpers.

---

### Task 1: Direct module imports

**Files:**
- Modify: `src/harness/controlplane.py`
- Test: `tests/test_control_plane.py`

- [ ] Write failing import/command regression proving `cmd_status` and task save behavior work without `_load`.
- [ ] Run exact test; expect failure after removing `_load` only.
- [ ] Add direct imports; replace `_load` calls; remove `importlib` and `_load`.
- [ ] Run control-plane regression suite.

### Task 2: Dense command-handler expansion

**Files:**
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/cli.py`
- Test: `tests/test_control_plane.py`, `tests/test_cli_interface.py`

- [ ] Write golden tests for representative success/error routes.
- [ ] Run tests; expect failure only for missing expected regression coverage.
- [ ] Expand handlers into normal multi-line branches; preserve literal output and return codes.
- [ ] Run focused tests and wheel build.

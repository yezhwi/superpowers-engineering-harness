# Task Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add audited recovery from an active stale Harness task into a fresh `CREATED` task.

**Architecture:** Keep CLI parsing in `harness.cli`; put recovery filesystem workflow in `harness.controlplane` beside existing `cmd_task_new`. Recovery copies task YAML, moves artifact directories into timestamped history, writes immutable recovery metadata, then resets active files from bundled resources.

**Tech Stack:** Python 3.11, argparse, pathlib, shutil, PyYAML, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-task-recovery-design.md`

## Global Constraints

- No dependency added.
- `task new` still accepts only `DONE` or `ESCALATED` tasks.
- `task recover` requires `TASK-[0-9]+` ID and nonempty `--reason`.
- Recovery archives YAML and moves `findings/` plus `evidence/`; it never deletes old task artifacts.
- Fresh task always starts in `CREATED`.

---

## File Structure

- `src/harness/cli.py`: parse `harness task recover ID --title --reason`; dispatch to control plane.
- `src/harness/controlplane.py`: validate active task, archive it, write audit, recreate active task.
- `tests/test_cli_task_recovery.py`: black-box CLI tests in temporary Git repositories.

### Task 1: Recovery CLI contract

**Files:**
- Modify: `src/harness/cli.py: task subparser setup and task dispatch`
- Create: `tests/test_cli_task_recovery.py`

**Interfaces:**
- Produces CLI form: `harness task recover TASK-005 --title TITLE --reason REASON`.
- Consumes future `controlplane.cmd_task_recover(task_id: str, title: str, reason: str) -> int`.

- [ ] **Step 1: Write failing parser tests**

```python
def test_task_recover_requires_reason(tmp_path):
    repo = make_repo(tmp_path)
    result = run_cli(repo, "task", "recover", "TASK-005")
    assert result.returncode == 2
    assert "--reason" in result.stderr


def test_task_recover_rejects_invalid_id(tmp_path):
    repo = make_repo(tmp_path)
    result = run_cli(repo, "task", "recover", "bad", "--reason", "stale")
    assert result.returncode == 2
    assert "INVALID TASK ID" in result.stderr
```

- [ ] **Step 2: Run tests; verify RED**

Run: `python -m pytest tests/test_cli_task_recovery.py -q`

Expected: parser rejects unknown `recover` command; no recovery implementation exists.

- [ ] **Step 3: Add parser and dispatch**

In `main()` task parser setup:

```python
p_recover = ts.add_parser("recover")
p_recover.add_argument("id")
p_recover.add_argument("--title", default="")
p_recover.add_argument("--reason", required=True)
```

In task dispatch:

```python
if args.task_command == "recover":
    return controlplane.cmd_task_recover(args.id, args.title, args.reason)
```

Do not implement recovery behavior in CLI.

- [ ] **Step 4: Run parser tests; verify remaining failure is control-plane behavior**

Run: `python -m pytest tests/test_cli_task_recovery.py -q`

Expected: `--reason` test passes; invalid-ID test fails until Task 2 adds control-plane validation.

- [ ] **Step 5: Commit parser contract**

```bash
git add src/harness/cli.py tests/test_cli_task_recovery.py
git commit -m "feat: add task recovery cli contract"
```

### Task 2: Validate and archive stale active task

**Files:**
- Modify: `src/harness/controlplane.py: after cmd_task_new`
- Modify: `tests/test_cli_task_recovery.py`

**Interfaces:**
- Produces `cmd_task_recover(task_id: str, title: str, reason: str) -> int`.
- Produces `.harness/history/<old-id>-<timestamp>/recovery.yaml` fields: `recovered_at`, `reason`, `previous_task_id`, `previous_state`, `replacement_task_id`.
- Consumes active `.harness/current-task.yaml` and bundled `harness.templates.templates_dir()`.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_task_recover_rejects_terminal_task_without_mutation(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "DONE", task_id="TASK-004")
    before = (repo / ".harness/current-task.yaml").read_text()
    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")
    assert result.returncode == 1
    assert "requires active task" in result.stderr
    assert (repo / ".harness/current-task.yaml").read_text() == before
    assert not list((repo / ".harness/history").glob("TASK-004-*"))


def test_task_recover_invalid_id_leaves_active_task_intact(tmp_path):
    repo = make_repo(tmp_path)
    before = (repo / ".harness/current-task.yaml").read_text()
    result = run_cli(repo, "task", "recover", "bad", "--reason", "stale")
    assert result.returncode == 2
    assert (repo / ".harness/current-task.yaml").read_text() == before
```

- [ ] **Step 2: Run tests; verify RED**

Run: `python -m pytest tests/test_cli_task_recovery.py -q`

Expected: invalid ID reaches missing control-plane function or lacks expected rejection; terminal state is not rejected by recovery behavior.

- [ ] **Step 3: Implement pre-mutation validation and YAML archive**

Add `cmd_task_recover` using existing `load_task` and `save_task` helpers. Before creating archive:

```python
if not re.fullmatch(r"TASK-[0-9]+", task_id):
    print("INVALID TASK ID", file=sys.stderr)
    return 2
if not reason.strip():
    print("RECOVERY_REASON_REQUIRED", file=sys.stderr)
    return 2
old = load_task(harness_dir)
if old.get("state") in {"DONE", "ESCALATED"}:
    print("task recover requires active task", file=sys.stderr)
    return 1
```

Create archive with collision protection. Copy only four active YAML files before artifact moves. Use UTC timestamp in archive name. Write `recovery.yaml` with `yaml.safe_dump(..., sort_keys=False)` after archive creation.

- [ ] **Step 4: Run validation tests; verify GREEN**

Run: `python -m pytest tests/test_cli_task_recovery.py -q`

Expected: invalid-ID and terminal-state tests pass. Successful-recovery test not yet added.

- [ ] **Step 5: Commit validation/archive foundation**

```bash
git add src/harness/controlplane.py tests/test_cli_task_recovery.py
git commit -m "feat: validate task recovery requests"
```

### Task 3: Move artifacts and initialize replacement task

**Files:**
- Modify: `src/harness/controlplane.py: cmd_task_recover`
- Modify: `tests/test_cli_task_recovery.py`

**Interfaces:**
- `cmd_task_recover` moves active `findings/` and `evidence/` to archive.
- On success, active `.harness/current-task.yaml` has ID `TASK-005`, requested title, and state `CREATED`.
- Active `.harness/findings/` and `.harness/evidence/` exist and are empty.

- [ ] **Step 1: Write failing success test**

```python
def test_task_recover_archives_artifacts_and_creates_fresh_task(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "IMPLEMENTING", task_id="TASK-004")
    findings = repo / ".harness/findings"
    evidence = repo / ".harness/evidence"
    (findings / "FND-001.yaml").write_text("id: FND-001\n")
    (evidence / "unit.json").write_text("{}")

    result = run_cli(repo, "task", "recover", "TASK-005", "--title", "Wheel isolation", "--reason", "stale task")

    assert result.returncode == 0, result.stderr
    archive = next((repo / ".harness/history").glob("TASK-004-*"))
    audit = yaml.safe_load((archive / "recovery.yaml").read_text())
    assert audit["previous_state"] == "IMPLEMENTING"
    assert audit["reason"] == "stale task"
    assert audit["replacement_task_id"] == "TASK-005"
    assert (archive / "findings/FND-001.yaml").is_file()
    assert (archive / "evidence/unit.json").is_file()
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["task"] == {"id": "TASK-005", "title": "Wheel isolation"}
    assert task["state"] == "CREATED"
    assert list(findings.iterdir()) == []
    assert list(evidence.iterdir()) == []
```

Add test proving normal task creation remains protected:

```python
def test_task_new_still_rejects_active_task(tmp_path):
    repo = make_repo(tmp_path)
    result = run_cli(repo, "task", "new", "TASK-005")
    assert result.returncode == 1
    assert "DONE or ESCALATED" in result.stderr
```

- [ ] **Step 2: Run tests; verify RED**

Run: `python -m pytest tests/test_cli_task_recovery.py -q`

Expected: recovery does not yet move artifacts or reset active task.

- [ ] **Step 3: Implement move and reset sequence**

After YAML archive/audit:

```python
for name in ("findings", "evidence"):
    source = harness_dir / name
    if source.exists():
        shutil.move(str(source), str(archive / name))
    (harness_dir / name).mkdir()
```

Overwrite only active `current-task.yaml`, `requirements.yaml`, `invariants.yaml`, and `gate.yaml` from `templates_dir()`. Load replacement task, assign `task.id` and `task.title`, save via `save_task`. Do not modify `task new`.

- [ ] **Step 4: Run focused tests; verify GREEN**

Run: `python -m pytest tests/test_cli_task_recovery.py -q`

Expected: all recovery CLI tests pass.

- [ ] **Step 5: Run regression suite**

Run: `python -m pytest tests/test_cli_init.py tests/test_cli_complexity.py tests/test_control_plane.py -q`

Expected: PASS. Confirms CLI parsing, init, and existing control-plane behavior.

- [ ] **Step 6: Commit recovery workflow**

```bash
git add src/harness/controlplane.py tests/test_cli_task_recovery.py
git commit -m "feat: recover stale harness tasks"
```

### Task 4: Verify installed package behavior

**Files:**
- Modify: `tests/test_wheel_isolation.py`

**Interfaces:**
- Installed console script provides `harness task recover` outside repository checkout after `harness init`.

- [ ] **Step 1: Write failing installed-wheel assertion**

After installed wheel initializes its temporary Git repository, run:

```python
result = subprocess.run(
    [harness, "task", "recover", "TASK-005", "--reason", "stale"],
    cwd=outside, capture_output=True, text=True,
)
assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run test; verify RED only if console script lacks command**

Run: `python -m pytest tests/test_wheel_isolation.py -q`

Expected: PASS if Tasks 1-3 are installed by wheel build; failure indicates package-data/import regression and must be fixed before continuing.

- [ ] **Step 3: Run final verification**

Run: `python -m pytest tests/ -q`

Expected: PASS.

Also run:

```bash
harness task recover --help
rg -n 'parent / "(scripts|schemas|templates)"|parent\.parent / "(schemas|templates)"' src/harness
```

Expected: help lists `--reason`; search has no matches.

- [ ] **Step 4: Commit installed-wheel coverage**

```bash
git add tests/test_wheel_isolation.py
git commit -m "test: cover task recovery from installed wheel"
```

## Self-Review

- Spec coverage: Tasks 1-3 cover required CLI, validation, archive copy/move, audit, fresh `CREATED` task, and unchanged normal task flow. Task 4 covers installed-package runtime.
- Placeholder scan: no TODO/TBD or undefined implementation steps.
- Type consistency: CLI dispatch and `cmd_task_recover(task_id, title, reason)` match every task.

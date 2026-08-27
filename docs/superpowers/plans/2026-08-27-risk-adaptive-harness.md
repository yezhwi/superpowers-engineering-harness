# Risk-Adaptive Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe rule-based risk classification and FAST Q1 workflow while preserving deterministic evidence, Gate, and authorization controls.

**Architecture:** `harness.risk` owns pure risk/profile validation and monotonic escalation. CLI/control-plane persist a validated risk record and drive a new `CLASSIFIED` state. `quality_gate` dispatches FAST tasks to a narrow Light Gate; all other profiles retain existing Gate logic. Authorization is normalized to independent records without implying permission across actions.

**Tech Stack:** Python 3.11, PyYAML, jsonschema draft-07, pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-risk-adaptive-harness-design.md`

## Global Constraints

- Q0 is agent-side inquiry behavior; no Q0 CLI/task creation.
- Use rules, not ML or keyword classification.
- Q1 with Q2/Q3 risk must fail closed; no silent promotion.
- Escalation is monotonic: Q1→Q2/Q3 and Q2→Q3 only.
- FAST retains real RED/GREEN evidence, freshness, deterministic Gate, and explicit authorization.
- FAST must not require requirements/invariants/impact/minimal-plan/complexity artifacts.
- Never weaken STANDARD/STRICT evidence freshness, finding, recovery, baseline, review, or authorization behavior.
- Do not implement evidence reuse, execution budgets, state shortcuts, telemetry, or benchmarks.
- Never use `git add .`; stage exact paths and run `git diff --cached --check` before each commit.

---

### Task 1: Rule-based classification, persisted risk metadata, and CLI

**Files:**
- Create: `src/harness/risk.py`
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/state_machine.py`
- Modify: `src/harness/schemas/task.schema.json`
- Modify: `src/harness/templates/current-task.yaml`
- Test: `tests/test_risk.py`
- Test: `tests/test_control_plane.py`

**Interfaces:**
- Produces `RiskDimensions`, `RiskClassificationError`, `classify(level: str, dimensions: dict[str, str]) -> str`, and `validate_escalation(current: str, target: str) -> None`.
- Produces `cmd_task_classify(level: str, dimensions: dict[str, str]) -> int` and `cmd_task_escalate(level: str, reason: str) -> int`.
- Consumes existing `load_task`, `save_task`, `workspace_fingerprint`, and state-machine transition validation.

- [ ] **Step 1: Write pure classifier failing tests**

```python
import pytest
from harness.risk import RiskClassificationError, classify, validate_escalation

SAFE = {"scope": "low", "contract": "none", "data": "none", "authorization": "none", "security": "none", "concurrency": "none", "deployment": "none"}

def test_safe_q1_selects_fast():
    assert classify("Q1", SAFE) == "FAST"

def test_q1_with_contract_risk_fails_closed():
    with pytest.raises(RiskClassificationError, match="RISK_LEVEL_UNDERSPECIFIED"):
        classify("Q1", {**SAFE, "contract": "low"})

def test_q2_to_q1_downgrade_is_rejected():
    with pytest.raises(RiskClassificationError, match="RISK_DOWNGRADE_FORBIDDEN"):
        validate_escalation("Q2", "Q1")
```

- [ ] **Step 2: Run classifier tests RED**

Run: `python -m pytest tests/test_risk.py -q`

Expected: FAIL because `harness.risk` does not exist.

- [ ] **Step 3: Implement `harness.risk`**

```python
RISK_LEVELS = ("Q1", "Q2", "Q3")
PROFILES = {"Q1": "FAST", "Q2": "STANDARD", "Q3": "STRICT"}
DIMENSION_VALUES = {
    "scope": {"low", "high"},
    "contract": {"none", "low", "high"},
    "data": {"none", "low", "high"},
    "authorization": {"none", "low", "high"},
    "security": {"none", "low", "high"},
    "concurrency": {"none", "low", "high"},
    "deployment": {"none", "low", "high"},
}

def classify(level: str, dimensions: dict[str, str]) -> str:
    minimum = required_level(dimensions)
    if RISK_LEVELS.index(level) < RISK_LEVELS.index(minimum):
        raise RiskClassificationError("RISK_LEVEL_UNDERSPECIFIED")
    return PROFILES[level]
```

`required_level` returns Q3 for any high data/authorization/security/concurrency/deployment, Q2 for non-none contract or high scope, otherwise Q1. Reject missing/unknown dimension values.

- [ ] **Step 4: Run classifier tests GREEN**

Run: `python -m pytest tests/test_risk.py -q`

Expected: PASS.

- [ ] **Step 5: Write CLI persistence/transition failing tests**

```python
def test_task_classify_q1_persists_fast_profile_and_enters_classified(tmp_path):
    repo = make_repo(tmp_path)
    result = run_cli(repo, "task", "classify", "--level", "Q1", *SAFE_FLAGS)
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert result.returncode == 0
    assert task["state"] == "CLASSIFIED"
    assert task["risk"]["profile"] == "FAST"
    assert task["risk"]["workspace_fingerprint"]

def test_task_escalate_records_reason_and_rejects_downgrade(tmp_path):
    # classify Q1, escalate Q2, then attempt Q1
    assert run_cli(repo, "task", "escalate", "--level", "Q1", "--reason", "undo").returncode == 2
```

- [ ] **Step 6: Run CLI tests RED**

Run: `python -m pytest tests/test_control_plane.py -k 'classify or escalate' -q`

Expected: FAIL because task subcommands and `CLASSIFIED` do not exist.

- [ ] **Step 7: Add task schema, template, state, CLI, and control-plane support**

Add `CLASSIFIED` to `STATES`, task schema state enums, and transition `("CREATED", "CLASSIFIED")`, `("CLASSIFIED", "IMPLEMENTING")`. Add task schema `risk` object requiring `level`, `profile`, `dimensions`, `escalation_history`, and `workspace_fingerprint` when present. Add template `risk: null`.

Add CLI subcommands with required dimension flags:

```python
p_classify = ts.add_parser("classify")
p_classify.add_argument("--level", choices=["Q1", "Q2", "Q3"], required=True)
for name in RISK_DIMENSIONS:
    p_classify.add_argument(f"--{name}", required=True)
p_escalate = ts.add_parser("escalate")
p_escalate.add_argument("--level", choices=["Q2", "Q3"], required=True)
p_escalate.add_argument("--reason", required=True)
```

`cmd_task_classify` requires `CREATED`, calls `classify`, captures current workspace fingerprint, writes the risk record, then uses `require_legal("CREATED", "CLASSIFIED")`. `cmd_task_escalate` validates current risk, calls `validate_escalation`, updates level/profile, appends `{from, to, reason}`, and does not alter state.

- [ ] **Step 8: Run Task 1 tests GREEN**

Run: `python -m pytest tests/test_risk.py tests/test_control_plane.py -q`

Expected: PASS.

- [ ] **Step 9: Commit Task 1**

```bash
git add src/harness/risk.py src/harness/cli.py src/harness/controlplane.py src/harness/state_machine.py src/harness/schemas/task.schema.json src/harness/templates/current-task.yaml tests/test_risk.py tests/test_control_plane.py
git diff --cached --check
git commit -m "feat: classify tasks by risk profile"
```

### Task 2: FAST state guards and Light Gate

**Files:**
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/quality_gate.py`
- Modify: `src/harness/blockers.py`
- Test: `tests/test_fast_workflow.py`
- Test: `tests/test_control_plane.py`
- Test: `tests/test_quality_gate.py`

**Interfaces:**
- Consumes `task["risk"]["profile"]`, existing `run_gate`, `validate_evidence`, `workspace_fingerprint`, and typed `GateBlocker`.
- Produces `run_fast_gate(harness_dir: Path, head: str, workspace: str) -> tuple[str, list[GateBlocker]]` and FAST blocker code `FAST_REGRESSION_EVIDENCE_MISSING` routed to VERIFYING.

- [ ] **Step 1: Write FAST transition and Light Gate failing tests**

```python
def test_fast_classified_transitions_to_implementing_without_minimal_decision(tmp_path):
    repo = classified_fast_repo(tmp_path)
    result = run_cli(repo, "transition", "IMPLEMENTING")
    assert result.returncode == 0

def test_fast_gate_requires_fresh_red_and_green_evidence(tmp_path):
    h = fast_harness(tmp_path, state="GATING")
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert blockers[0].code == "FAST_REGRESSION_EVIDENCE_MISSING"

def test_fast_gate_passes_with_current_red_and_green_evidence(tmp_path):
    h = fast_harness(tmp_path, state="GATING")
    write_fast_evidence(h, phase="red", exit_code=1)
    write_fast_evidence(h, phase="green", exit_code=0)
    assert run_gate(h)[0] == "PASS"
```

Use real `collect_evidence`-shaped JSON with current commit and workspace fingerprint. RED must have nonzero exit code; GREEN must have zero.

- [ ] **Step 2: Run FAST tests RED**

Run: `python -m pytest tests/test_fast_workflow.py -q`

Expected: FAIL because FAST bypass and Light Gate do not exist.

- [ ] **Step 3: Implement FAST state guard behavior**

In `cmd_transition`, detect `task.get("risk", {}).get("profile") == "FAST"`:

- allow `CLASSIFIED → IMPLEMENTING` without minimal evidence;
- allow `VERIFYING → GATING` without complexity evidence;
- reject FAST transitions into SPECIFYING, PLANNED, REVIEWING, REPRODUCING, and FIXING with `FAST_PROFILE_TRANSITION_FORBIDDEN`.

Add legal transitions `IMPLEMENTING → VERIFYING`, `VERIFYING → GATING` while retaining all existing STANDARD/STRICT transitions.

- [ ] **Step 4: Implement `run_fast_gate` and dispatch**

At start of `run_gate`, after schema/load/head/workspace setup, dispatch when profile is FAST. Validate classification fingerprint equals current workspace fingerprint. Read exactly two evidence records named `fast-red-unit-test.json` and `fast-green-unit-test.json`; validate commit/fingerprint via existing `validate_evidence`, expecting false then true. Return typed verification blockers for absent, stale, or wrong-result evidence. Do not load or require requirements, invariants, impact, findings, or complexity evidence in this branch.

Add FAST code(s) to `RECOVERY_POLICY` with target VERIFYING. Preserve existing normal `run_gate` logic untouched for non-FAST profiles.

- [ ] **Step 5: Add workspace-protection failing test**

```python
def test_fast_gate_blocks_when_workspace_changed_since_classification(tmp_path):
    h = fast_harness(tmp_path, state="GATING")
    write_fast_evidence(h, phase="red", exit_code=1)
    write_fast_evidence(h, phase="green", exit_code=0)
    (tmp_path / "user-change.txt").write_text("do not overwrite")
    status, blockers = run_gate(h)
    assert status == "BLOCKED"
    assert blockers[0].code == "FAST_WORKSPACE_CHANGED"
```

- [ ] **Step 6: Run workspace test RED, then implement blocker**

Run: `python -m pytest tests/test_fast_workflow.py::test_fast_gate_blocks_when_workspace_changed_since_classification -q`

Expected before implementation: FAIL because changed workspace is accepted.

Add `FAST_WORKSPACE_CHANGED: VERIFYING` to recovery policy. In `run_fast_gate`, compare the persisted classification fingerprint with current workspace fingerprint before accepting evidence. Never modify workspace files.

- [ ] **Step 7: Run Task 2 tests GREEN**

Run: `python -m pytest tests/test_fast_workflow.py tests/test_control_plane.py tests/test_quality_gate.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/harness/controlplane.py src/harness/quality_gate.py src/harness/blockers.py tests/test_fast_workflow.py tests/test_control_plane.py tests/test_quality_gate.py
git diff --cached --check
git commit -m "feat: add fast risk-adaptive gate"
```

### Task 3: Independent authorization records, documentation, and compatibility regression

**Files:**
- Modify: `src/harness/cli.py`
- Modify: `src/harness/controlplane.py`
- Modify: `src/harness/schemas/task.schema.json`
- Modify: `src/harness/templates/current-task.yaml`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Test: `tests/test_authorization.py`
- Test: `tests/test_readme_docs.py`
- Test: `tests/test_control_plane.py`

**Interfaces:**
- Produces `cmd_authorize(action: str, granted: bool) -> int`.
- Consumes legacy `authorization.full_suite.granted` and emits normalized `authorizations.full_suite.granted`.
- Existing `harness authorize full-suite` remains accepted.

- [ ] **Step 1: Write authorization failing tests**

```python
def test_authorizations_are_independent(tmp_path):
    repo = make_repo(tmp_path)
    assert run_cli(repo, "authorize", "commit").returncode == 0
    task = load_task(repo)
    assert task["authorizations"]["commit"]["granted"] is True
    assert task["authorizations"]["push"]["granted"] is False

def test_full_suite_requires_its_own_authorization(tmp_path):
    repo = make_repo(tmp_path)
    run_cli(repo, "authorize", "commit")
    result = run_cli(repo, "evidence", "--type", "unit_test", "--scope", "full_suite", "--command", "true")
    assert result.returncode == 2
    assert "FULL_SUITE_AUTHORIZATION_REQUIRED" in result.stderr
```

- [ ] **Step 2: Run authorization tests RED**

Run: `python -m pytest tests/test_authorization.py -q`

Expected: FAIL because authorization actions beyond full-suite are rejected.

- [ ] **Step 3: Implement normalized independent authorization**

Define `AUTHORIZATION_ACTIONS = ("commit", "full_suite", "push", "create_mr", "ready_mr", "merge", "deploy")`. CLI accepts each action and `revoke-<action>`. `cmd_authorize` writes `task["authorizations"][action] = {"granted": bool, "granted_at": ISO-8601 UTC timestamp, "source": "user"}`. Template and schema declare `authorizations` records.

Compatibility helper `authorization_granted(task, action)` checks normalized record first, then old `authorization.full_suite` only for `full_suite`. Use helper in evidence CLI full-suite guard. Do not permit any action to satisfy another action.

- [ ] **Step 4: Run authorization tests GREEN**

Run: `python -m pytest tests/test_authorization.py tests/test_control_plane.py -q`

Expected: PASS.

- [ ] **Step 5: Write documentation failing test**

```python
def test_readmes_document_risk_profiles_and_independent_authorization():
    for path in (REPO / "README.md", REPO / "README.zh-CN.md"):
        text = path.read_text()
        assert "Q1" in text and "FAST" in text
        assert "harness task classify" in text
        assert "harness authorize commit" in text
        assert "harness authorize push" in text
```

- [ ] **Step 6: Run documentation test RED**

Run: `python -m pytest tests/test_readme_docs.py::test_readmes_document_risk_profiles_and_independent_authorization -q`

Expected: FAIL because risk-adaptive workflow is undocumented.

- [ ] **Step 7: Document Q0/Q1/Q2/Q3 and FAST boundaries**

Add concise bilingual README sections. Q0: direct answer/no task. Q1: classify with all risk dimensions, capture RED and GREEN evidence, transition FAST path, Gate. Q2/Q3: current STANDARD/STRICT process remains. State that FAST does not authorize commit, push, or full-suite and list independent authorization commands. State deferred features are not available.

- [ ] **Step 8: Run Task 3 tests GREEN**

Run: `python -m pytest tests/test_authorization.py tests/test_readme_docs.py tests/test_control_plane.py -q`

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add src/harness/cli.py src/harness/controlplane.py src/harness/schemas/task.schema.json src/harness/templates/current-task.yaml README.md README.zh-CN.md tests/test_authorization.py tests/test_readme_docs.py tests/test_control_plane.py
git diff --cached --check
git commit -m "feat: add independent harness authorizations"
```

### Task 4: Cross-profile regression and release verification

**Files:**
- Modify: `CHANGELOG.md`
- Test: `tests/test_risk.py`
- Test: `tests/test_fast_workflow.py`
- Test: `tests/test_authorization.py`

**Interfaces:**
- Consumes all prior task interfaces.
- Produces release-facing v0.2.3 changelog entries.

- [ ] **Step 1: Write cross-profile regression test**

```python
def test_standard_profile_retains_existing_complexity_requirement(tmp_path):
    repo = classified_standard_repo(tmp_path, state="VERIFYING")
    result = run_cli(repo, "transition", "REVIEWING")
    assert result.returncode == 1
    assert "COMPLEXITY_REVIEW_REQUIRED" in result.stderr
```

- [ ] **Step 2: Run regression test RED if standard guard was accidentally bypassed**

Run: `python -m pytest tests/test_fast_workflow.py::test_standard_profile_retains_existing_complexity_requirement -q`

Expected: PASS after Tasks 1–3. If it fails, repair profile dispatch before release.

- [ ] **Step 3: Update changelog**

Add an unreleased `0.2.3` section listing rule-based risk classification, FAST Light Gate, independent authorization records, and explicit deferral of evidence reuse, budgets, shortcut states, telemetry, and benchmark work.

- [ ] **Step 4: Run focused cross-profile suite**

Run: `python -m pytest tests/test_risk.py tests/test_fast_workflow.py tests/test_authorization.py tests/test_control_plane.py tests/test_quality_gate.py tests/test_state_machine.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add CHANGELOG.md tests/test_risk.py tests/test_fast_workflow.py tests/test_authorization.py
git diff --cached --check
git commit -m "docs: record risk-adaptive harness scope"
```

## Final verification

- [ ] Record impacted files, dependents, contracts, risks, and focused tests with `harness impact add-*`.
- [ ] Request explicit current-task authorization before full suite.
- [ ] Run `harness evidence --type unit_test --scope full_suite --command "python -m pytest tests/ -q"`.
- [ ] Run `harness evidence --type build --command "python -m pip wheel . --no-deps --wheel-dir /tmp/harness-risk-adaptive-wheels"`.
- [ ] Write `/tmp/TASK-risk-adaptive-complexity-review.yaml` with current task id, immutable base SHA, current HEAD SHA, and findings; run `harness review complexity --file /tmp/TASK-risk-adaptive-complexity-review.yaml`.
- [ ] Verify every requirement/invariant with fresh evidence, route clean review through `harness review outcome PASS --reason-code REVIEW_CLEAN`, and run `harness gate`.
- [ ] On Gate PASS, transition `CONVERGED → DONE`, run `git diff --check`, and report deferred scope explicitly.

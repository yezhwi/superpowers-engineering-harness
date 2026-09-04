"""Milestone 1: State Core tests.

Covers:
- fixed enum of states
- legal transition table
- forbidden transitions rejected (IMPLEMENTING/VERIFYING/REVIEWING/FIXING/BLOCKED -> DONE)
- only CONVERGED -> DONE allowed
- validate_state.py CLI exit codes
- persistence via templates/current-task.yaml + harness_status.py
"""

import json
from importlib import resources
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

from harness.state_machine import (
    STATES,
    TRANSITIONS,
    InvalidTransition,
    is_legal,
    legal_targets,
)


# ---------------------------------------------------------------------------
# 1. Fixed enum
# ---------------------------------------------------------------------------

EXPECTED_STATES = {
    "CREATED",
    "CLASSIFIED",
    "SPECIFYING",
    "PLANNED",
    "IMPLEMENTING",
    "VERIFYING",
    "REVIEWING",
    "REPRODUCING",
    "FIXING",
    "GATING",
    "BLOCKED",
    "CONVERGED",
    "DONE",
    "ESCALATED",
}


def test_states_are_fixed_enum():
    assert set(STATES) == EXPECTED_STATES


def test_no_extra_states():
    assert len(STATES) == 14


# ---------------------------------------------------------------------------
# 2. Legal transition table (spec section 6.2)
# ---------------------------------------------------------------------------

EXPECTED_TRANSITIONS = {
    ("CREATED", "CLASSIFIED"),
    ("CREATED", "SPECIFYING"),
    ("CLASSIFIED", "IMPLEMENTING"),
    ("CLASSIFIED", "SPECIFYING"),
    ("SPECIFYING", "PLANNED"),
    ("PLANNED", "IMPLEMENTING"),
    ("IMPLEMENTING", "VERIFYING"),
    ("IMPLEMENTING", "SPECIFYING"),
    ("VERIFYING", "IMPLEMENTING"),
    ("VERIFYING", "GATING"),
    ("VERIFYING", "REVIEWING"),
    ("REVIEWING", "REPRODUCING"),
    ("REVIEWING", "VERIFYING"),
    ("REVIEWING", "GATING"),
    ("REPRODUCING", "REVIEWING"),
    ("REPRODUCING", "FIXING"),
    ("FIXING", "VERIFYING"),
    ("GATING", "BLOCKED"),
    ("GATING", "CONVERGED"),
    ("BLOCKED", "IMPLEMENTING"),
    ("BLOCKED", "VERIFYING"),
    ("BLOCKED", "REPRODUCING"),
    ("BLOCKED", "ESCALATED"),
    ("CONVERGED", "DONE"),
}


def test_transition_table_matches_spec():
    assert TRANSITIONS == EXPECTED_TRANSITIONS


@pytest.mark.parametrize("current,target", sorted(EXPECTED_TRANSITIONS))
def test_all_legal_transitions_allowed(current, target):
    assert is_legal(current, target) is True


@pytest.mark.parametrize("current,target", sorted(EXPECTED_TRANSITIONS))
def test_validate_state_cli_accepts_legal(current, target):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "validate_state.py"), current, target],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# 3. Forbidden transitions (spec section 6.3)
# ---------------------------------------------------------------------------

FORBIDDEN_TO_DONE = [
    ("IMPLEMENTING", "DONE"),
    ("VERIFYING", "DONE"),
    ("REVIEWING", "DONE"),
    ("FIXING", "DONE"),
    ("BLOCKED", "DONE"),
]


@pytest.mark.parametrize("current,target", FORBIDDEN_TO_DONE)
def test_direct_to_done_rejected(current, target):
    assert is_legal(current, target) is False


@pytest.mark.parametrize("current,target", FORBIDDEN_TO_DONE)
def test_validate_state_cli_rejects_done_shortcut(current, target):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "validate_state.py"), current, target],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "INVALID" in result.stdout + result.stderr


def test_converged_to_done_is_the_only_path_to_done():
    entries_into_done = [c for (c, t) in TRANSITIONS if t == "DONE"]
    assert entries_into_done == ["CONVERGED"]


# ---------------------------------------------------------------------------
# 4. Unknown states and self-transitions rejected
# ---------------------------------------------------------------------------


def test_unknown_state_rejected():
    with pytest.raises(InvalidTransition):
        is_legal("WAT", "DONE")


def test_unknown_target_rejected():
    with pytest.raises(InvalidTransition):
        is_legal("CREATED", "WAT")


def test_self_transition_rejected():
    for s in EXPECTED_STATES:
        assert is_legal(s, s) is False


def test_validate_state_cli_invalid_state_name():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "validate_state.py"), "BOGUS", "DONE"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1


def test_legal_targets_helper():
    assert legal_targets("VERIFYING") == {"IMPLEMENTING", "REVIEWING", "GATING"}
    assert legal_targets("DONE") == set()


# ---------------------------------------------------------------------------
# 5. Persistence: schema + template + harness_status
# ---------------------------------------------------------------------------


def test_task_schema_declares_fixed_state_enum():
    schema = json.loads(
        resources.files("harness").joinpath("schemas", "task.schema.json").read_text()
    )
    enum_values = set(schema["properties"]["state"]["enum"])
    assert enum_values == EXPECTED_STATES


def test_template_state_in_enum():
    import yaml

    tpl = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "current-task.yaml")
        .read_text()
    )
    # guide HARNESS_INIT section 10: init must not pre-create a concrete task
    assert tpl["task"]["id"] is None
    assert tpl["state"] in EXPECTED_STATES


def _run_status(harness_dir: Path):
    return subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "harness_status.py"),
            "--harness-dir",
            str(harness_dir),
        ],
        capture_output=True,
        text=True,
    )


def test_harness_status_reads_persisted_state(tmp_path):
    import yaml

    task = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "current-task.yaml")
        .read_text()
    )
    task["task"]["id"] = "TASK-009"
    task["task"]["title"] = "Persisted recovery check"
    task["state"] = "VERIFYING"
    (tmp_path / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = _run_status(tmp_path)

    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "TASK-009" in out
    assert "VERIFYING" in out


def test_harness_status_fails_on_missing_task_file(tmp_path):
    result = _run_status(tmp_path)
    assert result.returncode == 2


def test_harness_status_rejects_illegal_persisted_state(tmp_path):
    import yaml

    task = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "current-task.yaml")
        .read_text()
    )
    task["state"] = "NOT_A_STATE"
    (tmp_path / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = _run_status(tmp_path)
    assert result.returncode == 2


def test_harness_status_rejects_done_without_converged(tmp_path):
    """DONE reachable in file but only legally via CONVERGED -> DONE; a task
    written directly as DONE without gate pass must be flagged invalid."""
    import yaml

    task = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "current-task.yaml")
        .read_text()
    )
    task["state"] = "DONE"
    task["gate"]["status"] = "unknown"  # no gate PASS recorded
    (tmp_path / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = _run_status(tmp_path)
    assert result.returncode == 2


def test_harness_status_accepts_done_after_gate_pass(tmp_path):
    import yaml

    task = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "current-task.yaml")
        .read_text()
    )
    task["state"] = "DONE"
    task["gate"]["status"] = "PASS"
    (tmp_path / "current-task.yaml").write_text(yaml.safe_dump(task))

    result = _run_status(tmp_path)
    assert result.returncode == 0, result.stderr

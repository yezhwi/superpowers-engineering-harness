"""Milestone 5: Convergence rule tests.

Deterministic core of the convergence skill (doc section 24):
- PASS:  GATING -> CONVERGED -> DONE is the only path to DONE.
- Continue: GATING -> BLOCKED, BLOCKED -> IMPLEMENTING/REPRODUCING.
- Escalate: BLOCKED -> ESCALATED; ESCALATED must NOT loop back to work states
  silently; max_iterations surfaced by harness_status.py.
- Gate bypass: no state except CONVERGED reaches DONE.
"""

from importlib import resources
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from state_machine import legal_targets, require_legal  # noqa: E402
from state_machine import InvalidTransition, is_legal  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# 1. PASS path -----------------------------------------------------------------


def test_gating_to_converged_legal():
    assert is_legal("GATING", "CONVERGED")


def test_converged_to_done_legal():
    assert is_legal("CONVERGED", "DONE")


def test_done_only_from_converged():
    for state in (
        "CREATED",
        "SPECIFYING",
        "PLANNED",
        "IMPLEMENTING",
        "VERIFYING",
        "REVIEWING",
        "REPRODUCING",
        "FIXING",
        "GATING",
        "BLOCKED",
        "ESCALATED",
    ):
        assert not is_legal(state, "DONE"), state
    assert legal_targets("DONE") == set()  # terminal


def test_converged_is_terminal_except_done():
    assert legal_targets("CONVERGED") == {"DONE"}


# 2. Continue path ---------------------------------------------------------------


def test_gating_to_blocked_legal():
    assert is_legal("GATING", "BLOCKED")


@pytest.mark.parametrize("target", ["IMPLEMENTING", "REPRODUCING", "ESCALATED"])
def test_blocked_resume_targets_legal(target):
    assert target in legal_targets("BLOCKED")


def test_blocked_cannot_go_directly_to_converged():
    assert not is_legal("BLOCKED", "CONVERGED")
    assert not is_legal("BLOCKED", "DONE")


# 3. Escalate path --------------------------------------------------------------


def test_blocked_to_escalated_legal():
    require_legal("BLOCKED", "ESCALATED")


@pytest.mark.parametrize("target", ["IMPLEMENTING", "VERIFYING", "CONVERGED", "DONE"])
def test_escalated_does_not_silently_resume(target):
    assert not is_legal("ESCALATED", target)


def test_escalation_reason_codes():
    codes = {
        "SPEC_AMBIGUITY",
        "ARCHITECTURE_DEFECT",
        "REPEATED_REGRESSION",
        "UNSTABLE_TEST",
        "REVIEW_DISAGREEMENT",
        "MAX_ITERATIONS",
    }
    skill = (REPO / "skills" / "convergence" / "SKILL.md").read_text()
    for code in codes:
        assert code in skill, f"missing reason code {code}"


# 4. validate_state.py CLI ---------------------------------------------------------


def _validate(current, target):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "validate_state.py"), current, target],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def test_validate_cli_pass_path():
    result = _validate("GATING", "CONVERGED")
    assert result.returncode == 0
    assert "OK" in result.stdout


def test_validate_cli_rejects_bypass():
    result = _validate("IMPLEMENTING", "DONE")
    assert result.returncode == 1
    assert "INVALID TRANSITION" in result.stdout + result.stderr


# 5. harness_status surfaces iteration budget --------------------------------------


def _status(harness_dir: Path):
    return subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "harness_status.py"),
            "--harness-dir",
            str(harness_dir),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
    )


def make_task(tmp_path: Path, **overrides) -> Path:
    task = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "current-task.yaml")
        .read_text()
    )
    task.update(overrides)
    h = tmp_path / ".harness"
    h.mkdir(parents=True)
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    return h


def test_status_shows_iteration_budget(tmp_path):
    h = make_task(tmp_path, state="GATING", iteration=3, max_iterations=5)
    result = _status(h)
    assert result.returncode == 0
    assert "Iteration    3 / 5" in result.stdout


def test_status_rejects_unknown_state(tmp_path):
    h = make_task(tmp_path, state="NOT_A_STATE")
    result = _status(h)
    assert result.returncode == 2


def test_status_invalid_when_empty_yaml(tmp_path):
    h = tmp_path / ".harness"
    h.mkdir(parents=True)
    (h / "current-task.yaml").write_text("")
    result = _status(h)
    assert result.returncode == 2
    assert "INVALID_HARNESS_STATE" in result.stderr

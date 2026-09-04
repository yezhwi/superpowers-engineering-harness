"""Review outcomes route only through deterministic control-plane command."""

from importlib import resources

import pytest
import yaml

from harness.quality_gate import InvalidHarnessState, validate_schema
from test_cli_task_recovery import make_repo, run_cli, set_task_state


def test_task_schema_rejects_invalid_persisted_review_reason(tmp_path):
    """Break caught: direct YAML review facts bypass runtime reason-code validation."""
    task = yaml.safe_load(
        resources.files("harness")
        .joinpath("templates", "current-task.yaml")
        .read_text()
    )
    task["review"] = {
        "outcome": "VERIFICATION_GAP",
        "reason_code": "tests",
        "message": "forged",
        "finding_ids": [],
    }

    with pytest.raises(InvalidHarnessState, match="review"):
        validate_schema(task, "task.schema.json", tmp_path / "current-task.yaml")


def test_verification_gap_routes_reviewing_to_verifying(tmp_path):
    """Break caught: missing-test review result forces fake implementation work."""
    repo = make_repo(tmp_path)
    set_task_state(repo, "REVIEWING")

    result = run_cli(
        repo,
        "review",
        "outcome",
        "VERIFICATION_GAP",
        "--reason-code",
        "TEST_COVERAGE_INSUFFICIENT",
    )

    assert result.returncode == 0, result.stderr
    assert "REVIEWING -> VERIFYING" in result.stdout


def test_invalid_review_reason_code_is_rejected_without_transition(tmp_path):
    """Break caught: arbitrary prose becomes a machine-meaningful review reason."""
    repo = make_repo(tmp_path)
    set_task_state(repo, "REVIEWING")

    result = run_cli(
        repo, "review", "outcome", "VERIFICATION_GAP", "--reason-code", "tests"
    )

    assert result.returncode == 2
    assert (
        yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["state"]
        == "REVIEWING"
    )


def test_defect_requires_existing_nonterminal_finding(tmp_path):
    """Break caught: reviewer declares defect without entering Finding lifecycle."""
    repo = make_repo(tmp_path)
    set_task_state(repo, "REVIEWING")

    missing = run_cli(
        repo,
        "review",
        "outcome",
        "DEFECT",
        "--reason-code",
        "LOGIC_ERROR",
        "--finding",
        "FND-404",
    )

    assert missing.returncode == 2
    assert (
        yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["state"]
        == "REVIEWING"
    )


def test_defect_routes_to_reproducing_with_open_finding(tmp_path):
    """Break caught: valid defect outcome skips mandatory reproduction phase."""
    repo = make_repo(tmp_path)
    set_task_state(repo, "REVIEWING")
    (repo / ".harness/findings/FND-001.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "FND-001",
                "kind": "failure_scenario",
                "target": "REQ-001",
                "scenario": "reproduces",
                "severity": "major",
                "status": "PROPOSED",
            }
        )
    )

    result = run_cli(
        repo,
        "review",
        "outcome",
        "DEFECT",
        "--reason-code",
        "LOGIC_ERROR",
        "--finding",
        "FND-001",
    )

    assert result.returncode == 0, result.stderr
    assert (
        yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["state"]
        == "REPRODUCING"
    )


def test_defect_rejects_terminal_finding(tmp_path):
    """Break caught: closed Finding is reused to bypass a new defect lifecycle."""
    repo = make_repo(tmp_path)
    set_task_state(repo, "REVIEWING")
    (repo / ".harness/findings/FND-001.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "FND-001",
                "kind": "failure_scenario",
                "target": "REQ-001",
                "scenario": "closed",
                "severity": "major",
                "status": "REJECTED",
                "attempts": ["not reproducible"],
                "rejection_reason": "not a defect",
            }
        )
    )

    result = run_cli(
        repo,
        "review",
        "outcome",
        "DEFECT",
        "--reason-code",
        "LOGIC_ERROR",
        "--finding",
        "FND-001",
    )

    assert result.returncode == 2


def test_pass_review_outcome_maps_invalid_gate_state_to_exit_2(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "REVIEWING")
    import subprocess

    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    (repo / ".harness/requirements.yaml").write_text("{bad yaml")

    result = run_cli(repo, "review", "outcome", "PASS", "--reason-code", "REVIEW_CLEAN")

    assert result.returncode == 2
    assert "GATE_PREFLIGHT_INVALID" in result.stderr
    assert "Traceback" not in result.stderr


def test_generic_transition_cannot_bypass_review_outcome(tmp_path):
    """Break caught: agent labels a review result by directly choosing target state."""
    repo = make_repo(tmp_path)
    set_task_state(repo, "REVIEWING")

    result = run_cli(repo, "transition", "GATING")

    assert result.returncode == 1
    assert "REVIEW_OUTCOME_REQUIRED" in result.stderr

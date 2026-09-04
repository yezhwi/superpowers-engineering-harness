"""Test Plan entry Gate integration tests."""

import subprocess
import sys
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parent.parent
SAFE = {
    "scope": "low",
    "contract": "none",
    "data": "none",
    "authorization": "none",
    "security": "none",
    "concurrency": "none",
    "deployment": "none",
}


def cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def standard_repo_in_state(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    dimensions = {**SAFE, "scope": "high", "contract": "high"}
    flags = [
        value
        for name, setting in dimensions.items()
        for value in (f"--{name}", setting)
    ]
    assert cli(tmp_path, "task", "classify", "--level", "Q2", *flags).returncode == 0
    task_path = tmp_path / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-004"
    task["state"] = "PLANNED"
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    return tmp_path


def write_minimal_decision(repo: Path):
    decision = {
        "version": 1,
        "task": "TASK-004",
        "checks": {
            "existence": {"checked": True, "result": "required"},
            "reuse": {"checked": True, "result": "none"},
            "stdlib": {"checked": True, "result": "none"},
            "native": {"checked": True, "result": "none"},
            "existing_dependency": {"checked": True, "result": "none"},
            "minimum_local_implementation": {"checked": True, "result": "required"},
        },
        "decision": {"approach": "local_implementation", "rationale": "required"},
    }
    path = repo / ".harness/evidence/minimal-implementation.yaml"
    path.write_text(yaml.safe_dump(decision, sort_keys=False))


def write_documents(repo: Path, *, valid: bool):
    strategies = ["unit"] if valid else []
    requirement = {
        "id": "REQ-001",
        "statement": "feature works",
        "priority": "must",
        "status": "pending",
        "test_plan": {
            "strategies": strategies,
            "cases": [
                {
                    "id": "TC-001",
                    "type": "happy_path",
                    "strategy": "unit",
                    "description": "works",
                }
            ],
        },
    }
    invariant = {
        "id": "INV-001",
        "statement": "safe",
        "category": "correctness",
        "severity": "critical",
        "status": "pending",
        "verification": [],
        "test_plan": {
            "strategies": ["integration"],
            "cases": [
                {
                    "id": "TC-002",
                    "type": "invariant",
                    "strategy": "integration",
                    "description": "holds",
                }
            ],
        },
    }
    (repo / ".harness/requirements.yaml").write_text(
        yaml.safe_dump({"requirements": [requirement]})
    )
    (repo / ".harness/invariants.yaml").write_text(
        yaml.safe_dump({"invariants": [invariant]})
    )


def test_standard_planned_to_implementing_rejects_invalid_test_plan(tmp_path):
    """Break caught: STANDARD task starts implementation without a strategy."""
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=False)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "TEST_PLAN_BLOCKED" in result.stderr
    assert (
        yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["state"]
        == "PLANNED"
    )


def test_standard_planned_to_implementing_accepts_valid_test_plan(tmp_path):
    """Break caught: valid plan cannot reach implementation after minimal check."""
    repo = standard_repo_in_state(tmp_path)
    write_minimal_decision(repo)
    write_documents(repo, valid=True)

    result = cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 0, result.stderr


def test_fast_classified_to_implementing_does_not_load_test_plan(tmp_path):
    """Break caught: v0.2.4 adds STANDARD ceremony to FAST path."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert cli(tmp_path, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    flags = [
        value for name, setting in SAFE.items() for value in (f"--{name}", setting)
    ]
    assert cli(tmp_path, "task", "classify", "--level", "Q1", *flags).returncode == 0

    result = cli(tmp_path, "transition", "IMPLEMENTING")

    assert result.returncode == 0, result.stderr

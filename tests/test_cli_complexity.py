"""v0.2 CLI behavior for minimal and complexity checks."""

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args], cwd=cwd,
        capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def make_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    assert run_cli(tmp_path, "init").returncode == 0
    return tmp_path


def set_task_state(repo: Path, state: str) -> None:
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["task"]["id"] = "TASK-004"
    task["state"] = state
    path.write_text(yaml.safe_dump(task, sort_keys=False))


def minimal_decision() -> dict:
    return {
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
        "decision": {"approach": "local_implementation", "rationale": "needed"},
    }


def write_decision(path: Path, task: str = "TASK-004") -> None:
    document = minimal_decision()
    document["task"] = task
    path.write_text(yaml.safe_dump(document, sort_keys=False))


def test_check_minimal_persists_valid_document(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "PLANNED")
    source = tmp_path / "decision.yaml"
    write_decision(source)

    result = run_cli(repo, "check", "minimal", "--file", str(source))

    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / ".harness/evidence/minimal-implementation.yaml").is_file()


def test_planned_to_implementing_requires_minimal_evidence(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "PLANNED")

    result = run_cli(repo, "transition", "IMPLEMENTING")

    assert result.returncode == 1
    assert "MINIMAL_IMPLEMENTATION_REQUIRED" in result.stderr


def test_check_minimal_rejects_task_mismatch(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "PLANNED")
    source = tmp_path / "decision.yaml"
    write_decision(source, task="TASK-999")

    result = run_cli(repo, "check", "minimal", "--file", str(source))

    assert result.returncode == 2
    assert "task mismatch" in result.stderr

"""CLI contract for audited stale-task recovery."""

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


def set_task_state(repo: Path, state: str, task_id: str = "TASK-004") -> None:
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["task"]["id"] = task_id
    task["state"] = state
    path.write_text(yaml.safe_dump(task, sort_keys=False))


def test_task_recover_requires_reason(tmp_path):
    repo = make_repo(tmp_path)

    result = run_cli(repo, "task", "recover", "TASK-005")

    assert result.returncode == 2
    assert "--reason" in result.stderr


def test_task_recover_rejects_invalid_id(tmp_path):
    repo = make_repo(tmp_path)
    before = (repo / ".harness/current-task.yaml").read_text()

    result = run_cli(repo, "task", "recover", "bad", "--reason", "stale")

    assert result.returncode == 2
    assert "INVALID TASK ID" in result.stderr
    assert (repo / ".harness/current-task.yaml").read_text() == before


def test_task_recover_rejects_terminal_task_without_mutation(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "DONE")
    before = (repo / ".harness/current-task.yaml").read_text()

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")

    assert result.returncode == 1
    assert "requires active task" in result.stderr
    assert (repo / ".harness/current-task.yaml").read_text() == before
    assert not list((repo / ".harness/history").glob("TASK-004-*"))

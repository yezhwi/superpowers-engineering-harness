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


def test_task_recover_archives_artifacts_and_creates_fresh_task(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "IMPLEMENTING")
    findings = repo / ".harness/findings"
    evidence = repo / ".harness/evidence"
    (findings / "FND-001.yaml").write_text("id: FND-001\n")
    (evidence / "unit.json").write_text("{}")

    result = run_cli(
        repo, "task", "recover", "TASK-005", "--title", "Wheel isolation",
        "--reason", "stale task",
    )

    assert result.returncode == 0, result.stderr
    archive = next((repo / ".harness/history").glob("TASK-004-*"))
    audit = yaml.safe_load((archive / "recovery.yaml").read_text())
    assert audit["previous_state"] == "IMPLEMENTING"
    assert audit["reason"] == "stale task"
    assert audit["replacement_task_id"] == "TASK-005"
    assert (archive / "findings/FND-001.yaml").is_file()
    assert (archive / "evidence/unit.json").is_file()
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["task"]["id"] == "TASK-005"
    assert task["task"]["title"] == "Wheel isolation"
    assert task["state"] == "CREATED"
    assert list(findings.iterdir()) == []
    assert list(evidence.iterdir()) == []


def test_task_new_still_rejects_active_task(tmp_path):
    repo = make_repo(tmp_path)

    result = run_cli(repo, "task", "new", "TASK-005")

    assert result.returncode == 1
    assert "DONE or ESCALATED" in result.stderr

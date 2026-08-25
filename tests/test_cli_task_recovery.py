"""CLI contract for audited stale-task recovery."""

import subprocess
import sys
from pathlib import Path


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

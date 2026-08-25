"""Impact full-suite recommendation is advisory; execution still requires authorization."""

import subprocess
import sys
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parent.parent


def cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args], cwd=cwd,
        capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    cli(path, "init")
    harness_dir = path / ".harness"
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    task["task"]["id"] = "TASK-010"
    task["state"] = "IMPLEMENTING"
    (harness_dir / "current-task.yaml").write_text(yaml.safe_dump(task))
    cli(path, "impact", "add-test", "tests/test_x.py::test_x")


def test_recommended_full_suite_does_not_block_verifying(tmp_path):
    setup(tmp_path)
    cli(tmp_path, "impact", "require-full-suite", "--reason", "state boundary")

    result = cli(tmp_path, "transition", "VERIFYING")

    assert result.returncode == 0, result.stderr


def test_full_suite_execution_still_requires_authorization(tmp_path):
    setup(tmp_path)

    result = cli(tmp_path, "evidence", "--type", "unit_test", "--scope", "full_suite", "--command", "true")

    assert result.returncode == 2
    assert "FULL_SUITE_AUTHORIZATION_REQUIRED" in result.stderr

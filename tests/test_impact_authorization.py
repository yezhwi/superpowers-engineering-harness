"""Related evidence is only execution scope."""

import subprocess
import sys
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parent.parent


def cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    cli(path, "init")
    harness_dir = path / ".harness"
    assert cli(path, 'task', 'migrate-id', 'TASK-010').returncode == 0
    target = path / 'tests/test_x.py'
    target.parent.mkdir()
    target.write_text('def test_x():\n    pass\n')
    subprocess.run(['git', 'add', '-A'], cwd=path, check=True)
    subprocess.run(['git', 'commit', '-qm', 'fixture baseline'], cwd=path, check=True)
    classified = cli(path, 'task', 'classify', '--level', 'Q1', '--scope', 'low', '--contract', 'none',
                     '--data', 'none', '--authorization', 'none', '--security', 'none', '--concurrency', 'none', '--deployment', 'none')
    assert classified.returncode == 0, classified.stderr
    task = yaml.safe_load((harness_dir / "current-task.yaml").read_text())
    task["state"] = "IMPLEMENTING"
    (harness_dir / "current-task.yaml").write_text(yaml.safe_dump(task))
    result = cli(path, "impact", "add-test", "tests/test_x.py::test_x")
    assert result.returncode == 0, result.stderr


def test_related_required_tests_do_not_block_verifying(tmp_path):
    setup(tmp_path)

    result = cli(tmp_path, "transition", "VERIFYING")

    assert result.returncode == 0, result.stderr


def test_full_suite_execution_is_forbidden(tmp_path):
    setup(tmp_path)

    result = cli(
        tmp_path,
        "evidence",
        "--type",
        "unit_test",
        "--scope",
        "full_suite",
        "--command",
        "true",
    )

    assert result.returncode == 2
    assert "FULL_SUITE_FORBIDDEN" in result.stderr

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


def setup(repo):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    assert cli(repo, "init").returncode == 0
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)


def task(repo):
    return yaml.safe_load((repo / ".harness/current-task.yaml").read_text())


def test_authorizations_are_independent(tmp_path):
    setup(tmp_path)
    result = cli(tmp_path, "authorize", "commit")

    assert result.returncode == 0
    assert task(tmp_path)["authorizations"]["commit"]["granted"] is True
    assert task(tmp_path)["authorizations"]["push"]["granted"] is False


def test_full_suite_requires_its_own_authorization(tmp_path):
    setup(tmp_path)
    assert cli(tmp_path, "authorize", "commit").returncode == 0

    result = cli(tmp_path, "evidence", "--type", "unit_test",
                 "--scope", "full_suite", "--command", "true")

    assert result.returncode == 2
    assert "FULL_SUITE_AUTHORIZATION_REQUIRED" in result.stderr

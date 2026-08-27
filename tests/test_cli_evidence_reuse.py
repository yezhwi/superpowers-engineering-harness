import subprocess
import sys
from pathlib import Path

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


def test_cli_passes_reuse_flag_to_collector(tmp_path):
    setup(tmp_path)
    first = cli(tmp_path, "evidence", "--type", "build", "--command", "true")
    second = cli(tmp_path, "evidence", "--type", "build", "--command", "true", "--reuse-if-valid")
    assert first.returncode == second.returncode == 0
    assert "EVIDENCE_REUSED: build.json" in second.stdout

import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args], cwd=cwd,
        capture_output=True, text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    assert cli(repo, "init").returncode == 0
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    task_path = repo / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-042"
    task_path.write_text(yaml.safe_dump(task))


def proposal_args() -> tuple[str, ...]:
    return (
        "--topic", "cache", "--question", "Which cache?",
        "--context", "Redis exists", "--option", "local=local cache",
        "--option", "redis=shared cache", "--recommend", "redis",
        "--reason", "existing infrastructure", "--tradeoff", "network dependency",
        "--scope", "src/service/**", "--constraint", "no new cache",
    )


def test_decision_propose_and_accept_persist_user_choice(tmp_path):
    """Break caught: CLI accepts a choice without durable decision artifact."""
    setup(tmp_path)

    proposed = cli(tmp_path, "decision", "propose", *proposal_args())
    accepted = cli(tmp_path, "decision", "accept", "DEC-001", "--option", "redis")

    assert proposed.returncode == 0, proposed.stderr
    assert accepted.returncode == 0, accepted.stderr
    record = yaml.safe_load((tmp_path / ".harness" / "decisions" / "DEC-001.yaml").read_text())
    assert record["selected"]["option"] == "redis"
    assert record["selected"]["source"] == "accepted_recommendation"

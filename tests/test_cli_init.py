"""M3: harness init CLI (guide sections 6, 14-16, 27)."""

import subprocess
import yaml
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def make_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_success_returns_zero(tmp_path):
    repo = make_repo(tmp_path)
    result = run_cli(repo, "init")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / ".harness" / "current-task.yaml").exists()


def test_prints_created_files(tmp_path):
    repo = make_repo(tmp_path)
    result = run_cli(repo, "init")
    assert "current-task.yaml" in result.stdout
    assert "created" in result.stdout.lower()


def test_reports_existing_harness(tmp_path):
    repo = make_repo(tmp_path)
    run_cli(repo, "init")
    result = run_cli(repo, "init")
    assert result.returncode == 0
    assert "skipped" in result.stdout.lower()


def test_init_writes_explicit_off_policy_and_empty_module_scope(tmp_path):
    repo = make_repo(tmp_path)

    assert run_cli(repo, "init").returncode == 0

    gate = yaml.safe_load((repo / ".harness/gate.yaml").read_text())
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert gate["gate"]["architecture"] == {"mode": "off"}
    assert task["scope"]["modules"] == []


def test_init_does_not_overwrite_existing_architecture_policy_or_scope(tmp_path):
    repo = make_repo(tmp_path)
    assert run_cli(repo, "init").returncode == 0
    gate_path = repo / ".harness/gate.yaml"
    task_path = repo / ".harness/current-task.yaml"
    gate = yaml.safe_load(gate_path.read_text())
    task = yaml.safe_load(task_path.read_text())
    gate["gate"]["architecture"] = {"mode": "required"}
    task["scope"]["modules"] = ["app"]
    gate_path.write_text(yaml.safe_dump(gate, sort_keys=False))
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    before_gate = gate_path.read_bytes()
    before_task = task_path.read_bytes()

    assert run_cli(repo, "init").returncode == 0

    assert gate_path.read_bytes() == before_gate
    assert task_path.read_bytes() == before_task


def test_outside_repo_returns_one(tmp_path):
    result = run_cli(tmp_path, "init")
    assert result.returncode == 1
    assert "git repository" in result.stdout + result.stderr
    # must not auto git-init
    assert not (tmp_path / ".git").exists()


def test_mr_describe_assesses_current_state_not_stale_gate(tmp_path):
    repo = make_repo(tmp_path)
    run_cli(repo, "init")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["gate"] = {
        "status": "PASS",
        "blocked_by": [],
        "quality": {"status": "PASS"},
        "release_readiness": {"status": "READY", "reasons": []},
    }
    path.write_text(yaml.safe_dump(task))
    result = run_cli(repo, "mr", "describe")
    assert result.returncode == 0
    assert "Quality Gate: BLOCKED" in result.stdout
    assert "Ready for MR" not in result.stdout


def test_unknown_command_is_invalid_usage(tmp_path):
    repo = make_repo(tmp_path)
    result = run_cli(repo, "destroy-everything")
    assert result.returncode == 2


def test_no_flags_added_v01(tmp_path):
    # guide section 6: --force and friends must NOT exist
    repo = make_repo(tmp_path)
    result = run_cli(repo, "init", "--force")
    assert result.returncode != 0

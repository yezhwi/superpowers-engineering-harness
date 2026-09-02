"""v0.2 CLI behavior for minimal and complexity checks."""

import json
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


def test_verifying_to_reviewing_requires_complexity_review(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "VERIFYING")

    result = run_cli(repo, "transition", "REVIEWING")

    assert result.returncode == 1
    assert "COMPLEXITY_REVIEW_REQUIRED" in result.stderr


def test_review_complexity_writes_findings_and_metadata(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("base")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base", "-q"], cwd=repo, check=True)
    set_task_state(repo, "VERIFYING")
    review = {
        "task": "TASK-004", "base": "HEAD~1", "head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip(),
        "findings": [{
            "id": "CPLX-001", "category": "complexity", "type": "reuse",
            "severity": "high", "status": "open", "location": {"file": "x.py"},
            "summary": "duplicate", "reason": "existing x", "evidence": {"candidate": "x"},
            "recommendation": "reuse x",
        }],
    }
    source = tmp_path / "review.yaml"
    source.write_text(yaml.safe_dump(review, sort_keys=False))

    result = run_cli(repo, "review", "complexity", "--base", "HEAD", "--file", str(source))

    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / ".harness/findings/CPLX-001.yaml").is_file()
    assert (repo / ".harness/evidence/complexity-review.json").is_file()


def test_complexity_scope_excludes_protected_dirty_path(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "owned.py").write_text("base\n"); (repo / "protected.py").write_text("base\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True); subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "VERIFYING")
    task_path = repo / ".harness/current-task.yaml"; task = yaml.safe_load(task_path.read_text())
    task["scope"] = {"owned_paths": ["owned.py"], "protected_user_paths": ["protected.py"]}; task_path.write_text(yaml.safe_dump(task))
    (repo / "protected.py").write_text("user edit\n")
    source = tmp_path / "review.yaml"; source.write_text(yaml.safe_dump({"task": "TASK-004", "findings": [], "review_scope": {"files": ["owned.py"]}}))
    result = run_cli(repo, "review", "complexity", "--base", "HEAD", "--file", str(source))
    assert result.returncode == 0, result.stderr


def test_complexity_scope_excludes_unadopted_dirty_file(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "tracked.py").write_text("base\n")
    subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "VERIFYING")
    (repo / "dirty.py").write_text("changed\n")
    source = tmp_path / "review.yaml"
    source.write_text(yaml.safe_dump({
        "task": "TASK-004", "findings": [],
        "review_scope": {"files": []},
    }))

    result = run_cli(repo, "review", "complexity", "--base", "HEAD", "--file", str(source))

    assert result.returncode == 0, result.stderr


def test_legacy_complexity_input_warns_before_v04_rejection(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "tracked.py").write_text("base\n")
    subprocess.run(["git", "add", "tracked.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "VERIFYING")
    source = tmp_path / "review.yaml"; source.write_text(yaml.safe_dump({"task": "TASK-004", "findings": []}))
    result = run_cli(repo, "review", "complexity", "--base", "HEAD", "--file", str(source))
    assert result.returncode == 0, result.stderr
    assert "COMPLEXITY_CHECKS_DEPRECATED" in result.stderr


def test_complexity_defaults_to_task_baseline_for_clean_committed_change(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
    set_task_state(repo, "DONE")
    assert run_cli(repo, "task", "new", "TASK-005").returncode == 0
    (repo / "service.py").write_text("enabled = True\n")
    subprocess.run(["git", "add", "service.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "service"], cwd=repo, check=True)
    set_task_state(repo, "VERIFYING")
    task_path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-005"
    task_path.write_text(yaml.safe_dump(task))
    source = tmp_path / "review.yaml"
    source.write_text(yaml.safe_dump({"task": "TASK-005", "findings": []}))

    result = run_cli(repo, "review", "complexity", "--file", str(source))

    assert result.returncode == 0, result.stderr
    metadata = json.loads((repo / ".harness/evidence/complexity-review.json").read_text())
    assert "service.py" not in metadata["review_scope"]["files"]


def test_check_minimal_rejects_task_mismatch(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "PLANNED")
    source = tmp_path / "decision.yaml"
    write_decision(source, task="TASK-999")

    result = run_cli(repo, "check", "minimal", "--file", str(source))

    assert result.returncode == 2
    assert "task mismatch" in result.stderr

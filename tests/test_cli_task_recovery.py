"""CLI contract for audited stale-task recovery."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
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
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    findings = repo / ".harness/findings"
    evidence = repo / ".harness/evidence"
    (findings / "FND-001.yaml").write_text("id: FND-001\n")
    (evidence / "unit.json").write_text("{}")

    result = run_cli(
        repo,
        "task",
        "recover",
        "TASK-005",
        "--title",
        "Wheel isolation",
        "--reason",
        "stale task",
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


def test_task_recover_preserves_required_mode_and_architecture_artifact(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    harness = repo / ".harness"
    seal = {
        "version": 2,
        "task_id": "TASK-004",
        "contract_hash": "sha256:" + "0" * 64,
        "architecture_mode": "required",
        "architecture_fingerprint": "sha256:" + "1" * 64,
        "declared_modules": ["app"],
        "decision_selections": {},
        "boundary_refs": {"interface": [], "permission": [], "persistence": []},
        "frozen_at": "2026-10-01T00:00:00Z",
    }
    (harness / "alignment-freeze.yaml").write_text(yaml.safe_dump(seal, sort_keys=False))
    architecture = harness / "architecture.yaml"
    architecture.write_text("version: 1\n")
    before = architecture.read_bytes()

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")

    assert result.returncode == 0, result.stderr
    gate = yaml.safe_load((harness / "gate.yaml").read_text())
    assert gate["gate"]["architecture"]["mode"] == "required"
    assert architecture.read_bytes() == before
    archive = next((harness / "history").glob("TASK-004-*"))
    assert (archive / "alignment-freeze.yaml").is_file()


def test_task_recover_malformed_seal_is_atomic(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    harness = repo / ".harness"
    (harness / "alignment-freeze.yaml").write_text("version: 2\n")
    before = {path.relative_to(harness).as_posix(): path.read_bytes() for path in harness.rglob("*") if path.is_file()}

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")

    assert result.returncode == 2
    assert {path.relative_to(harness).as_posix(): path.read_bytes() for path in harness.rglob("*") if path.is_file()} == before


def test_task_recover_archives_and_clears_stale_alignment(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    alignment = repo / ".harness/alignment.yaml"
    alignment.write_text("version: 1\ntask_id: TASK-004\n")

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "stale")

    assert result.returncode == 0, result.stderr
    archive = next((repo / ".harness/history").glob("TASK-004-*"))
    assert (archive / "alignment.yaml").is_file()
    assert not alignment.exists()


def test_resume_routes_typed_evidence_blocker_to_verifying(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "BLOCKED")
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["gate"] = {
        "status": "BLOCKED",
        "blocked_by": [
            {
                "code": "EVIDENCE_WORKSPACE_STALE",
                "category": "verification",
                "message": "unit-test evidence stale",
                "source": "unit_test",
                "finding_id": None,
                "recover_to": "VERIFYING",
            }
        ],
    }
    path.write_text(yaml.safe_dump(task))

    result = run_cli(repo, "resume")

    assert result.returncode == 0, result.stderr
    assert "BLOCKED -> VERIFYING" in result.stdout
    assert yaml.safe_load(path.read_text())["state"] == "VERIFYING"


@pytest.mark.parametrize(
    ("code", "category", "target"),
    [
        ("DIAGNOSABILITY_REVIEW_MISSING", "verification", "VERIFYING"),
        ("OBSERVABILITY_CONTRACT_INVALID", "implementation", "IMPLEMENTING"),
    ],
)
def test_resume_routes_diagnosability_blocker(code, category, target, tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "BLOCKED")
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["gate"] = {
        "status": "BLOCKED",
        "blocked_by": [
            {
                "code": code,
                "category": category,
                "message": "diagnosability blocked",
                "recover_to": "tampered",
            }
        ],
    }
    path.write_text(yaml.safe_dump(task))

    result = run_cli(repo, "resume")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(path.read_text())["state"] == target


def test_resume_ignores_tampered_persisted_recovery_target(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "BLOCKED")
    path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["gate"] = {
        "status": "BLOCKED",
        "blocked_by": [
            {
                "code": "EVIDENCE_MISSING",
                "category": "verification",
                "message": "missing build evidence",
                "source": "build",
                "requirement_id": None,
                "invariant_id": None,
                "finding_id": None,
                "recover_to": "IMPLEMENTING",
            }
        ],
    }
    path.write_text(yaml.safe_dump(task))

    result = run_cli(repo, "resume")

    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(path.read_text())["state"] == "VERIFYING"


@pytest.mark.parametrize(
    "target", ["IMPLEMENTING", "VERIFYING", "REPRODUCING", "ESCALATED"]
)
def test_transition_cannot_bypass_resume_for_blocked_recovery(tmp_path, target):
    repo = make_repo(tmp_path)
    set_task_state(repo, "BLOCKED")

    result = run_cli(repo, "transition", target)

    assert result.returncode == 1
    assert "RESUME_REQUIRED" in result.stderr


def test_task_recover_records_current_git_head_as_complexity_baseline(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "IMPLEMENTING")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = run_cli(repo, "task", "recover", "TASK-005", "--reason", "restart")

    assert result.returncode == 0, result.stderr
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["git"]["head"] == head
    assert task["git"]["base_commit"] == head
    assert task["git"]["head_at_start"] == head
    assert task["git"]["base_ref"]


def test_task_new_without_git_head_fails_without_mutation(tmp_path):
    repo = make_repo(tmp_path)
    set_task_state(repo, "DONE")
    task_path = repo / ".harness/current-task.yaml"
    before = task_path.read_bytes()

    result = run_cli(repo, "task", "new", "TASK-005")

    assert result.returncode == 2
    assert "TASK_GIT_BASELINE_REQUIRED" in result.stderr
    assert task_path.read_bytes() == before
    history = repo / ".harness/history"
    assert not history.exists() or not list(history.iterdir())


def test_task_new_records_current_git_head_as_complexity_baseline(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    set_task_state(repo, "DONE")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    result = run_cli(repo, "task", "new", "TASK-005")

    assert result.returncode == 0, result.stderr
    assert (
        yaml.safe_load((repo / ".harness/current-task.yaml").read_text())["git"][
            "base_commit"
        ]
        == head
    )


def test_task_new_still_rejects_active_task(tmp_path):
    repo = make_repo(tmp_path)

    result = run_cli(repo, "task", "new", "TASK-005")

    assert result.returncode == 1
    assert "DONE or ESCALATED" in result.stderr

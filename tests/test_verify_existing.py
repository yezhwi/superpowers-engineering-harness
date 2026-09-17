"""Existing-implementation verification does not fake RED or close GitLab."""

import json
import subprocess
import sys
from pathlib import Path

import yaml

from evidence_factory import write_evidence
from test_risk import CLASSIFY_FLAGS, SAFE

REPO = Path(__file__).resolve().parent.parent


def run_cli(cwd: Path, *args: str):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def classified_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "Test")
    assert run_cli(tmp_path, "init").returncode == 0
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('done')\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "implemented")
    assert run_cli(tmp_path, "task", "classify", "--level", "Q1", *CLASSIFY_FLAGS).returncode == 0
    task_path = tmp_path / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["scope"]["owned_paths"] = ["src/app.py"]
    task_path.write_text(yaml.safe_dump(task, sort_keys=False))
    return tmp_path


def write_green(repo: Path) -> None:
    from harness.workspace import git_head, snapshot

    fingerprint = snapshot(repo).fingerprint
    head = git_head(repo)
    evidence = repo / ".harness/evidence"
    evidence.mkdir(exist_ok=True)
    for name, evidence_type in (
        ("build.json", "build"),
        ("fast-green-unit-test.json", "unit_test"),
    ):
        (evidence / name).write_text(
            json.dumps(
                {
                    "type": evidence_type,
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "command": "true",
                    "exit_code": 0,
                    "commit": head,
                    "workspace_fingerprint": fingerprint,
                    "workspace_fingerprint_after": fingerprint,
                }
            )
        )


def test_verify_existing_records_already_satisfied_without_red(tmp_path):
    repo = classified_repo(tmp_path)
    write_green(repo)

    result = run_cli(
        repo,
        "task",
        "verify-existing",
        "--reference",
        "HEAD",
        "--reason",
        "work item already implemented",
        "--conclusion",
        "already_satisfied",
    )

    assert result.returncode == 0, result.stderr
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["state"] == "CLASSIFIED"
    assert task["verification_mode"] == "existing_implementation"
    assert task["existing_verification"]["conclusion"] == "already_satisfied"
    assert task["existing_verification"]["reference"]
    assert task["existing_verification"]["introducing_commit"]
    assert (repo / ".harness/findings").exists()
    assert list((repo / ".harness/findings").glob("*.yaml")) == []


def test_verify_existing_blocks_without_green_evidence(tmp_path):
    repo = classified_repo(tmp_path)

    result = run_cli(
        repo,
        "task",
        "verify-existing",
        "--reference",
        "HEAD",
        "--reason",
        "already on main",
        "--conclusion",
        "already_satisfied",
    )

    assert result.returncode != 0
    assert "EXISTING_VERIFICATION_GREEN_MISSING" in result.stderr
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert "verification_mode" not in task


def test_verify_existing_blocks_unaccepted_target_diff(tmp_path):
    repo = classified_repo(tmp_path)
    write_green(repo)
    (repo / "src/app.py").write_text("print('local change')\n")

    result = run_cli(
        repo,
        "task",
        "verify-existing",
        "--reference",
        "HEAD",
        "--reason",
        "already on main",
        "--conclusion",
        "already_satisfied",
    )

    assert result.returncode != 0
    assert "EXISTING_VERIFICATION_DIFF_UNACCEPTED" in result.stderr


def test_verify_existing_accepts_diff_with_explicit_reason(tmp_path):
    repo = classified_repo(tmp_path)
    git(repo, "branch", "baseline")
    (repo / "src/app.py").write_text("print('later')\n")
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-qm", "later")
    write_green(repo)

    result = run_cli(
        repo,
        "task",
        "verify-existing",
        "--reference",
        "baseline",
        "--reason",
        "already on main",
        "--conclusion",
        "already_satisfied",
        "--accept-diff",
        "cosmetic local only",
    )

    assert result.returncode == 0, result.stderr
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["existing_verification"]["accepted_diff_reason"] == "cosmetic local only"


def test_verify_existing_requires_reproduction_does_not_persist_mode(tmp_path):
    repo = classified_repo(tmp_path)
    write_green(repo)

    result = run_cli(
        repo,
        "task",
        "verify-existing",
        "--reference",
        "HEAD",
        "--reason",
        "ui still wrong",
        "--conclusion",
        "requires_reproduction",
    )

    assert result.returncode != 0
    assert "EXISTING_VERIFICATION_REQUIRES_REPRODUCTION" in result.stderr
    task = yaml.safe_load((repo / ".harness/current-task.yaml").read_text())
    assert task["state"] == "CLASSIFIED"
    assert "verification_mode" not in task


def test_verify_existing_source_does_not_write_gitlab():
    from harness import controlplane, existing_verification

    for path in (
        Path(existing_verification.__file__),
        Path(controlplane.__file__),
    ):
        text = path.read_text().lower()
        assert "gitlab.com" not in text
        assert "glab " not in text
        assert "issues.close" not in text


def test_fast_gate_skips_red_for_existing_implementation(tmp_path):
    from harness.quality_gate import run_gate
    from harness.workspace import protected_paths_fingerprint
    from test_quality_gate import HEAD, make_harness

    h = make_harness(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["git"]["base_commit"] = HEAD
    (h / "risk-boundaries.yaml").write_text(
        "boundaries:\n  q2: [never/**]\n  q3: [never/**]\n"
    )
    task["risk"] = {
        "level": "Q1",
        "profile": "FAST",
        "dimensions": {name: "none" if name != "scope" else "low" for name in SAFE},
        "escalation_history": [],
        "user_changes": {"paths": [], "fingerprint": protected_paths_fingerprint(())},
    }
    task["verification_mode"] = "existing_implementation"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    (h / "requirements.yaml").unlink()
    (h / "invariants.yaml").unlink()
    write_evidence(REPO, h, "unit_test", name="fast-green-unit-test.json")

    status, blockers = run_gate(h)

    assert status == "PASS", blockers
    assert blockers == []

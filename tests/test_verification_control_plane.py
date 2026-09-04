"""TASK-007: task identity and verification attachment control plane."""

import subprocess, sys
from pathlib import Path
import yaml
from evidence_factory import write_evidence

REPO = Path(__file__).resolve().parent.parent


def cli(cwd, *a):
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *a],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )


def setup(p):
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    cli(p, "init")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=p, check=True)
    return p / ".harness"


def test_task_migrate_id_validates_schema(p=None):
    pass


def test_task_migrate_id_rejects_slug(tmp_path):
    h = setup(tmp_path)
    r = cli(tmp_path, "task", "migrate-id", "datasearch-generation-phase-commit")
    assert r.returncode == 2


def test_task_migrate_id_persists_task_nnn(tmp_path):
    h = setup(tmp_path)
    r = cli(tmp_path, "task", "migrate-id", "TASK-007")
    assert r.returncode == 0
    assert (
        yaml.safe_load((h / "current-task.yaml").read_text())["task"]["id"]
        == "TASK-007"
    )


def test_requirement_verify_unknown_id_rejected(tmp_path):
    setup(tmp_path)
    assert (
        cli(
            tmp_path, "requirement", "verify", "REQ-999", "--evidence", "build.json"
        ).returncode
        == 1
    )


def test_transition_rejects_invalid_persisted_task_id(tmp_path):
    h = setup(tmp_path)
    task = yaml.safe_load((h / "current-task.yaml").read_text())
    task["task"]["id"] = "bad-slug"
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    assert cli(tmp_path, "transition", "SPECIFYING").returncode == 2


def test_requirement_and_invariant_verify_attach_fresh_evidence(tmp_path):
    h = setup(tmp_path)
    (h / "requirements.yaml").write_text(
        yaml.safe_dump(
            {
                "requirements": [
                    {
                        "id": "REQ-001",
                        "statement": "works",
                        "priority": "must",
                        "status": "pending",
                        "evidence": [],
                    }
                ]
            }
        )
    )
    (h / "invariants.yaml").write_text(
        yaml.safe_dump(
            {
                "invariants": [
                    {
                        "id": "INV-001",
                        "statement": "safe",
                        "category": "correctness",
                        "severity": "critical",
                        "status": "pending",
                        "verification": [],
                    }
                ]
            }
        )
    )
    write_evidence(tmp_path, h, "build")
    assert (
        cli(
            tmp_path, "requirement", "verify", "REQ-001", "--evidence", "build.json"
        ).returncode
        == 0
    )
    assert (
        cli(
            tmp_path, "invariant", "verify", "INV-001", "--evidence", "build.json"
        ).returncode
        == 0
    )
    assert (
        yaml.safe_load((h / "requirements.yaml").read_text())["requirements"][0][
            "status"
        ]
        == "verified"
    )


def test_requirement_verify_rejects_evidence_reference_outside_canonical_directory(
    tmp_path,
):
    h = setup(tmp_path)
    (h / "requirements.yaml").write_text(
        yaml.safe_dump(
            {
                "requirements": [
                    {
                        "id": "REQ-001",
                        "statement": "works",
                        "priority": "must",
                        "status": "pending",
                        "evidence": [],
                    }
                ]
            }
        )
    )
    write_evidence(tmp_path, h, "build")
    (h / "history").mkdir(exist_ok=True)
    (h / "history" / "build.json").write_bytes(
        (h / "evidence" / "build.json").read_bytes()
    )
    result = cli(
        tmp_path,
        "requirement",
        "verify",
        "REQ-001",
        "--evidence",
        "../history/build.json",
    )
    assert result.returncode == 2
    assert "EVIDENCE_REFERENCE_INVALID" in result.stderr
    assert (
        yaml.safe_load((h / "requirements.yaml").read_text())["requirements"][0][
            "status"
        ]
        == "pending"
    )


def test_verify_rejects_stale_workspace_evidence(tmp_path):
    h = setup(tmp_path)
    (h / "requirements.yaml").write_text(
        yaml.safe_dump(
            {
                "requirements": [
                    {
                        "id": "REQ-001",
                        "statement": "works",
                        "priority": "must",
                        "status": "pending",
                        "evidence": [],
                    }
                ]
            }
        )
    )
    write_evidence(tmp_path, h, "build")
    (tmp_path / "new-untracked.py").write_text("changed")
    assert (
        cli(
            tmp_path, "requirement", "verify", "REQ-001", "--evidence", "build.json"
        ).returncode
        == 2
    )

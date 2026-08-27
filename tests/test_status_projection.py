"""Evidence classifications shared by status and quality gate."""

import json
import subprocess
from pathlib import Path

from test_cli_task_recovery import make_repo, run_cli


def fresh_record() -> dict:
    return {
        "type": "build",
        "timestamp": "2026-08-27T00:00:00+00:00",
        "command": "python -m pytest",
        "exit_code": 0,
        "commit": "a" * 40,
        "workspace_fingerprint": "sha256:" + "b" * 64,
        "workspace_fingerprint_after": "sha256:" + "b" * 64,
    }


def test_projection_marks_current_successful_evidence_fresh(tmp_path: Path):
    """Break caught: status calls a different freshness rule than Gate."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    path = tmp_path / "build.json"
    path.write_text(json.dumps(fresh_record()))

    projection = project_evidence(
        path, current_head="a" * 40, current_workspace="sha256:" + "b" * 64,
        expected_success=True,
    )

    assert projection.status is EvidenceStatus.FRESH
    assert projection.code is None
    assert projection.record["command"] == "python -m pytest"


def test_projection_marks_current_failed_command_failed(tmp_path: Path):
    """Break caught: nonzero current evidence is displayed as stale or fresh."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    record = fresh_record()
    record["exit_code"] = 1
    path = tmp_path / "build.json"
    path.write_text(json.dumps(record))

    projection = project_evidence(
        path, current_head="a" * 40, current_workspace="sha256:" + "b" * 64,
        expected_success=True,
    )

    assert projection.status is EvidenceStatus.FAILED
    assert projection.code == "EVIDENCE_RESULT_MISMATCH"


def test_projection_marks_head_mismatch_stale(tmp_path: Path):
    """Break caught: stale HEAD-bound proof can look valid before Gate."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    path = tmp_path / "build.json"
    path.write_text(json.dumps(fresh_record()))

    projection = project_evidence(
        path, current_head="c" * 40, current_workspace="sha256:" + "b" * 64,
        expected_success=True,
    )

    assert projection.status is EvidenceStatus.STALE
    assert projection.code == "EVIDENCE_HEAD_MISMATCH"


def test_status_projects_stale_evidence_without_mutating_task(tmp_path: Path):
    """Break caught: status trusts persisted verification flags or writes a new truth."""
    repo = make_repo(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "app.py").write_text("base\n")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    record = fresh_record()
    record["commit"] = head
    (repo / ".harness/evidence/build.json").write_text(json.dumps(record))
    task_path = repo / ".harness/current-task.yaml"
    before = task_path.read_bytes()
    (repo / "app.py").write_text("changed\n")

    result = run_cli(repo, "status")

    assert result.returncode == 0, result.stderr
    assert "build" in result.stdout.lower()
    assert "STALE" in result.stdout
    assert task_path.read_bytes() == before


def test_projection_marks_missing_evidence_missing(tmp_path: Path):
    """Break caught: absent required evidence is indistinguishable from invalid data."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    projection = project_evidence(
        tmp_path / "missing.json", current_head="a" * 40,
        current_workspace="sha256:" + "b" * 64, expected_success=True,
    )

    assert projection.status is EvidenceStatus.MISSING
    assert projection.code == "EVIDENCE_MISSING"

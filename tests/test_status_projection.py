"""Evidence classifications shared by status and quality gate."""

import json
import subprocess
from pathlib import Path

import yaml

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


def test_status_renders_active_decision_summary(tmp_path: Path):
    """Break caught: resumed session cannot see accepted user constraint."""
    from harness.decision import accept, propose
    from harness.init import init_harness

    repo = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    assert init_harness(repo).harness_dir == repo / ".harness"
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    task_path = repo / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-042"
    task_path.write_text(yaml.safe_dump(task))
    proposed = propose(
        repo / ".harness",
        {
            "topic": "pagination",
            "question": "Which pagination?",
            "context": ["clients exist"],
            "options": [{"id": "cursor", "description": "cursor"}],
            "recommendation": {
                "option": "cursor",
                "reasons": ["stable"],
                "tradeoffs": [],
            },
            "scope": [],
            "constraints": [],
        },
    )
    accept(repo / ".harness", proposed["id"], "cursor", "accepted_recommendation")

    result = run_cli(repo, "status")

    assert result.returncode == 0, result.stderr
    assert "DEC-001 pagination = cursor" in result.stdout


def test_status_renders_public_interface_summary(tmp_path: Path):
    """Break caught: resumed session hides declared public compatibility impact."""
    from harness.init import init_harness

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    init_harness(tmp_path)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    (tmp_path / ".harness" / "impact.yaml").write_text(
        yaml.safe_dump(
            {
                "impact": {
                    "changed": [],
                    "direct_dependents": [],
                    "contracts": [],
                    "interfaces": [
                        {
                            "id": "INT-001",
                            "kind": "cli",
                            "visibility": "external",
                            "consumers": ["agent"],
                            "compatibility": "compatible",
                            "affected_contracts": [],
                            "contract_id": "INT-001",
                        }
                    ],
                    "risks": [],
                    "required_tests": [],
                    "full_suite": {"recommended": False, "reason": None},
                }
            }
        )
    )

    result = run_cli(tmp_path, "status")

    assert "Interfaces" in result.stdout
    assert "public changes: 1" in result.stdout
    assert "compatibility: compatible" in result.stdout


def test_projection_marks_current_successful_evidence_fresh(tmp_path: Path):
    """Break caught: status calls a different freshness rule than Gate."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    path = tmp_path / "build.json"
    path.write_text(json.dumps(fresh_record()))

    projection = project_evidence(
        path,
        current_head="a" * 40,
        current_workspace="sha256:" + "b" * 64,
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
        path,
        current_head="a" * 40,
        current_workspace="sha256:" + "b" * 64,
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
        path,
        current_head="c" * 40,
        current_workspace="sha256:" + "b" * 64,
        expected_success=True,
    )

    assert projection.status is EvidenceStatus.STALE
    assert projection.code == "EVIDENCE_HEAD_MISMATCH"


def test_status_projects_stale_evidence_without_mutating_task(tmp_path: Path):
    """Break caught: status trusts persisted verification flags or writes a new truth."""
    repo = make_repo(tmp_path)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "app.py").write_text("base\n")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
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


def test_status_rejects_done_with_cached_pass_and_open_canonical_finding(tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    task_path = repo / ".harness/current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["state"] = "DONE"
    task["gate"] = {"status": "PASS", "blocked_by": []}
    task_path.write_text(yaml.safe_dump(task))
    (repo / ".harness/findings/FND-001.yaml").write_text(yaml.safe_dump({
        "id": "FND-001", "kind": "failure_scenario", "target": "REQ-001",
        "scenario": "open canonical defect", "severity": "major", "status": "PROPOSED",
    }))

    result = run_cli(repo, "status")

    assert result.returncode == 2
    assert "DONE without current gate PASS" in result.stderr


def test_projection_marks_missing_evidence_missing(tmp_path: Path):
    """Break caught: absent required evidence is indistinguishable from invalid data."""
    from harness.evidence_validator import EvidenceStatus, project_evidence

    projection = project_evidence(
        tmp_path / "missing.json",
        current_head="a" * 40,
        current_workspace="sha256:" + "b" * 64,
        expected_success=True,
    )

    assert projection.status is EvidenceStatus.MISSING
    assert projection.code == "EVIDENCE_MISSING"

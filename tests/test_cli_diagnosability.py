"""Diagnosability review CLI integration tests."""

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
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    assert run_cli(repo, "init").returncode == 0
    harness = repo / ".harness"
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    task["task"]["id"] = "TASK-028"
    task["state"] = "REVIEWING"
    task["git"]["base_commit"] = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    (harness / "current-task.yaml").write_text(yaml.safe_dump(task, sort_keys=False))
    (harness / "observability.yaml").write_text(yaml.safe_dump({
        "version": 1, "required": True,
        "applicability": {"reasons": ["external_dependency"], "inspected_paths": ["src/orders/refund.py"]},
        "business_keys": ["order_id"],
        "failure_boundaries": ["payment_refund"],
        "external_dependencies": [{"name": "payment_gateway", "operations": ["refund"], "required_context": ["order_id", "dependency"]}],
    }, sort_keys=False))
    return repo


def review_source(tmp_path: Path, *, external_result: str = "pass") -> Path:
    source = tmp_path / "review.yaml"
    source.write_text(yaml.safe_dump({
        "task": "TASK-028",
        "contract_required": True,
        "finding_ids": [],
        "direct_dependencies": [],
        "review_scope": {"files": ["src/orders/refund.py"]},
        "checks": {
            "business_keys": "pass",
            "external_failure_context": external_result,
            "state_transitions": "not_applicable",
            "caller_rejections": "not_applicable",
            "sensitive_data": "not_applicable",
            "duplicate_exception_logging": "pass",
            "low_value_logging": "pass",
        },
    }, sort_keys=False))
    return source


def test_review_diagnosability_writes_current_scope_evidence(tmp_path):
    repo = make_repo(tmp_path)

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(review_source(tmp_path)))

    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads((repo / ".harness/evidence/diagnosability-review.json").read_text())
    assert record["type"] == "diagnosability_review"
    assert record["checks"]["business_keys"] == "pass"
    assert record["review_scope"]["files"] == ["src/orders/refund.py"]


def diag_proposal(local_id="missing-external-context"):
    return {
        "local_id": local_id,
        "target": "REQ-001",
        "severity": "major",
        "reason_code": "DIAG_MISSING_EXTERNAL_FAILURE_CONTEXT",
        "location": {"file": "src/orders/refund.py"},
        "required_checks": ["external_failure_context"],
    }


def test_review_publishes_diag_proposal_as_allocated_finding(tmp_path):
    repo = make_repo(tmp_path)
    source = review_source(tmp_path, external_result="fail")
    document = yaml.safe_load(source.read_text())
    document["proposals"] = [diag_proposal()]
    source.write_text(yaml.safe_dump(document))

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(source))

    assert result.returncode == 0, result.stderr
    finding = yaml.safe_load((repo / ".harness/findings/FND-001.yaml").read_text())
    assert finding["category"] == "diagnosability"
    record = yaml.safe_load((repo / ".harness/evidence/diagnosability-review.json").read_text())
    assert record["finding_mapping"] == {"missing-external-context": "FND-001"}


def test_review_rejects_duplicate_diag_proposal_with_stable_code(tmp_path):
    repo = make_repo(tmp_path)
    source = review_source(tmp_path, external_result="fail")
    document = yaml.safe_load(source.read_text())
    document["proposals"] = [diag_proposal()]
    source.write_text(yaml.safe_dump(document))
    assert run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(source)).returncode == 0
    (repo / ".harness/evidence/diagnosability-review.json").unlink()
    document["proposals"] = [diag_proposal("same-problem-again")]
    source.write_text(yaml.safe_dump(document))

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(source))

    assert result.returncode == 2
    assert "DIAG_PROPOSAL_DUPLICATE" in result.stderr


def test_review_rejects_invalid_diag_proposal_with_stable_code(tmp_path):
    repo = make_repo(tmp_path,)
    source = review_source(tmp_path, external_result="fail")
    document = yaml.safe_load(source.read_text())
    proposal = diag_proposal()
    del proposal["target"]
    document["proposals"] = [proposal]
    source.write_text(yaml.safe_dump(document))

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(source))

    assert result.returncode == 2
    assert "DIAG_PROPOSAL_FIELD_REQUIRED" in result.stderr


def test_review_rejects_invalid_proposed_finding_without_partial_artifacts(tmp_path):
    repo = make_repo(tmp_path)
    source = review_source(tmp_path, external_result="fail")
    document = yaml.safe_load(source.read_text())
    document["finding_ids"] = ["FND-010"]
    document["findings"] = [{"id": "FND-010"}]
    source.write_text(yaml.safe_dump(document))

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(source))

    assert result.returncode == 2
    assert not (repo / ".harness/findings/FND-010.yaml").exists()
    assert not (repo / ".harness/evidence/diagnosability-review.json").exists()


def test_review_diagnosability_rejects_missing_finding_for_failed_check(tmp_path):
    repo = make_repo(tmp_path)

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(review_source(tmp_path, external_result="fail")))

    assert result.returncode == 2
    assert "DIAG_FINDING_REQUIRED" in result.stderr
    assert not (repo / ".harness/evidence/diagnosability-review.json").exists()

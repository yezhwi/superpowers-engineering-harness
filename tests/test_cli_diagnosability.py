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


def test_review_diagnosability_rejects_missing_finding_for_failed_check(tmp_path):
    repo = make_repo(tmp_path)

    result = run_cli(repo, "review", "diagnosability", "--base", "HEAD", "--file", str(review_source(tmp_path, external_result="fail")))

    assert result.returncode == 2
    assert "DIAG_FINDING_REQUIRED" in result.stderr
    assert not (repo / ".harness/evidence/diagnosability-review.json").exists()

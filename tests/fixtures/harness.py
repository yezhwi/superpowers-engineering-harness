"""Reusable schema-valid Harness lifecycle fixtures."""

import json
from importlib import resources
from pathlib import Path

import yaml
from evidence_factory import write_complexity_review, write_evidence


def make_harness(tmp_path: Path, *, state: str = "GATING", risk: str = "Q2", task_type: str = "feature", observability: str = "required") -> Path:
    h = tmp_path / ".harness"
    h.mkdir(parents=True)
    task = yaml.safe_load(resources.files("harness").joinpath("templates", "current-task.yaml").read_text())
    task["state"] = state
    task["task"]["type"] = task_type
    task["risk"] = {"level": risk}
    (h / "current-task.yaml").write_text(yaml.safe_dump(task))
    (h / "gate.yaml").write_text(resources.files("harness").joinpath("templates", "gate.yaml").read_text())
    required = observability == "required"
    contract = {"version": 1, "required": required, "applicability": {"reasons": ["security"] if required else ["not_assessed"], "inspected_paths": ["src/example.py"]}}
    if task_type == "bugfix":
        contract["bug_fix"] = {"observability_gap": False, "basis": "fixture baseline"}
    if required:
        contract.update({"business_keys": ["task_id"], "failure_boundaries": ["review"], "critical_events": ["published"]})
    (h / "observability.yaml").write_text(yaml.safe_dump(contract))
    (h / "findings").mkdir()
    return h


def make_complete_harness(repo: Path, tmp_path: Path, *, state: str = "GATING") -> Path:
    """Complete Gate-ready fixture for lifecycle tests."""
    h = make_harness(tmp_path, state=state)
    requirements = {"requirements": [{"id": "REQ-001", "statement": "works", "priority": "must", "status": "verified", "evidence": ["build.json"], "test_plan": {"strategies": ["manual"], "cases": [{"id": "TC-700", "type": "happy_path", "strategy": "manual", "description": "fixture requirement", "tests": []}]}}]}
    invariants = {"invariants": [{"id": "INV-001", "statement": "safe", "category": "correctness", "severity": "critical", "status": "verified", "verification": ["build.json"], "test_plan": {"strategies": ["manual"], "cases": [{"id": "TC-701", "type": "invariant", "strategy": "manual", "description": "fixture invariant", "tests": []}]}}]}
    (h / "requirements.yaml").write_text(yaml.safe_dump(requirements))
    (h / "invariants.yaml").write_text(yaml.safe_dump(invariants))
    evidence = h / "evidence"
    evidence.mkdir()
    for kind in ("build", "unit_test"):
        write_evidence(repo, h, kind)
    write_complexity_review(repo, h)
    build = json.loads((evidence / "build.json").read_text())
    build["covered_test_cases"] = ["TC-700", "TC-701"]
    (evidence / "build.json").write_text(json.dumps(build))
    return h

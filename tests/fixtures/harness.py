"""Reusable schema-valid Harness lifecycle fixtures."""

import json
from importlib import resources
from pathlib import Path

import yaml


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

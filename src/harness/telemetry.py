"""Local deterministic Harness telemetry."""
import json
from pathlib import Path


def update_telemetry(harness_dir: Path, task: dict) -> dict:
    risk = task.get("risk") or {}
    budget = task.get("budget") or {}
    data = {
        "task_id": (task.get("task") or {}).get("id"),
        "risk_level": risk.get("level"),
        "workflow_profile": risk.get("profile"),
        "evidence": {key: budget.get(key, 0) for key in ("test_runs", "build_runs", "retry_runs")},
        "elapsed_seconds": None,
        "gate_result": (task.get("gate") or {}).get("status"),
        "rework_count": task.get("iteration"),
        "risk_escalations": len(risk.get("escalation_history") or []),
        "token_estimate": None,
    }
    path = harness_dir / "telemetry.json"
    path.write_text(json.dumps(data, indent=2))
    return data

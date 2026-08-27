"""Local deterministic Harness telemetry."""
import datetime
import json
from pathlib import Path


def _elapsed_seconds(created_at: str | None, now: str) -> int | None:
    if not created_at:
        return None
    try:
        return max(0, int((datetime.datetime.fromisoformat(now) - datetime.datetime.fromisoformat(created_at)).total_seconds()))
    except ValueError:
        return None


def update_telemetry(harness_dir: Path, task: dict, *, now: str | None = None) -> dict:
    now = now or datetime.datetime.now(datetime.timezone.utc).isoformat()
    path = harness_dir / "telemetry.json"
    try:
        previous = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        previous = {}
    risk = task.get("risk") or {}
    budget = task.get("budget") or {}
    data = {
        "task_id": (task.get("task") or {}).get("id"),
        "risk_level": risk.get("level"),
        "workflow_profile": risk.get("profile"),
        "evidence": {key: budget.get(key, 0) for key in ("test_runs", "build_runs", "retry_runs")},
        "elapsed_seconds": _elapsed_seconds((task.get("timestamps") or {}).get("created_at"), now),
        "harness_command_calls": int(previous.get("harness_command_calls", 0)) + 1,
        "gate_result": (task.get("gate") or {}).get("status"),
        "rework_count": task.get("iteration"),
        "risk_escalations": len(risk.get("escalation_history") or []),
        "agent": {"tool_calls": None, "search_rounds": None, "token_estimate": None},
        "token_estimate": None,
    }
    path.write_text(json.dumps(data, indent=2))
    return data

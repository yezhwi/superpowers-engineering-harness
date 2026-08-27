import json

from harness.telemetry import update_telemetry


def test_telemetry_contains_only_local_command_facts(tmp_path):
    task = {
        "task": {"id": "TASK-020"}, "risk": {"level": "Q1", "profile": "FAST", "escalation_history": []},
        "budget": {"test_runs": 2, "build_runs": 1, "retry_runs": 0},
        "gate": {"status": "PASS"}, "iteration": 1,
        "timestamps": {"created_at": None},
    }
    data = update_telemetry(tmp_path, task)
    assert data["evidence"] == {"test_runs": 2, "build_runs": 1, "retry_runs": 0}
    assert data["token_estimate"] is None
    assert "command" not in json.dumps(data)
    assert json.loads((tmp_path / "telemetry.json").read_text()) == data

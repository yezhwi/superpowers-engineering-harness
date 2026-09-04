import json

from harness.telemetry import update_telemetry


def test_telemetry_measures_elapsed_and_harness_calls_without_agent_guessing(tmp_path):
    task = {
        "task": {"id": "TASK-021"},
        "risk": {},
        "budget": {},
        "gate": {},
        "iteration": 0,
        "timestamps": {"created_at": "2026-01-01T00:00:00+00:00"},
    }
    data = update_telemetry(tmp_path, task, now="2026-01-01T00:00:10+00:00")
    assert data["elapsed_seconds"] == 10
    assert data["harness_command_calls"] == 1
    assert data["agent"] == {
        "tool_calls": None,
        "search_rounds": None,
        "token_estimate": None,
    }


def test_telemetry_contains_only_local_command_facts(tmp_path):
    task = {
        "task": {"id": "TASK-020"},
        "risk": {"level": "Q1", "profile": "FAST", "escalation_history": []},
        "budget": {"test_runs": 2, "build_runs": 1, "retry_runs": 0},
        "gate": {"status": "PASS"},
        "iteration": 1,
        "timestamps": {"created_at": None},
    }
    data = update_telemetry(tmp_path, task)
    assert data["evidence"] == {"test_runs": 2, "build_runs": 1, "retry_runs": 0}
    assert data["token_estimate"] is None
    assert '"command"' not in json.dumps(data)
    assert json.loads((tmp_path / "telemetry.json").read_text()) == data

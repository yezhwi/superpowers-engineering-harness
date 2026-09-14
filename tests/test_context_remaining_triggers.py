"""Remaining automatic triggers preserve risk floors and event idempotency."""

import json

import pytest
import test_context_builder
import yaml
from evidence_factory import write_evidence
from test_context_builder import write_yaml

from harness.context.store import generate_context

harness = test_context_builder.harness


def test_failed_tests_outside_working_set_expand_once(harness):
    path = write_evidence(harness.parent, harness, "unit_test", exit_code=1)
    record = json.loads(path.read_text())
    record["covered_tests"] = ["tests/outside.py::test_failure"]
    path.write_text(json.dumps(record))
    document = generate_context(harness)
    (event,) = document["expansions"]
    assert event["trigger"] == "TEST_FAILURE_OUTSIDE_WORKING_SET"
    assert document["policy"] == "BOUNDED"
    assert generate_context(harness)["expansions"] == [event]
    with (harness / "requirements.yaml").open("a") as stream:
        stream.write("\n# unrelated edit\n")
    assert generate_context(harness)["expansions"] == [event]


def test_failure_omitted_only_in_compact_can_record_event(harness):
    required = {
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "Optional test",
                "priority": "should",
                "status": "pending",
                "test_plan": {
                    "strategies": ["unit"],
                    "cases": [
                        {
                            "id": "TC-001",
                            "type": "negative",
                            "strategy": "unit",
                            "description": "external",
                            "tests": ["tests/outside.py::test_failure"],
                        }
                    ],
                },
            }
        ]
    }
    write_yaml(harness / "requirements.yaml", required)
    write_yaml(
        harness / "impact.yaml", {"impact": {"changed": [], "required_tests": []}}
    )
    path = write_evidence(harness.parent, harness, "unit_test", exit_code=1)
    record = json.loads(path.read_text())
    record["covered_tests"] = ["tests/outside.py::test_failure"]
    path.write_text(json.dumps(record))
    document = generate_context(harness, mode="compact")
    assert document["expansions"][0]["trigger"] == "TEST_FAILURE_OUTSIDE_WORKING_SET"


def test_passing_evidence_does_not_trigger_expansion(harness):
    path = write_evidence(harness.parent, harness, "unit_test")
    record = json.loads(path.read_text())
    record["covered_tests"] = ["tests/outside.py::test_ok"]
    path.write_text(json.dumps(record))
    assert generate_context(harness)["expansions"] == []


@pytest.mark.parametrize(
    "history",
    [
        [{"from": "Q2", "to": "Q1", "reason": "decrease"}],
        [{"from": [], "to": "Q2", "reason": "invalid"}],
        [{"from": "Q1", "to": "Q2", "reason": " "}],
    ],
)
def test_invalid_risk_history_fails_without_writes(harness, history):
    from harness.context.model import ContextBuildError

    path = harness / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["risk"].update(level="Q2", profile="STANDARD", escalation_history=history)
    write_yaml(path, task)
    before = path.read_bytes()
    with pytest.raises(ContextBuildError, match="CONTEXT_POLICY_MISMATCH"):
        generate_context(harness)
    assert path.read_bytes() == before
    assert not (harness / "context/expansions.yaml").exists()


def test_risk_escalation_event_follows_risk_without_extra_policy_step(harness):
    path = harness / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["risk"].update(
        level="Q2",
        profile="STANDARD",
        escalation_history=[
            {"from": "Q1", "to": "Q2", "reason": "Cross-module change"}
        ],
    )
    write_yaml(path, task)
    document = generate_context(harness)
    (event,) = document["expansions"]
    assert event["trigger"] == "RISK_ESCALATED"
    assert event["from"] == "LOCAL"
    assert event["to"] == "BOUNDED"
    assert document["policy"] == document["base_policy"] == "BOUNDED"
    assert generate_context(harness)["expansions"] == [event]
    updated = yaml.safe_load(path.read_text())
    assert updated["risk"] == task["risk"]
    assert updated["budget"]["context_expansions"] == 1

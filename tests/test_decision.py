from pathlib import Path

import pytest
import yaml

from harness.init import init_harness


def setup_harness(path: Path) -> Path:
    init_harness(path)
    task_path = path / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-042"
    task_path.write_text(yaml.safe_dump(task))
    return path / ".harness"


def proposal(*, topic: str = "cache", recommendation: str = "redis") -> dict:
    return {
        "topic": topic,
        "question": "Which cache should be used?",
        "context": ["repository has Redis client"],
        "options": [
            {"id": "local", "description": "in-process cache"},
            {"id": "redis", "description": "shared cache"},
        ],
        "recommendation": {
            "option": recommendation,
            "reasons": ["existing infrastructure"],
            "tradeoffs": ["network dependency"],
        },
        "scope": ["src/service/**"],
        "constraints": ["do not add another cache"],
    }


def test_accept_persists_recommended_option_without_mutating_proposal(tmp_path):
    """Break caught: accepted choice missing from persisted decision record."""
    from harness.decision import accept, load_decision, propose

    harness_dir = setup_harness(tmp_path)
    created = propose(harness_dir, proposal())

    accepted = accept(harness_dir, created["id"], "redis", "accepted_recommendation")

    assert accepted["status"] == "ACCEPTED"
    assert accepted["selected"] == {
        "option": "redis",
        "source": "accepted_recommendation",
        "decided_by": "user",
    }
    assert load_decision(harness_dir, created["id"])["selected"] == accepted["selected"]


def test_user_override_preserves_selected_option_distinct_from_recommendation(tmp_path):
    """Break caught: user override silently replaced by agent recommendation."""
    from harness.decision import accept, propose

    created = propose(setup_harness(tmp_path), proposal())

    accepted = accept(tmp_path / ".harness", created["id"], "local", "user_override")

    assert accepted["recommendation"]["option"] == "redis"
    assert accepted["selected"]["option"] == "local"
    assert accepted["selected"]["source"] == "user_override"


def test_supersede_proposal_keeps_original_active(tmp_path):
    """Break caught: replacement proposal prematurely changes accepted truth."""
    from harness.decision import accept, load_decision, propose, supersede

    harness_dir = setup_harness(tmp_path)
    original = propose(harness_dir, proposal())
    accept(harness_dir, original["id"], "redis", "accepted_recommendation")

    old, replacement = supersede(
        harness_dir, original["id"], proposal(topic="cache-v2", recommendation="local")
    )

    assert old["status"] == "ACCEPTED"
    assert old["selected"]["option"] == "redis"
    assert old["superseded_by"] is None
    assert replacement["status"] == "PROPOSED"
    assert replacement["supersedes"] == original["id"]
    assert load_decision(harness_dir, original["id"])["status"] == "ACCEPTED"


def test_accepted_supersede_replaces_original_decision(tmp_path):
    from harness.decision import accept, load_decision, propose, supersede

    harness_dir = setup_harness(tmp_path)
    original = propose(harness_dir, proposal())
    accept(harness_dir, original["id"], "redis", "accepted_recommendation")
    _, replacement = supersede(harness_dir, original["id"], proposal(topic="replacement"))

    accepted = accept(harness_dir, replacement["id"], "redis", "accepted_recommendation")

    assert accepted["status"] == "ACCEPTED"
    assert load_decision(harness_dir, original["id"])["status"] == "SUPERSEDED"
    assert load_decision(harness_dir, original["id"])["superseded_by"] == replacement["id"]


def test_supersede_publish_failure_preserves_accepted_original(tmp_path, monkeypatch):
    """Break caught: partial supersede leaves accepted decision chain broken."""
    from harness.decision import accept, load_decision, propose, supersede
    from harness.transaction import publish

    harness_dir = setup_harness(tmp_path)
    original = propose(harness_dir, proposal())
    accept(harness_dir, original["id"], "redis", "accepted_recommendation")

    def fail_publish(*args, **kwargs):
        raise OSError("injected publication failure")

    monkeypatch.setattr("harness.decision.publish", fail_publish, raising=False)
    _, replacement = supersede(harness_dir, original["id"], proposal(topic="replacement"))
    with pytest.raises(OSError, match="injected publication failure"):
        accept(harness_dir, replacement["id"], "redis", "accepted_recommendation")

    persisted = load_decision(harness_dir, original["id"])
    assert persisted["status"] == "ACCEPTED"
    assert persisted["superseded_by"] is None


def test_accept_rejects_wrong_selection_source(tmp_path):
    """Break caught: recommended choice can be falsely recorded as user override."""
    from harness.decision import DecisionError, accept, propose

    harness_dir = setup_harness(tmp_path)
    created = propose(harness_dir, proposal())

    with pytest.raises(DecisionError, match="DECISION_SELECTION_SOURCE_INVALID"):
        accept(harness_dir, created["id"], "redis", "user_override")


def test_decision_id_path_escape_rejected_before_lookup(tmp_path):
    from harness.decision import DecisionError, load_decision

    with pytest.raises(DecisionError, match="DECISION_ID_INVALID"):
        load_decision(setup_harness(tmp_path), "DEC-../../../escape")


def test_decision_id_requires_exact_pattern(tmp_path):
    from harness.decision import DecisionError, load_decision

    with pytest.raises(DecisionError, match="DECISION_ID_INVALID"):
        load_decision(setup_harness(tmp_path), "DEC-1.yaml")

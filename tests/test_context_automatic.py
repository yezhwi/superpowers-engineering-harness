"""Automatic expansions bind only trigger inputs, never their own output."""

import pytest
import test_context_builder
import yaml
from test_context_builder import write_yaml
from test_context_integrity import add_core_records

from harness.context.store import generate_context, load_context

harness = test_context_builder.harness


def outside_finding(root):
    add_core_records(root)
    # Isolate finding trigger from unrelated accepted decision.
    decision = next((root / "decisions").glob("*.yaml"))
    record = yaml.safe_load(decision.read_text())
    record["scope"] = ["src/local.py"]
    write_yaml(decision, record)
    path = root / "findings/FND-001.yaml"
    record = yaml.safe_load(path.read_text())
    record["location"] = {"file": "src/other.py"}
    write_yaml(path, record)


def test_finding_auto_expansion_is_fresh_and_deduplicated(harness):
    outside_finding(harness)
    document = generate_context(harness)
    assert document["policy"] == "BOUNDED"
    (event,) = document["expansions"]
    assert event["trigger"] == "FINDING_OUTSIDE_SCOPE"
    assert event["object_id"] == "FND-001"
    assert load_context(harness)[1]["freshness"]
    assert generate_context(harness)["expansions"] == [event]
    with (harness / "requirements.yaml").open("a") as stream:
        stream.write("\n# unrelated edit\n")
    assert generate_context(harness)["expansions"] == [event]
    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    assert task["budget"]["context_expansions"] == 1
    assert task["risk"]["level"] == "Q1"


def test_changed_trigger_basis_records_new_event(harness):
    outside_finding(harness)
    generate_context(harness)
    path = harness / "findings/FND-001.yaml"
    record = yaml.safe_load(path.read_text())
    record["location"]["file"] = "src/another.py"
    write_yaml(path, record)
    document = generate_context(harness)
    assert document["policy"] == "EXPANDED"
    assert len(document["expansions"]) == 2
    assert (
        document["expansions"][0]["source_hash"]
        != document["expansions"][1]["source_hash"]
    )


def test_accepted_decision_outside_scope_expands_once(harness):
    add_core_records(harness)
    document = generate_context(harness)
    (event,) = document["expansions"]
    assert event["trigger"] == "DECISION_OUTSIDE_SCOPE"
    assert document["policy"] == "BOUNDED"
    assert generate_context(harness)["expansions"] == [event]


def historical_accepted(decision_id, task_id, *, topic, scope):
    return {
        "id": decision_id,
        "task_id": task_id,
        "status": "ACCEPTED",
        "topic": topic,
        "question": f"HISTORICAL-BODY-{decision_id}",
        "context": ["old task"],
        "options": [{"id": "keep", "description": "keep"}],
        "recommendation": {
            "option": "keep",
            "reasons": ["done"],
            "tradeoffs": [],
        },
        "selected": {
            "option": "keep",
            "source": "accepted_recommendation",
            "decided_by": "user",
        },
        "decision_reason": ["user accepted current recommendation"],
        "rejection_reason": None,
        "scope": scope,
        "constraints": [],
        "created_at": "2026-01-01T00:00:00+00:00",
        "accepted_at": "2026-01-01T00:00:01+00:00",
        "rejected_at": None,
        "supersedes": None,
        "superseded_by": None,
    }


def test_other_task_accepted_decisions_do_not_enter_layer0_or_expand(harness):
    """Break caught: historical ACCEPTED decisions inflate compact and expansion."""
    add_core_records(harness)
    current = next((harness / "decisions").glob("*.yaml"))
    record = yaml.safe_load(current.read_text())
    record["scope"] = ["src/local.py"]
    write_yaml(current, record)
    for index in range(101, 106):
        write_yaml(
            harness / f"decisions/DEC-{index:03d}.yaml",
            historical_accepted(
                f"DEC-{index:03d}",
                "TASK-001",
                topic=f"old-{index}",
                scope=["src/unrelated.py"],
            ),
        )

    from harness import decision

    decision.reindex(harness)
    document = generate_context(harness, mode="compact")

    assert [item["id"] for item in document["control"]["decisions"]] == [record["id"]]
    assert document["expansions"] == []
    omitted_ids = {item["id"]: item["reason"] for item in document["omitted"]}
    assert omitted_ids["DEC-101"] == "different_task_not_referenced"
    dumped = yaml.safe_dump(document)
    assert "HISTORICAL-BODY-DEC-101" not in dumped
    assert "HISTORICAL-BODY-DEC-105" not in dumped


def test_context_loads_only_current_decision_body_from_index(harness, monkeypatch):
    from harness import decision

    add_core_records(harness)
    for index in range(101, 106):
        write_yaml(
            harness / f"decisions/DEC-{index:03d}.yaml",
            historical_accepted(
                f"DEC-{index:03d}", "TASK-001", topic=f"old-{index}", scope=[]
            ),
        )
    decision.reindex(harness)
    loaded = []
    original = decision.load_decision

    def count(path, decision_id):
        loaded.append(decision_id)
        return original(path, decision_id)

    monkeypatch.setattr(decision, "load_decision", count)
    generate_context(harness, mode="compact")

    assert loaded and set(loaded) == {"DEC-001"}


def test_explicit_cross_task_decision_is_layer2_ref_not_inlined(harness):
    add_core_records(harness)
    current_path = next((harness / "decisions").glob("*.yaml"))
    current = yaml.safe_load(current_path.read_text())
    current["scope"] = ["src/local.py"]
    current["supersedes"] = "DEC-200"
    write_yaml(current_path, current)
    write_yaml(
        harness / "decisions/DEC-200.yaml",
        historical_accepted(
            "DEC-200",
            "TASK-001",
            topic="old-cache",
            scope=["src/unrelated.py"],
        ),
    )

    from harness import decision

    decision.reindex(harness)
    document = generate_context(harness, mode="compact")

    assert [item["id"] for item in document["control"]["decisions"]] == [current["id"]]
    omitted = {item["id"]: item for item in document["omitted"] if item["id"] == "DEC-200"}
    assert omitted["DEC-200"]["reason"] == "cross_task_reference"
    assert "decisions/DEC-200.yaml" in omitted["DEC-200"]["ref"]
    assert omitted["DEC-200"]["sha256"].startswith("sha256:")
    assert "HISTORICAL-BODY-DEC-200" not in yaml.safe_dump(document["control"])
    assert document["expansions"] == []


def test_broken_cross_task_decision_ref_fails_closed(harness):
    add_core_records(harness)
    current_path = next((harness / "decisions").glob("*.yaml"))
    current = yaml.safe_load(current_path.read_text())
    current["scope"] = ["src/local.py"]
    current["supersedes"] = "DEC-999"
    write_yaml(current_path, current)

    from harness.context.model import ContextBuildError

    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        generate_context(harness, mode="compact")


def test_context_integrity_unproven_rejects_compact_without_expansion(harness):
    from harness.context.escalation import (
        AUTOMATIC_TRIGGERS,
        FAIL_CLOSED_TRIGGERS,
        REPORTED_TRIGGERS,
    )
    from harness.context.model import ContextBuildError
    from test_context_cli import run_cli

    assert FAIL_CLOSED_TRIGGERS == ("CONTEXT_INTEGRITY_UNPROVEN",)
    assert "CONTEXT_INTEGRITY_UNPROVEN" not in AUTOMATIC_TRIGGERS + REPORTED_TRIGGERS
    outside_finding(harness)
    write_yaml(harness / "requirements.yaml", {"requirements": "invalid"})
    before = (harness / "current-task.yaml").read_bytes()
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        generate_context(harness, mode="compact")
    result = run_cli(harness.parent, "--compact")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "CONTEXT_SCHEMA_INVALID" in result.stderr
    assert (harness / "current-task.yaml").read_bytes() == before
    assert not (harness / "context/expansions.yaml").exists()
    assert not (harness / "context/current.yaml").exists()


def test_two_concurrent_generators_record_one_automatic_event(harness):
    from concurrent.futures import ThreadPoolExecutor

    outside_finding(harness)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(generate_context, harness) for _ in range(2)]
        documents = [future.result(timeout=30) for future in futures]
    assert documents[0]["expansions"] == documents[1]["expansions"]
    assert len(documents[0]["expansions"]) == 1
    assert load_context(harness)[1]["freshness"]


def test_duplicate_automatic_log_event_is_rejected_even_with_matching_counter(harness):
    from harness.context.model import ContextBuildError

    outside_finding(harness)
    generate_context(harness)
    path = harness / "context/expansions.yaml"
    log = yaml.safe_load(path.read_text())
    duplicate = dict(log["expansions"][0], **{"from": "BOUNDED", "to": "EXPANDED"})
    log["expansions"].append(duplicate)
    write_yaml(path, log)
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["budget"]["context_expansions"] = 2
    write_yaml(task_path, task)
    with pytest.raises(ContextBuildError, match="CONTEXT_POLICY_MISMATCH"):
        generate_context(harness)


@pytest.mark.parametrize("scope", [[], ["src/local.py"], ["src/**"]])
def test_intersecting_or_empty_decision_scope_does_not_expand(harness, scope):
    add_core_records(harness)
    path = next((harness / "decisions").glob("*.yaml"))
    record = yaml.safe_load(path.read_text())
    record["scope"] = scope
    write_yaml(path, record)
    assert generate_context(harness)["expansions"] == []

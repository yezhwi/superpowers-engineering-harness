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


def test_invalid_integrity_never_records_automatic_expansion(harness):
    from harness.context.model import ContextBuildError

    outside_finding(harness)
    write_yaml(harness / "requirements.yaml", {"requirements": "invalid"})
    before = (harness / "current-task.yaml").read_bytes()
    with pytest.raises(ContextBuildError, match="CONTEXT_SCHEMA_INVALID"):
        generate_context(harness)
    assert (harness / "current-task.yaml").read_bytes() == before
    assert not (harness / "context/expansions.yaml").exists()


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

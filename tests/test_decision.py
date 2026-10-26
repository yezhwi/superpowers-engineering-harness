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


def test_first_decision_write_creates_metadata_index(tmp_path):
    from harness.decision import propose

    harness_dir = setup_harness(tmp_path)
    created = propose(harness_dir, proposal())

    index = yaml.safe_load((harness_dir / "decisions/index.yaml").read_text())
    assert index["decisions"][0] == {
        "id": created["id"],
        "task_id": "TASK-042",
        "status": "PROPOSED",
        "supersedes": None,
        "superseded_by": None,
        "sha256": index["decisions"][0]["sha256"],
    }
    assert index["decisions"][0]["sha256"].startswith("sha256:")


def test_reindex_updates_metadata_after_manual_body_edit(tmp_path):
    from harness.decision import load_decision_index, propose, reindex

    harness_dir = setup_harness(tmp_path)
    created = propose(harness_dir, proposal())
    path = harness_dir / f"decisions/{created['id']}.yaml"
    body = yaml.safe_load(path.read_text())
    body["status"] = "REJECTED"
    path.write_text(yaml.safe_dump(body, sort_keys=False))

    reindex(harness_dir)

    assert load_decision_index(harness_dir)[0]["status"] == "REJECTED"


def test_decision_index_rejects_duplicate_ids(tmp_path):
    from harness.decision import DecisionError, load_decision_index, propose

    harness_dir = setup_harness(tmp_path)
    propose(harness_dir, proposal())
    path = harness_dir / "decisions/index.yaml"
    index = yaml.safe_load(path.read_text())
    index["decisions"].append(dict(index["decisions"][0]))
    path.write_text(yaml.safe_dump(index))

    with pytest.raises(DecisionError, match="DECISION_INDEX_INVALID"):
        load_decision_index(harness_dir)


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

    harness_dir = setup_harness(tmp_path)
    original = propose(harness_dir, proposal())
    accept(harness_dir, original["id"], "redis", "accepted_recommendation")

    def fail_publish(*args, **kwargs):
        raise OSError("injected publication failure")

    monkeypatch.setattr("harness.decision.publish", fail_publish, raising=False)
    with pytest.raises(OSError, match="injected publication failure"):
        supersede(harness_dir, original["id"], proposal(topic="replacement"))

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


@pytest.fixture
def decision_read_case(tmp_path):
    from harness import decision

    root = setup_harness(tmp_path)
    record = decision.propose(root, proposal())
    return root, record


def test_read_session_keeps_reads_validation_and_mutable_results_independent(decision_read_case, monkeypatch):
    from harness import decision

    root, record = decision_read_case
    path = root / f"decisions/{record['id']}.yaml"
    reads = []
    original = decision.source_access.read_text

    def read(member, *args, **kwargs):
        if member == path:
            reads.append(member)
        return original(member, *args, **kwargs)

    monkeypatch.setattr(decision.source_access, "read_text", read)
    with decision._read_session():
        first = decision.load_decision(root, record["id"])
        first["context"].append("caller-local mutation")
        second = decision.load_decision(root, record["id"])
        assert second["context"] == ["repository has Redis client"]
        first["topic"] = None
        with pytest.raises(decision.DecisionError, match="DECISION_RECORD_INVALID"):
            decision._validate(first)
        changed = dict(record, status="INVALID")
        path.write_text(yaml.safe_dump(changed))
        with pytest.raises(decision.DecisionError, match="DECISION_RECORD_INVALID"):
            decision.load_decision(root, record["id"])
    assert reads == [path, path, path]


@pytest.mark.parametrize("kind", ["changed", "malformed"])
def test_read_session_uses_current_schema_and_rechecks_preparation(decision_read_case, monkeypatch, kind):
    from jsonschema import SchemaError

    from harness import decision

    _, record = decision_read_case
    original = decision._schema
    reads = []

    def schema():
        document = original()
        reads.append(True)
        if len(reads) > 1:
            if kind == "malformed":
                document["type"] = "not-a-schema-type"
            else:
                document["properties"]["topic"] = {"const": "different topic"}
        return document

    monkeypatch.setattr(decision, "_schema", schema)
    with decision._read_session():
        decision._validate(record)
        with pytest.raises(SchemaError if kind == "malformed" else decision.DecisionError):
            decision._validate(record)
    assert len(reads) == 2


def test_read_session_does_not_hide_invalid_yaml_or_nonmapping_replacement(decision_read_case):
    from harness import decision

    root, record = decision_read_case
    path = root / f"decisions/{record['id']}.yaml"
    with decision._read_session():
        decision.load_decision(root, record["id"])
        for replacement in ("[", "[]"):
            path.write_text(replacement)
            with pytest.raises(decision.DecisionError, match="DECISION_RECORD_INVALID"):
                decision.load_decision(root, record["id"])


@pytest.mark.parametrize("failure", [None, ValueError, KeyboardInterrupt, SystemExit])
def test_read_session_nested_and_copied_contexts_do_not_extend_lifetime(decision_read_case, monkeypatch, failure):
    from contextlib import nullcontext
    from contextvars import copy_context

    from harness import decision

    root, record = decision_read_case
    body = (root / f"decisions/{record['id']}.yaml").read_text()
    parses = []
    original = yaml.safe_load

    def parse(text, *args, **kwargs):
        if text == body:
            parses.append(True)
        return original(text, *args, **kwargs)

    monkeypatch.setattr(yaml, "safe_load", parse)
    with pytest.raises(failure) if failure else nullcontext():
        with decision._read_session():
            decision.load_decision(root, record["id"])
            captured = copy_context()
            with decision._read_session():
                decision.load_decision(root, record["id"])
            decision.load_decision(root, record["id"])
            if failure:
                raise failure()
    assert len(parses) == 2
    captured.run(decision.load_decision, root, record["id"])
    captured.run(decision.load_decision, root, record["id"])
    with decision._read_session():
        decision.load_decision(root, record["id"])
        decision.load_decision(root, record["id"])
    assert len(parses) == 5


def test_read_sessions_in_crossing_threads_keep_private_lifetimes(decision_read_case, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    from harness import decision

    root, record = decision_read_case
    body = (root / f"decisions/{record['id']}.yaml").read_text()
    first_read, second_read, first_closed = Event(), Event(), Event()
    parses, lock = [], Lock()
    original = yaml.safe_load

    def parse(text, *args, **kwargs):
        if text == body:
            with lock:
                parses.append(True)
        return original(text, *args, **kwargs)

    def first():
        with decision._read_session():
            decision.load_decision(root, record["id"])
            first_read.set()
            assert second_read.wait(10)
        first_closed.set()

    def second():
        assert first_read.wait(10)
        with decision._read_session():
            decision.load_decision(root, record["id"])
            second_read.set()
            assert first_closed.wait(10)
            decision.load_decision(root, record["id"])

    monkeypatch.setattr(yaml, "safe_load", parse)
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = [executor.submit(first), executor.submit(second)]
        for job in jobs:
            job.result(timeout=20)
    assert len(parses) == 2


@pytest.mark.parametrize("failure", [ValueError, KeyboardInterrupt])
def test_generate_failure_does_not_leave_decision_reuse_active(decision_read_case, monkeypatch, failure):
    from harness import decision
    from harness.context import store

    root, record = decision_read_case
    body = (root / f"decisions/{record['id']}.yaml").read_text()
    parses = []
    original = yaml.safe_load

    def parse(text, *args, **kwargs):
        if text == body:
            parses.append(True)
        return original(text, *args, **kwargs)

    def fail(*args, **kwargs):
        decision.load_decision(root, record["id"])
        raise failure()

    monkeypatch.setattr(yaml, "safe_load", parse)
    monkeypatch.setattr(store, "build_context", fail)
    with pytest.raises(failure):
        store.generate_context(root)
    decision.load_decision(root, record["id"])
    decision.load_decision(root, record["id"])
    assert len(parses) == 3


def test_read_session_preserves_best_match_validation_error(decision_read_case):
    from harness import decision

    _, record = decision_read_case
    invalid = dict(record, topic=None, status="BAD", options=[])
    with pytest.raises(decision.DecisionError) as baseline:
        decision._validate(invalid)
    with decision._read_session():
        decision._validate(record)
        with pytest.raises(decision.DecisionError) as reused:
            decision._validate(invalid)
    one, two = baseline.value.__cause__, reused.value.__cause__
    assert (type(one), one.message, one.json_path, list(one.schema_path)) == (
        type(two), two.message, two.json_path, list(two.schema_path)
    )

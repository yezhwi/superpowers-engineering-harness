"""Execution v2 schema and pure replay contract tests."""

from copy import deepcopy

import pytest
from jsonschema import ValidationError, validate

from harness.schema_resources import read_schema


DIGEST = "sha256:" + "a" * 64
OTHER_DIGEST = "sha256:" + "b" * 64


def plan() -> dict:
    return {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "first"},
            {"id": "P-002", "intent": "second"},
        ],
    }


def empty_v2() -> dict:
    return {
        "version": 2,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": DIGEST},
        "sequence": 0,
        "transitions": [],
        "items": {},
    }


def proof_receipt(*, evidence_refs: tuple[str, ...] = ()) -> dict:
    return {
        "head": "abc123",
        "workspace": DIGEST,
        "evidence": [
            {
                "ref": reference,
                "sha256": OTHER_DIGEST,
                "type": "unit_test",
                "exit_code": 0,
                "commit": "abc123",
                "workspace_fingerprint": DIGEST,
            }
            for reference in evidence_refs
        ],
        "surface_refs": ["src/service.py"],
    }


def decision_receipt() -> dict:
    return {
        "decision_id": "DEC-031",
        "sha256": OTHER_DIGEST,
        "task_id": "TASK-062",
        "status": "ACCEPTED",
    }


def schema() -> dict:
    return read_schema("plan-execution.schema.json")


def assert_schema_invalid(document: dict) -> None:
    with pytest.raises(ValidationError):
        validate(document, schema())


def test_plan_execution_schema_preserves_v1_documents():
    document = {
        "version": 1,
        "plan": {"path": ".harness/plan.yaml", "fingerprint": DIGEST},
        "items": {
            "P-001": {
                "status": "SUPERSEDED",
                "reason": "split",
                "superseded_by": ["P-002"],
                "decision_id": "DEC-031",
            }
        },
    }

    validate(document, schema())


def test_plan_execution_schema_accepts_empty_v2_journal():
    validate(empty_v2(), schema())


@pytest.mark.parametrize(
    ("transition", "projected"),
    [
        (
            {
                "sequence": 1,
                "item": "P-001",
                "from": "PENDING",
                "to": "IN_PROGRESS",
                "action": "BEGIN",
            },
            {"status": "IN_PROGRESS"},
        ),
        (
            {
                "sequence": 2,
                "item": "P-001",
                "from": "IN_PROGRESS",
                "to": "BLOCKED",
                "action": "BLOCK",
                "reason": "waiting",
            },
            {"status": "BLOCKED", "reason": "waiting"},
        ),
        (
            {
                "sequence": 3,
                "item": "P-001",
                "from": "BLOCKED",
                "to": "IN_PROGRESS",
                "action": "RESUME",
            },
            {"status": "IN_PROGRESS"},
        ),
        (
            {
                "sequence": 2,
                "item": "P-001",
                "from": "IN_PROGRESS",
                "to": "COMPLETE",
                "action": "RECONCILE",
                "evidence_refs": ["unit-test.json"],
                "surface_refs": ["src/service.py"],
                "proof_receipt": proof_receipt(evidence_refs=("unit-test.json",)),
            },
            {
                "status": "COMPLETE",
                "evidence_refs": ["unit-test.json"],
                "surface_refs": ["src/service.py"],
            },
        ),
        (
            {
                "sequence": 2,
                "item": "P-001",
                "from": "IN_PROGRESS",
                "to": "SKIPPED",
                "action": "RECONCILE",
                "reason": "removed",
                "decision_id": "DEC-031",
                "decision_receipt": decision_receipt(),
            },
            {"status": "SKIPPED", "reason": "removed", "decision_id": "DEC-031"},
        ),
        (
            {
                "sequence": 2,
                "item": "P-001",
                "from": "IN_PROGRESS",
                "to": "SUPERSEDED",
                "action": "RECONCILE",
                "reason": "split",
                "decision_id": "DEC-031",
                "superseded_by": ["P-002"],
                "decision_receipt": decision_receipt(),
            },
            {
                "status": "SUPERSEDED",
                "reason": "split",
                "decision_id": "DEC-031",
                "superseded_by": ["P-002"],
            },
        ),
        (
            {
                "sequence": 3,
                "item": "P-001",
                "from": "COMPLETE",
                "to": "COMPLETE",
                "action": "REFRESH_PROOF",
                "evidence_refs": ["unit-test.json"],
                "surface_refs": ["src/service.py"],
                "proof_receipt": proof_receipt(evidence_refs=("unit-test.json",)),
            },
            {
                "status": "COMPLETE",
                "evidence_refs": ["unit-test.json"],
                "surface_refs": ["src/service.py"],
            },
        ),
    ],
)
def test_plan_execution_schema_accepts_each_action_payload(transition, projected):
    document = empty_v2()
    document["sequence"] = transition["sequence"]
    document["transitions"] = [transition]
    document["items"] = {"P-001": projected}

    validate(document, schema())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(extra=True),
        lambda d: d["items"].update({"bad": {"status": "IN_PROGRESS"}}),
        lambda d: d.update(
            sequence=1,
            transitions=[
                {
                    "sequence": 1,
                    "item": "P-001",
                    "from": "PENDING",
                    "to": "IN_PROGRESS",
                    "action": "BEGIN",
                    "reason": "forbidden",
                }
            ],
        ),
        lambda d: d.update(
            sequence=1,
            transitions=[
                {
                    "sequence": 1,
                    "item": "P-001",
                    "from": "IN_PROGRESS",
                    "to": "BLOCKED",
                    "action": "BLOCK",
                    "reason": "",
                }
            ],
        ),
        lambda d: d.update(
            sequence=1,
            transitions=[
                {
                    "sequence": 1,
                    "item": "P-001",
                    "from": "IN_PROGRESS",
                    "to": "COMPLETE",
                    "action": "RECONCILE",
                    "evidence_refs": [],
                    "surface_refs": [],
                }
            ],
        ),
        lambda d: d.update(
            sequence=1,
            transitions=[
                {
                    "sequence": 1,
                    "item": "P-001",
                    "from": "IN_PROGRESS",
                    "to": "SKIPPED",
                    "action": "RECONCILE",
                    "reason": "removed",
                    "decision_id": "DEC-031",
                    "decision_receipt": {
                        **decision_receipt(),
                        "status": "PROPOSED",
                    },
                }
            ],
        ),
        lambda d: d.update(
            sequence=1,
            transitions=[
                {
                    "sequence": 1,
                    "item": "P-001",
                    "from": "IN_PROGRESS",
                    "to": "SUPERSEDED",
                    "action": "RECONCILE",
                    "reason": "split",
                    "decision_id": "DEC-031",
                    "superseded_by": [],
                    "decision_receipt": decision_receipt(),
                }
            ],
        ),
    ],
)
def test_plan_execution_schema_rejects_closed_or_malformed_action_payloads(mutate):
    document = empty_v2()
    mutate(document)
    assert_schema_invalid(document)


def test_plan_execution_schema_rejects_unknown_receipt_fields():
    document = empty_v2()
    receipt = proof_receipt(evidence_refs=("unit-test.json",))
    receipt["evidence"][0]["stdout"] = "secret"
    document.update(
        sequence=1,
        transitions=[
            {
                "sequence": 1,
                "item": "P-001",
                "from": "IN_PROGRESS",
                "to": "COMPLETE",
                "action": "RECONCILE",
                "evidence_refs": ["unit-test.json"],
                "surface_refs": ["src/service.py"],
                "proof_receipt": receipt,
            }
        ],
    )

    assert_schema_invalid(document)


def test_plan_execution_schema_rejects_unknown_action():
    document = empty_v2()
    document.update(
        sequence=1,
        transitions=[
            {
                "sequence": 1,
                "item": "P-001",
                "from": "PENDING",
                "to": "IN_PROGRESS",
                "action": "START",
            }
        ],
    )

    assert_schema_invalid(document)


def execution(transitions: list[dict], items: dict) -> dict:
    from harness.plan_reconciliation import plan_fingerprint

    return {
        "version": 2,
        "plan": {
            "path": ".harness/plan.yaml",
            "fingerprint": plan_fingerprint(plan()),
        },
        "sequence": len(transitions),
        "transitions": transitions,
        "items": items,
    }


def begin(item: str = "P-001", sequence: int = 1) -> dict:
    return {
        "sequence": sequence,
        "item": item,
        "from": "PENDING",
        "to": "IN_PROGRESS",
        "action": "BEGIN",
    }


def test_replay_empty_v2_is_legal_and_points_to_first_plan_item():
    from harness.plan_execution import replay_plan_execution
    from harness.plan_reconciliation import plan_fingerprint

    document = empty_v2()
    document["plan"]["fingerprint"] = plan_fingerprint(plan())

    result = replay_plan_execution(plan(), document)

    assert result.items == {}
    assert result.active_item is None
    assert result.next_item == "P-001"
    assert result.latest_proof_receipts == {}
    assert result.issues == ()


def test_replay_legal_begin_keeps_active_item_as_next():
    from harness.plan_execution import replay_plan_execution

    document = execution([begin()], {"P-001": {"status": "IN_PROGRESS"}})

    result = replay_plan_execution(plan(), document)

    assert result.items == {"P-001": {"status": "IN_PROGRESS"}}
    assert result.active_item == "P-001"
    assert result.next_item == "P-001"
    assert result.issues == ()


def test_replay_legal_block_resume_complete_lifecycle():
    from harness.plan_execution import replay_plan_execution

    receipt = proof_receipt(evidence_refs=("unit-test.json",))
    transitions = [
        begin(),
        {
            "sequence": 2,
            "item": "P-001",
            "from": "IN_PROGRESS",
            "to": "BLOCKED",
            "action": "BLOCK",
            "reason": "waiting",
        },
        {
            "sequence": 3,
            "item": "P-001",
            "from": "BLOCKED",
            "to": "IN_PROGRESS",
            "action": "RESUME",
        },
        {
            "sequence": 4,
            "item": "P-001",
            "from": "IN_PROGRESS",
            "to": "COMPLETE",
            "action": "RECONCILE",
            "evidence_refs": ["unit-test.json"],
            "surface_refs": ["src/service.py"],
            "proof_receipt": receipt,
        },
    ]
    projected = {
        "P-001": {
            "status": "COMPLETE",
            "evidence_refs": ["unit-test.json"],
            "surface_refs": ["src/service.py"],
        }
    }

    result = replay_plan_execution(plan(), execution(transitions, projected))

    assert result.items == projected
    assert result.active_item is None
    assert result.next_item == "P-002"
    assert result.latest_proof_receipts == {"P-001": receipt}
    assert result.issues == ()


def test_replay_legal_skipped_lifecycle_projects_decision():
    from harness.plan_execution import replay_plan_execution

    transition = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "SKIPPED",
        "action": "RECONCILE",
        "reason": "removed",
        "decision_id": "DEC-031",
        "decision_receipt": decision_receipt(),
    }
    projected = {
        "P-001": {
            "status": "SKIPPED",
            "reason": "removed",
            "decision_id": "DEC-031",
        }
    }

    result = replay_plan_execution(
        plan(), execution([begin(), transition], projected)
    )

    assert result.items == projected
    assert result.next_item == "P-002"
    assert result.latest_proof_receipts == {}
    assert result.issues == ()


def test_replay_legal_superseded_lifecycle_projects_replacements():
    from harness.plan_execution import replay_plan_execution

    transition = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "SUPERSEDED",
        "action": "RECONCILE",
        "reason": "split",
        "decision_id": "DEC-031",
        "superseded_by": ["P-002"],
        "decision_receipt": decision_receipt(),
    }
    projected = {
        "P-001": {
            "status": "SUPERSEDED",
            "reason": "split",
            "decision_id": "DEC-031",
            "superseded_by": ["P-002"],
        }
    }

    result = replay_plan_execution(
        plan(), execution([begin(), transition], projected)
    )

    assert result.items == projected
    assert result.next_item == "P-002"
    assert result.issues == ()


def test_replay_legal_refresh_updates_only_latest_proof_receipt():
    from harness.plan_execution import replay_plan_execution

    accepted = proof_receipt(evidence_refs=("unit-test.json",))
    refreshed = deepcopy(accepted)
    refreshed["head"] = "def456"
    refreshed["workspace"] = OTHER_DIGEST
    refreshed["evidence"][0]["sha256"] = DIGEST
    refreshed["evidence"][0]["commit"] = "def456"
    refreshed["evidence"][0]["workspace_fingerprint"] = OTHER_DIGEST
    complete = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "COMPLETE",
        "action": "RECONCILE",
        "evidence_refs": ["unit-test.json"],
        "surface_refs": ["src/service.py"],
        "proof_receipt": accepted,
    }
    refresh = {
        "sequence": 3,
        "item": "P-001",
        "from": "COMPLETE",
        "to": "COMPLETE",
        "action": "REFRESH_PROOF",
        "evidence_refs": ["unit-test.json"],
        "surface_refs": ["src/service.py"],
        "proof_receipt": refreshed,
    }
    projected = {
        "P-001": {
            "status": "COMPLETE",
            "evidence_refs": ["unit-test.json"],
            "surface_refs": ["src/service.py"],
        }
    }
    document = execution([begin(), complete, refresh], projected)
    original = deepcopy(document)

    first = replay_plan_execution(plan(), document)
    second = replay_plan_execution(plan(), document)

    assert first == second
    assert first.latest_proof_receipts == {"P-001": refreshed}
    assert document == original
    assert document["transitions"][1]["proof_receipt"] == accepted
    assert first.issues == ()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d.update(sequence=0), "SEQUENCE_COUNT_MISMATCH"),
        (lambda d: d["transitions"][0].update(sequence=2), "SEQUENCE_NONCONTIGUOUS"),
        (lambda d: d["transitions"][0].update(item="P-999"), "ITEM_UNKNOWN"),
        (lambda d: d["transitions"][0].update(**{"from": "IN_PROGRESS"}), "FROM_MISMATCH"),
        (lambda d: d["transitions"][0].update(to="COMPLETE"), "LIFECYCLE_INVALID"),
        (lambda d: d["items"]["P-001"].update(status="BLOCKED"), "PROJECTION_MISMATCH"),
    ],
)
def test_replay_rejects_deterministic_journal_mutations(mutate, code):
    from harness.plan_execution import replay_plan_execution

    document = execution([begin()], {"P-001": {"status": "IN_PROGRESS"}})
    mutate(document)

    result = replay_plan_execution(plan(), document)

    assert result.issues[0].code == code
    assert result.items == {}
    assert result.next_item is None


def test_replay_rejects_begin_for_non_next_item_and_multiple_activity():
    from harness.plan_execution import replay_plan_execution

    document = execution(
        [begin(), begin(item="P-002", sequence=2)],
        {
            "P-001": {"status": "IN_PROGRESS"},
            "P-002": {"status": "IN_PROGRESS"},
        },
    )

    result = replay_plan_execution(plan(), document)

    assert result.issues[0].code == "BEGIN_ORDER_INVALID"


@pytest.mark.parametrize(
    "second",
    [
        {
            "sequence": 3,
            "item": "P-001",
            "from": "COMPLETE",
            "to": "IN_PROGRESS",
            "action": "BEGIN",
        },
        {
            "sequence": 3,
            "item": "P-001",
            "from": "COMPLETE",
            "to": "SKIPPED",
            "action": "RECONCILE",
            "reason": "changed",
            "decision_id": "DEC-031",
            "decision_receipt": decision_receipt(),
        },
    ],
)
def test_replay_rejects_terminal_rebegin_or_overwrite(second):
    from harness.plan_execution import replay_plan_execution

    receipt = proof_receipt(evidence_refs=("unit-test.json",))
    complete = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "COMPLETE",
        "action": "RECONCILE",
        "evidence_refs": ["unit-test.json"],
        "surface_refs": ["src/service.py"],
        "proof_receipt": receipt,
    }
    document = execution(
        [begin(), complete, second],
        {"P-001": {"status": second["to"]}},
    )

    result = replay_plan_execution(plan(), document)

    assert result.issues[0].code == "LIFECYCLE_INVALID"


def test_replay_rejects_receipt_references_that_differ_from_transition():
    from harness.plan_execution import replay_plan_execution

    receipt = proof_receipt(evidence_refs=("other.json",))
    complete = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "COMPLETE",
        "action": "RECONCILE",
        "evidence_refs": ["unit-test.json"],
        "surface_refs": ["src/service.py"],
        "proof_receipt": receipt,
    }
    projected = {
        "P-001": {
            "status": "COMPLETE",
            "evidence_refs": ["unit-test.json"],
            "surface_refs": ["src/service.py"],
        }
    }

    result = replay_plan_execution(plan(), execution([begin(), complete], projected))

    assert result.issues[0].code == "RECEIPT_MISMATCH"


@pytest.mark.parametrize(
    "receipt_change",
    [
        {"exit_code": 1},
        {"commit": "different"},
        {"workspace_fingerprint": OTHER_DIGEST},
    ],
)
def test_replay_rejects_proof_receipt_that_could_not_have_been_accepted(receipt_change):
    from harness.plan_execution import replay_plan_execution

    receipt = proof_receipt(evidence_refs=("unit-test.json",))
    receipt["evidence"][0].update(receipt_change)
    complete = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "COMPLETE",
        "action": "RECONCILE",
        "evidence_refs": ["unit-test.json"],
        "surface_refs": ["src/service.py"],
        "proof_receipt": receipt,
    }
    projected = {
        "P-001": {
            "status": "COMPLETE",
            "evidence_refs": ["unit-test.json"],
            "surface_refs": ["src/service.py"],
        }
    }

    result = replay_plan_execution(plan(), execution([begin(), complete], projected))

    assert result.issues[0].code == "RECEIPT_MISMATCH"


def test_replay_rejects_decision_receipt_that_was_not_accepted():
    from harness.plan_execution import replay_plan_execution

    receipt = decision_receipt()
    receipt["status"] = "PROPOSED"
    skipped = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "SKIPPED",
        "action": "RECONCILE",
        "reason": "removed",
        "decision_id": "DEC-031",
        "decision_receipt": receipt,
    }
    projected = {
        "P-001": {
            "status": "SKIPPED",
            "reason": "removed",
            "decision_id": "DEC-031",
        }
    }

    result = replay_plan_execution(plan(), execution([begin(), skipped], projected))

    assert result.issues[0].code == "RECEIPT_MISMATCH"


def test_replay_rejects_refresh_for_noncomplete_item():
    from harness.plan_execution import replay_plan_execution

    refresh = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "COMPLETE",
        "action": "REFRESH_PROOF",
        "evidence_refs": [],
        "surface_refs": ["src/service.py"],
        "proof_receipt": proof_receipt(),
    }
    projected = {
        "P-001": {
            "status": "COMPLETE",
            "surface_refs": ["src/service.py"],
        }
    }

    result = replay_plan_execution(plan(), execution([begin(), refresh], projected))

    assert result.issues[0].code == "LIFECYCLE_INVALID"


def test_replay_rejects_supersession_projection_mismatch():
    from harness.plan_execution import replay_plan_execution

    superseded = {
        "sequence": 2,
        "item": "P-001",
        "from": "IN_PROGRESS",
        "to": "SUPERSEDED",
        "action": "RECONCILE",
        "reason": "split",
        "decision_id": "DEC-031",
        "superseded_by": ["P-002"],
        "decision_receipt": decision_receipt(),
    }
    projected = {
        "P-001": {
            "status": "SUPERSEDED",
            "reason": "split",
            "decision_id": "DEC-031",
            "superseded_by": ["P-001"],
        }
    }

    result = replay_plan_execution(
        plan(), execution([begin(), superseded], projected)
    )

    assert result.issues[0].code == "PROJECTION_MISMATCH"


def test_append_plan_transition_assigns_sequence_and_derives_projection():
    from harness.plan_execution import append_plan_transition
    from harness.plan_reconciliation import plan_fingerprint

    document = empty_v2()
    document["plan"]["fingerprint"] = plan_fingerprint(plan())
    original = deepcopy(document)
    transition = {key: value for key, value in begin().items() if key != "sequence"}

    updated = append_plan_transition(plan(), document, transition)

    assert updated == execution([begin()], {"P-001": {"status": "IN_PROGRESS"}})
    assert document == original
    assert "sequence" not in transition


def test_append_plan_transition_rejects_invalid_candidate_without_mutation():
    from harness.plan_execution import PlanExecutionError, append_plan_transition
    from harness.plan_reconciliation import plan_fingerprint

    document = empty_v2()
    document["plan"]["fingerprint"] = plan_fingerprint(plan())
    original = deepcopy(document)
    transition = {
        "item": "P-002",
        "from": "PENDING",
        "to": "IN_PROGRESS",
        "action": "BEGIN",
    }

    with pytest.raises(PlanExecutionError, match="BEGIN_ORDER_INVALID"):
        append_plan_transition(plan(), document, transition)

    assert document == original

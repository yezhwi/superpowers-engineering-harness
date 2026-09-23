from pathlib import Path

import pytest
import yaml

from harness.alignment import AlignmentError, load_alignment


def complete_alignment() -> dict:
    return {
        "version": 1,
        "task_id": "TASK-001",
        "goal": {"summary": "Close intent before implementation"},
        "scope": {"in": ["src/harness"], "out": ["CLI integration"]},
        "non_goals": ["scope drift detection"],
        "boundaries": ["private control plane"],
        "constraints": [],
        "assumptions": [],
        "acceptance_criteria": [
            {
                "id": "AC-001",
                "description": "Alignment graph is complete",
                "requirement_ids": ["REQ-001"],
            }
        ],
        "implementation_surfaces": [
            {
                "id": "SURFACE-001",
                "acceptance_criteria": ["AC-001"],
                "paths": ["src/harness/alignment.py"],
                "seam": "check_completeness",
            }
        ],
        "verification": [
            {
                "id": "VER-001",
                "acceptance_criteria": ["AC-001"],
                "method": "test",
                "expected_evidence": "unit-test evidence covers tests/test_alignment.py",
            }
        ],
        "decision_ids": ["DEC-001"],
        "interface_contract_ids": ["INT-001"],
        "open_questions": [],
        "open_decisions": [],
        "open_loops": [],
        "freeze": {"frozen": False, "frozen_at": None, "contract_hash": None},
    }


def write_alignment(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / ".harness" / "alignment.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_load_alignment_returns_valid_reference_only_contract(tmp_path):
    write_alignment(tmp_path, complete_alignment())

    assert load_alignment(tmp_path / ".harness")["acceptance_criteria"][0][
        "requirement_ids"
    ] == ["REQ-001"]


def test_load_alignment_rejects_embedded_decision_record(tmp_path):
    document = complete_alignment()
    document["decisions"] = [{"id": "DEC-001", "question": "embedded"}]
    write_alignment(tmp_path, document)

    with pytest.raises(AlignmentError, match="ALIGNMENT_INVALID"):
        load_alignment(tmp_path / ".harness")


def issue_codes(issues):
    return {issue.code for issue in issues}


def test_complete_alignment_has_no_issues():
    from harness.alignment import check_completeness

    assert (
        check_completeness(
            complete_alignment(),
            requirement_ids={"REQ-001"},
            critical_requirement_ids={"REQ-001"},
        )
        == []
    )


@pytest.mark.parametrize(
    ("mutate", "requirement_ids", "critical_requirement_ids", "expected"),
    [
        (
            lambda document: document["goal"].update(summary=""),
            {"REQ-001"},
            set(),
            {"ALIGNMENT_GOAL_MISSING"},
        ),
        (
            lambda document: document["scope"].update({"in": [], "out": []}),
            {"REQ-001"},
            set(),
            {"ALIGNMENT_SCOPE_MISSING"},
        ),
        (
            lambda document: document["open_decisions"].append("DEC-002"),
            {"REQ-001"},
            set(),
            {"OPEN_DECISION"},
        ),
        (
            lambda document: document["open_loops"].append("LOOP-001"),
            {"REQ-001"},
            set(),
            {"OPEN_LOOP"},
        ),
        (
            lambda document: None,
            {"REQ-001", "REQ-002"},
            set(),
            {"REQ_WITHOUT_AC"},
        ),
        (
            lambda document: document["acceptance_criteria"][0].update(
                requirement_ids=[]
            ),
            set(),
            set(),
            {"AC_WITHOUT_REQ"},
        ),
        (
            lambda document: document.update(verification=[]),
            {"REQ-001"},
            set(),
            {"AC_WITHOUT_VERIFICATION"},
        ),
        (
            lambda document: document["verification"][0].update(expected_evidence=""),
            {"REQ-001"},
            set(),
            {"VERIFICATION_EXPECTED_EVIDENCE_MISSING"},
        ),
        (
            lambda document: document.update(implementation_surfaces=[]),
            {"REQ-001"},
            {"REQ-001"},
            {"CRITICAL_REQ_WITHOUT_SURFACE"},
        ),
    ],
)
def test_completeness_reports_each_stable_open_loop(
    mutate, requirement_ids, critical_requirement_ids, expected
):
    from harness.alignment import check_completeness

    document = complete_alignment()
    mutate(document)

    assert issue_codes(
        check_completeness(
            document,
            requirement_ids=requirement_ids,
            critical_requirement_ids=critical_requirement_ids,
        )
    ) == expected


def test_completeness_merges_persisted_proposed_decisions():
    from harness.alignment import check_completeness

    issues = check_completeness(
        complete_alignment(),
        requirement_ids={"REQ-001"},
        proposed_decision_ids={"DEC-002", "DEC-003"},
    )

    assert [(issue.code, issue.subject_id) for issue in issues] == [
        ("OPEN_DECISION", "DEC-002"),
        ("OPEN_DECISION", "DEC-003"),
    ]


def test_completeness_diagnostics_are_ordered():
    from harness.alignment import check_completeness

    document = complete_alignment()
    document["goal"]["summary"] = ""
    document["scope"]["in"] = []
    document["open_decisions"] = ["DEC-003", "DEC-002"]
    document["open_loops"] = ["LOOP-002", "LOOP-001"]

    issues = check_completeness(document, requirement_ids={"REQ-001"})

    assert [(issue.code, issue.subject_id) for issue in issues] == [
        ("ALIGNMENT_GOAL_MISSING", None),
        ("ALIGNMENT_SCOPE_MISSING", None),
        ("OPEN_DECISION", "DEC-002"),
        ("OPEN_DECISION", "DEC-003"),
        ("OPEN_LOOP", "LOOP-001"),
        ("OPEN_LOOP", "LOOP-002"),
    ]


def test_sealed_freeze_bootstraps_once_and_rejects_self_hash_rewrite(tmp_path):
    from harness.alignment import contract_hash, validate_sealed_freeze

    document = complete_alignment()
    document["task_id"] = "TASK-001"
    document["freeze"] = {
        "frozen": True,
        "frozen_at": "2026-09-18T00:00:00+00:00",
        "contract_hash": contract_hash(document),
    }
    validate_sealed_freeze(tmp_path, document, decisions=[], boundary_refs={
        "interface": [], "permission": [], "persistence": []
    })
    assert (tmp_path / "alignment-freeze.yaml").exists()

    document["goal"]["summary"] = "rewritten"
    document["freeze"]["contract_hash"] = contract_hash(document)
    with pytest.raises(Exception, match="CONTRACT_CHANGED"):
        validate_sealed_freeze(tmp_path, document, decisions=[], boundary_refs={
            "interface": [], "permission": [], "persistence": []
        })


def test_sealed_freeze_rejects_accepted_decision_option_change(tmp_path):
    from harness.alignment import AlignmentError, contract_hash, validate_sealed_freeze

    document = complete_alignment()
    document["task_id"] = "TASK-001"
    document["decision_ids"] = ["DEC-001"]
    document["freeze"] = {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": contract_hash(document)}
    choices = [{"id": "DEC-001", "status": "ACCEPTED", "selected": {"option": "one"}}]
    refs = {"interface": [], "permission": [], "persistence": []}
    validate_sealed_freeze(tmp_path, document, decisions=choices, boundary_refs=refs)

    choices[0]["selected"]["option"] = "two"
    with pytest.raises(AlignmentError, match="CONTRACT_CHANGED"):
        validate_sealed_freeze(tmp_path, document, decisions=choices, boundary_refs=refs)


def test_sealed_freeze_rejects_added_or_removed_typed_boundary(tmp_path):
    from harness.alignment import AlignmentError, contract_hash, validate_sealed_freeze

    document = complete_alignment()
    document["task_id"] = "TASK-001"
    document["freeze"] = {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": contract_hash(document)}
    original = {"interface": [], "permission": ["DEC-001"], "persistence": []}
    validate_sealed_freeze(tmp_path, document, decisions=[], boundary_refs=original)

    with pytest.raises(AlignmentError, match="SCOPE_DRIFT_PERMISSION"):
        validate_sealed_freeze(tmp_path, document, decisions=[], boundary_refs={
            "interface": [], "permission": ["DEC-002"], "persistence": []
        })


def test_sealed_freeze_reports_each_changed_boundary(tmp_path):
    from harness.alignment import contract_hash, sealed_freeze_drift

    document = complete_alignment()
    document["task_id"] = "TASK-001"
    document["freeze"] = {"frozen": True, "frozen_at": "2026-09-18T00:00:00+00:00", "contract_hash": contract_hash(document)}
    initial = {"interface": [], "permission": ["DEC-001"], "persistence": ["INT-001"]}
    assert sealed_freeze_drift(tmp_path, document, decisions=[], boundary_refs=initial) == []

    assert [(issue.code, issue.subject_id) for issue in sealed_freeze_drift(
        tmp_path, document, decisions=[],
        boundary_refs={"interface": [], "permission": ["DEC-002"], "persistence": []},
    )] == [
        ("SCOPE_DRIFT_PERMISSION", "DEC-001"),
        ("SCOPE_DRIFT_PERMISSION", "DEC-002"),
        ("SCOPE_DRIFT_PERSISTENCE", "INT-001"),
    ]


def test_contract_hash_is_stable_for_mapping_order_and_ignores_seams():
    from harness.alignment import contract_hash

    document = complete_alignment()
    reordered = dict(reversed(list(document.items())))
    reordered["implementation_surfaces"][0]["seam"] = "renamed_private_helper"

    assert contract_hash(document) == contract_hash(reordered)


def test_scope_drift_classifier_reports_contract_and_interface_changes():
    from harness.alignment import classify_scope_drift

    assert {issue.code for issue in classify_scope_drift(
        frozen_hash="sha256:" + "0" * 64,
        current_hash="sha256:" + "1" * 64,
        external_interface_changed=True,
        permission_boundary_changed=True,
        persistence_boundary_changed=True,
    )} == {"CONTRACT_CHANGED", "SCOPE_DRIFT_API", "SCOPE_DRIFT_PERMISSION", "SCOPE_DRIFT_PERSISTENCE"}


def test_scope_drift_classifier_ignores_private_change():
    from harness.alignment import classify_scope_drift

    assert classify_scope_drift(
        frozen_hash="sha256:" + "0" * 64,
        current_hash="sha256:" + "0" * 64,
        external_interface_changed=False,
        permission_boundary_changed=False,
        persistence_boundary_changed=False,
    ) == []


def test_validate_freeze_rejects_stale_digest_without_mutation():
    from copy import deepcopy
    from harness.alignment import AlignmentError, contract_hash, validate_freeze

    document = complete_alignment()
    document["freeze"] = {
        "frozen": True,
        "frozen_at": "2026-09-18T00:00:00+00:00",
        "contract_hash": contract_hash(document),
    }
    before = deepcopy(document)
    validate_freeze(document)
    document["goal"]["summary"] = "changed"

    with pytest.raises(AlignmentError, match="ALIGNMENT_FREEZE_INVALID"):
        validate_freeze(document)
    assert document["freeze"] == before["freeze"]

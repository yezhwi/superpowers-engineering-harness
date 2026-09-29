"""P2 body-free Plan reporting tests."""

import json

import pytest

from harness.blockers import GateBlocker
from harness.plan_reconciliation import PlanAssessment
from harness.plan_reporting import plan_item_reports, with_verbose_items


def plan_items():
    return {
        "version": 1,
        "items": [
            {"id": "P-001", "intent": "tests", "test_case_refs": ["REQ-001/TC-001"]},
            {"id": "P-002", "intent": "surfaces", "surfaces": ["src/x.py"]},
            {
                "id": "P-003",
                "intent": "both",
                "test_case_refs": ["REQ-001/TC-001"],
                "surfaces": ["src/y.py"],
            },
            {"id": "P-004", "intent": "none"},
        ],
    }


def assessment(projection, blockers=(), final_blockers=()):
    return PlanAssessment(
        tuple(blockers),
        tuple(final_blockers),
        projection,
        None,
    )


def blocker(code: str, source: str, recovery: str) -> GateBlocker:
    return GateBlocker(
        code,
        "verification",
        "SECRET blocker message",
        source=source,
        recover_to=recovery,
    )


def test_plan_item_reports_projects_closed_fields_in_canonical_order():
    report = plan_item_reports(
        plan_items(),
        assessment(
            {
                "P-001": {"status": "COMPLETE", "evidence_refs": ["SECRET-EVIDENCE"]},
                "P-002": {"status": "IN_PROGRESS"},
                "P-003": {"status": "COMPLETE", "proof_receipt": "SECRET-RECEIPT"},
                "P-004": {"status": "SKIPPED", "reason": "SECRET-REASON"},
            },
            blockers=(
                blocker("PLAN_PROOF_MISSING", "P-001", "VERIFYING"),
                blocker("PLAN_PROTECTED_PATHS_MODIFIED", "P-003", "IMPLEMENTING"),
                blocker("PLAN_DISPOSITION_INVALID", "P-004", "IMPLEMENTING"),
            ),
        ),
    )

    assert tuple(row["id"] for row in report) == ("P-001", "P-002", "P-003", "P-004")
    assert report == (
        {
            "id": "P-001",
            "status": "COMPLETE",
            "proof_branch": "tests",
            "proof_health": "missing",
            "blockers": [{"code": "PLAN_PROOF_MISSING", "recovery": "VERIFYING"}],
        },
        {
            "id": "P-002",
            "status": "IN_PROGRESS",
            "proof_branch": "surfaces",
            "proof_health": "not_applicable",
            "blockers": [],
        },
        {
            "id": "P-003",
            "status": "COMPLETE",
            "proof_branch": "tests_and_surfaces",
            "proof_health": "invalid",
            "blockers": [
                {"code": "PLAN_PROTECTED_PATHS_MODIFIED", "recovery": "IMPLEMENTING"}
            ],
        },
        {
            "id": "P-004",
            "status": "SKIPPED",
            "proof_branch": "none",
            "proof_health": "not_applicable",
            "blockers": [
                {"code": "PLAN_DISPOSITION_INVALID", "recovery": "IMPLEMENTING"}
            ],
        },
    )
    assert all(
        set(row) == {"id", "status", "proof_branch", "proof_health", "blockers"}
        for row in report
    )


@pytest.mark.parametrize("status", ["SKIPPED", "SUPERSEDED"])
def test_plan_item_reports_noncomplete_terminal_proof_branch_is_not_applicable(status):
    plan = {
        "version": 1,
        "items": [
            {
                "id": "P-001",
                "intent": "semantic terminal",
                "test_case_refs": ["REQ-001/TC-001"],
                "surfaces": ["src/x.py"],
            }
        ],
    }

    (row,) = plan_item_reports(
        plan,
        assessment(
            {"P-001": {"status": status, "reason": "SECRET"}},
            blockers=(blocker("PLAN_DISPOSITION_INVALID", "P-001", "IMPLEMENTING"),),
        ),
    )

    assert row["proof_branch"] == "tests_and_surfaces"
    assert row["proof_health"] == "not_applicable"
    assert row["blockers"] == [
        {"code": "PLAN_DISPOSITION_INVALID", "recovery": "IMPLEMENTING"}
    ]


def test_plan_item_reports_untrusted_hides_persisted_status_and_progress():
    rows = plan_item_reports(
        plan_items(),
        assessment(
            None,
            blockers=(blocker("PLAN_SEQUENCE_INVALID", "P-003", "IMPLEMENTING"),),
        ),
    )

    assert all(row["status"] is None for row in rows)
    assert all(row["proof_health"] == "untrusted" for row in rows)
    assert rows[2]["blockers"] == [
        {"code": "PLAN_SEQUENCE_INVALID", "recovery": "IMPLEMENTING"}
    ]


def test_plan_item_reports_implicit_item_is_pending_and_none_complete_is_invalid():
    rows = plan_item_reports(
        plan_items(),
        assessment(
            {"P-004": {"status": "COMPLETE"}},
            blockers=(blocker("PLAN_DISPOSITION_INVALID", "P-004", "IMPLEMENTING"),),
        ),
    )

    assert rows[0]["status"] == "PENDING"
    assert rows[0]["proof_health"] == "not_applicable"
    assert rows[3]["proof_health"] == "not_applicable"
    assert rows[3]["blockers"] == [
        {"code": "PLAN_DISPOSITION_INVALID", "recovery": "IMPLEMENTING"}
    ]


def test_plan_item_reports_complete_proof_without_blocker_is_valid():
    (row,) = plan_item_reports(
        {"version": 1, "items": [{"id": "P-001", "intent": "surface", "surfaces": ["x"]}]},
        assessment({"P-001": {"status": "COMPLETE"}}),
    )

    assert row["proof_health"] == "valid"


def test_with_verbose_items_preserves_top_level_order_and_final_status():
    base = {
        "enabled": True,
        "mode": "task_and_final",
        "plan": {},
        "progress": None,
        "next_plan_item": None,
        "final_status": "pass",
        "blockers": [],
    }

    result = with_verbose_items(base, plan_items(), assessment(None))

    assert tuple(result) == (*base.keys(), "items")
    assert result["final_status"] == "pass"
    assert result is not base


def test_verbose_projection_never_serializes_body_sentinels():
    projection = {
        "P-001": {
            "status": "COMPLETE",
            "journal": "SECRET-JOURNAL",
            "sequence": "SECRET-SEQUENCE",
            "proof_receipt": "SECRET-PROOF",
            "decision_receipt": "SECRET-DECISION",
            "reason": "SECRET-REASON",
            "evidence": "SECRET-EVIDENCE",
        }
    }
    report = with_verbose_items(
        {"enabled": True, "final_status": "blocked"},
        plan_items(),
        assessment(
            projection,
            blockers=(blocker("PLAN_PROOF_MISSING", "P-001", "VERIFYING"),),
        ),
    )
    serialized = json.dumps(report)

    for secret in (
        "SECRET-JOURNAL",
        "SECRET-SEQUENCE",
        "SECRET-PROOF",
        "SECRET-DECISION",
        "SECRET-REASON",
        "SECRET-EVIDENCE",
        "SECRET blocker message",
    ):
        assert secret not in serialized

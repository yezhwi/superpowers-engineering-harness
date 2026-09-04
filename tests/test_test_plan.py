"""Structured Test Plan policy tests.

Each test names a planning defect that must block a STANDARD/STRICT task before
implementation. Fixtures use literal persisted-document shapes, not validator
helpers, so validator policy cannot make its own assertions tautological.
"""

from harness.test_plan import validate_test_plan


def requirement(*, requirement_type="feature", test_plan=None):
    return {
        "id": "REQ-001",
        "statement": "orders can be cancelled",
        "priority": "must",
        "status": "pending",
        "type": requirement_type,
        **({"test_plan": test_plan} if test_plan is not None else {}),
    }


def invariant(*, invariant_id="INV-001", severity="critical", test_plan=None):
    return {
        "id": invariant_id,
        "statement": "an order is refunded at most once",
        "category": "idempotency",
        "severity": severity,
        "status": "pending",
        "verification": [],
        **({"test_plan": test_plan} if test_plan is not None else {}),
    }


def case(case_id, case_type, strategy):
    return {
        "id": case_id,
        "type": case_type,
        "strategy": strategy,
        "description": "expected behavior",
    }


def plan(strategies, *cases):
    return {"strategies": list(strategies), "cases": list(cases)}


def issue_codes(requirements=None, invariants=None):
    issues = validate_test_plan(
        {"requirements": requirements or []}, {"invariants": invariants or []}
    )
    return {issue.code for issue in issues}


def test_requirement_without_test_plan_strategy_is_rejected():
    """Break caught: implementation begins with no declared verification method."""
    assert issue_codes(
        requirements=[
            requirement(test_plan=plan([], case("TC-001", "happy_path", "unit")))
        ]
    ) == {"TEST_PLAN_REQUIREMENT_STRATEGY_MISSING", "TEST_PLAN_CASE_STRATEGY_MISMATCH"}


def test_requirement_priority_cannot_disable_test_plan_validation():
    """Break caught: downgrading priority bypasses the Final Gate."""
    optional = requirement()
    optional["priority"] = "should"
    assert issue_codes(requirements=[optional]) == {
        "TEST_PLAN_REQUIREMENT_STRATEGY_MISSING"
    }


def test_critical_invariant_without_case_is_rejected():
    """Break caught: critical invariant has a method label but no scenario."""
    assert issue_codes(invariants=[invariant(test_plan=plan(["integration"]))]) == {
        "TEST_PLAN_CRITICAL_INVARIANT_UNCOVERED"
    }


def test_bugfix_without_regression_case_is_rejected():
    """Break caught: bug fix can pass planning with only happy-path protection."""
    assert issue_codes(
        requirements=[
            requirement(
                requirement_type="bugfix",
                test_plan=plan(["unit"], case("TC-001", "happy_path", "unit")),
            )
        ]
    ) == {"TEST_PLAN_REGRESSION_REQUIRED"}


def test_case_id_is_unique_across_requirement_and_invariant_documents():
    """Break caught: one TC identifier ambiguously links two proof obligations."""
    assert issue_codes(
        requirements=[
            requirement(test_plan=plan(["unit"], case("TC-001", "happy_path", "unit")))
        ],
        invariants=[
            invariant(
                test_plan=plan(
                    ["integration"], case("TC-001", "invariant", "integration")
                )
            )
        ],
    ) == {"TEST_PLAN_CASE_DUPLICATE"}


def test_case_strategy_must_be_declared_by_its_parent_plan():
    """Break caught: case claims integration proof outside parent unit strategy."""
    assert issue_codes(
        requirements=[
            requirement(
                test_plan=plan(["unit"], case("TC-001", "happy_path", "integration"))
            )
        ]
    ) == {"TEST_PLAN_CASE_STRATEGY_MISMATCH"}


def test_valid_feature_bugfix_and_critical_invariant_plan_passes():
    """Break caught: validator rejects complete plan needed to enter implementation."""
    assert (
        issue_codes(
            requirements=[
                requirement(
                    test_plan=plan(["unit"], case("TC-001", "happy_path", "unit"))
                ),
                {
                    **requirement(
                        requirement_type="bugfix",
                        test_plan=plan(
                            ["regression"], case("TC-002", "regression", "regression")
                        ),
                    ),
                    "id": "REQ-002",
                },
            ],
            invariants=[
                invariant(
                    test_plan=plan(
                        ["integration"], case("TC-003", "invariant", "integration")
                    )
                )
            ],
        )
        == set()
    )

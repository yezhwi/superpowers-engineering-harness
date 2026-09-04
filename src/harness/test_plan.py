"""Structured Test Plan policy shared by transition and quality gates."""

from dataclasses import dataclass


VALID_STRATEGIES = frozenset(
    {
        "unit",
        "integration",
        "e2e",
        "regression",
        "concurrency",
        "security",
        "contract",
        "manual",
    }
)
AUTOMATED_STRATEGIES = VALID_STRATEGIES - {"manual"}


@dataclass(frozen=True)
class TestPlanIssue:
    code: str
    message: str
    requirement_id: str | None = None
    invariant_id: str | None = None
    test_case_id: str | None = None


def validate_test_plan(requirements: dict, invariants: dict) -> list[TestPlanIssue]:
    """Return planning defects that block STANDARD/STRICT implementation entry."""
    issues: list[TestPlanIssue] = []
    seen_case_ids: set[str] = set()

    def issue(
        code: str,
        message: str,
        *,
        requirement_id=None,
        invariant_id=None,
        test_case_id=None,
    ) -> None:
        issues.append(
            TestPlanIssue(
                code,
                message,
                requirement_id=requirement_id,
                invariant_id=invariant_id,
                test_case_id=test_case_id,
            )
        )

    def inspect_cases(
        record: dict, plan: dict, *, requirement_id=None, invariant_id=None
    ) -> list[dict]:
        strategies = plan.get("strategies") or []
        cases = plan.get("cases") or []
        for test_case in cases:
            case_id = test_case.get("id")
            if case_id in seen_case_ids:
                issue(
                    "TEST_PLAN_CASE_DUPLICATE",
                    f"duplicate test case {case_id}",
                    requirement_id=requirement_id,
                    invariant_id=invariant_id,
                    test_case_id=case_id,
                )
            else:
                seen_case_ids.add(case_id)
            if test_case.get("strategy") not in strategies:
                issue(
                    "TEST_PLAN_CASE_STRATEGY_MISMATCH",
                    f"{case_id} strategy is not declared by its parent test plan",
                    requirement_id=requirement_id,
                    invariant_id=invariant_id,
                    test_case_id=case_id,
                )
        return cases

    for requirement in requirements.get("requirements", []):
        requirement_id = requirement.get("id")
        plan = requirement.get("test_plan") or {}
        strategies = plan.get("strategies") or []
        cases = inspect_cases(requirement, plan, requirement_id=requirement_id)
        if not strategies:
            issue(
                "TEST_PLAN_REQUIREMENT_STRATEGY_MISSING",
                f"{requirement_id} has no test plan strategy",
                requirement_id=requirement_id,
            )
        if set(strategies) & AUTOMATED_STRATEGIES and not cases:
            issue(
                "TEST_PLAN_AUTOMATED_CASE_REQUIRED",
                f"{requirement_id} has an automated strategy without a test case",
                requirement_id=requirement_id,
            )
        if requirement.get("type", "feature") == "bugfix" and not any(
            test_case.get("type") == "regression" for test_case in cases
        ):
            issue(
                "TEST_PLAN_REGRESSION_REQUIRED",
                f"{requirement_id} bugfix has no regression test case",
                requirement_id=requirement_id,
            )

    for invariant in invariants.get("invariants", []):
        invariant_id = invariant.get("id")
        plan = invariant.get("test_plan") or {}
        strategies = plan.get("strategies") or []
        cases = inspect_cases(invariant, plan, invariant_id=invariant_id)
        if invariant.get("severity") == "critical" and (not strategies or not cases):
            issue(
                "TEST_PLAN_CRITICAL_INVARIANT_UNCOVERED",
                f"{invariant_id} critical invariant has no complete test plan",
                invariant_id=invariant_id,
            )

    return issues


def validate_test_coverage(
    requirements: dict, invariants: dict, evidence_records, evidence_is_fresh
) -> list[TestPlanIssue]:
    """Return final-Gate defects for bindings missing fresh successful proof."""
    issues: list[TestPlanIssue] = []

    def issue(
        code: str,
        message: str,
        *,
        requirement_id=None,
        invariant_id=None,
        test_case_id=None,
    ) -> None:
        issues.append(
            TestPlanIssue(
                code,
                message,
                requirement_id=requirement_id,
                invariant_id=invariant_id,
                test_case_id=test_case_id,
            )
        )

    def covered(node_id: str) -> bool:
        return any(
            node_id in record.get("covered_tests", []) and evidence_is_fresh(record)
            for record in evidence_records
        )

    def has_manual_evidence(case_id: str) -> bool:
        return any(
            case_id in record.get("covered_test_cases", [])
            and evidence_is_fresh(record)
            for record in evidence_records
        )

    def inspect(document: dict, key: str) -> None:
        for record in document.get(key, []):
            record_id = record.get("id")
            for test_case in (record.get("test_plan") or {}).get("cases", []):
                identity = (
                    {"requirement_id": record_id}
                    if key == "requirements"
                    else {"invariant_id": record_id}
                )
                case_id = test_case.get("id")
                strategy = test_case.get("strategy")
                tests = test_case.get("tests") or []
                if strategy == "manual":
                    if not has_manual_evidence(case_id):
                        issue(
                            "TEST_EVIDENCE_MISSING",
                            f"{case_id} manual case has no fresh evidence",
                            test_case_id=case_id,
                            **identity,
                        )
                elif not tests:
                    issue(
                        "TEST_BINDING_MISSING",
                        f"{case_id} has no executable test binding",
                        test_case_id=case_id,
                        **identity,
                    )
                elif any(not covered(node_id) for node_id in tests):
                    issue(
                        "TEST_EVIDENCE_MISSING",
                        f"{case_id} binding has no fresh covering evidence",
                        test_case_id=case_id,
                        **identity,
                    )

    inspect(requirements, "requirements")
    inspect(invariants, "invariants")
    return issues

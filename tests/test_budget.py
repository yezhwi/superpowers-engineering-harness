import pytest

from harness.budget import BudgetOverrideRequired, check_budget, record_budget


def fast_task(test_runs=0):
    return {"risk": {"profile": "FAST"}, "budget": {"test_runs": test_runs, "build_runs": 0, "retry_runs": 0, "overrides": []}}


def test_fast_test_limit_requires_complete_override():
    with pytest.raises(BudgetOverrideRequired):
        check_budget(fast_task(2), "test", None)


def test_standard_budget_is_unlimited():
    task = fast_task(999); task["risk"]["profile"] = "STANDARD"
    check_budget(task, "test", None)


def test_valid_override_is_audited():
    task = fast_task(2)
    override = {"reason": "new consumer", "evidence": "unit-test.json", "hypothesis": "shared path"}
    check_budget(task, "test", override)
    record_budget(task, "test", override)
    assert task["budget"]["overrides"][-1] == {"action": "test", **override}

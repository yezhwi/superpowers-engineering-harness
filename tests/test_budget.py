import subprocess
import sys

import pytest
import yaml

from harness.budget import BudgetOverrideRequired, budget_action, check_budget, record_budget


def fast_task(test_runs=0):
    return {"risk": {"profile": "FAST"}, "budget": {"test_runs": test_runs, "build_runs": 0, "retry_runs": 0, "overrides": []}}


def test_budget_action_classifies_observable_evidence():
    assert budget_action("unit_test", 0, "pytest") == "test"
    assert budget_action("build", 0, "python -m pip wheel .") == "build"
    assert budget_action("lint", 0, "ruff") is None


def test_over_budget_evidence_does_not_execute_command(tmp_path):
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "current-task.yaml").write_text(yaml.safe_dump(fast_task(2)))
    marker = tmp_path / "ran"
    result = subprocess.run([
        sys.executable, "scripts/collect_evidence.py", "--harness-dir", str(harness_dir),
        "--type", "unit_test", "--scope", "related", "--covered-test", "tests/x.py",
        "--command", f"sh -c 'echo ran > {marker}'",
    ], capture_output=True, text=True)

    assert result.returncode == 2
    assert "BUDGET_OVERRIDE_REQUIRED" in result.stderr
    assert not marker.exists()


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

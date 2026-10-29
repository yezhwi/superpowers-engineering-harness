"""Verification batches rerun failures and affected scope, and keep RED history."""

import pytest

from harness.execution_proof import valid
from harness.verification_batch import Batch, BatchPlanError, append_observation, plan_batches, progress, rerun

NODE_A = "tests/test_a.py::test_a"
NODE_B = "tests/test_b.py::test_b"


def _batch(batch_id, node, resources=()):
    return Batch(batch_id, node.split("::", 1)[0], f"reports/{batch_id}.json", (node,), frozenset(resources))


def _success(node):
    run = {"collected": [node], "passed": [node], "failed": [], "skipped": [],
           "assertion_failures": [], "errors": 0, "exit_code": 0}
    return {"exit_code": 0, "covered_tests": [node], "test_execution": {"schema": "pytest-execution/v1", "runs": [run]}}


def _plan():
    return plan_batches(
        (_batch("b1", NODE_A, ("database",)), _batch("b2", NODE_B, ("database",)), _batch("b3", "tests/test_c.py::test_c")),
        historical_obligations=("TASK-115",),
    )


def test_shared_resource_is_serial_and_rerun_is_exact():
    planned = _plan()
    assert planned.required_tests == (NODE_A, NODE_B, "tests/test_c.py::test_c")
    assert planned.serial_groups == (("b1", "b2"),)
    assert rerun(planned, changed=("src/a.py",), owners={NODE_A: ["src/a.py"], NODE_B: ["src/b.py"]}) == ("b1",)
    assert rerun(planned, failed=("b2",)) == ("b2",)
    assert rerun(planned, changed=("src/a.py",), failed=("b2",), owners={NODE_A: ["src/a.py"]}) == ("b1", "b2")


def test_invalid_receipt_cannot_be_reused_and_red_history_remains():
    planned = _plan()
    assert rerun(planned, receipts={"b3": {"exit_code": 0}}) == ("b3",)
    assert rerun(planned, receipts={"b1": _success(NODE_A)}) == ()
    assert valid(_success(NODE_A), True)
    red = {"exit_code": 1, "command": "pytest tests/test_a.py"}
    green = _success(NODE_A)
    assert append_observation((red,), green) == (red, green)
    state = progress(planned, passed_batches=("b1",), historical_open=("TASK-115",))
    assert state["partial_done"] is False
    assert state["increment_complete"] is False
    assert state["historical_obligations"] == ["TASK-115"]


def test_plan_rejects_a_file_map_and_unknown_resource():
    with pytest.raises(BatchPlanError):
        plan_batches((Batch("b1", "tests/a.py", "reports/../a.json", (NODE_A,), frozenset()),))
    with pytest.raises(BatchPlanError):
        plan_batches((_batch("b1", NODE_A, ("cluster",)),))

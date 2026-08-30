import yaml

from fixtures.harness import make_harness
from harness.diagnosability import load_contract


def test_make_harness_persists_requested_task_and_contract(tmp_path):
    harness = make_harness(tmp_path, risk="Q3", task_type="bugfix", observability="required")

    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    assert task["risk"]["level"] == "Q3"
    assert task["task"]["type"] == "bugfix"
    assert load_contract(harness, task_type="bugfix")["required"] is True

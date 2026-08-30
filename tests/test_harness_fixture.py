from pathlib import Path

import yaml

from fixtures.harness import make_complete_harness, make_harness
from harness.diagnosability import load_contract


def test_make_complete_harness_is_gate_ready_baseline(tmp_path):
    harness = make_complete_harness(Path(__file__).resolve().parent.parent, tmp_path)
    assert (harness / "requirements.yaml").is_file()
    assert (harness / "invariants.yaml").is_file()
    assert (harness / "evidence/build.json").is_file()


def test_make_harness_persists_requested_task_and_contract(tmp_path):
    harness = make_harness(tmp_path, risk="Q3", task_type="bugfix", observability="required")

    task = yaml.safe_load((harness / "current-task.yaml").read_text())
    assert task["risk"]["level"] == "Q3"
    assert task["task"]["type"] == "bugfix"
    assert load_contract(harness, task_type="bugfix")["required"] is True

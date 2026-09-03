from pathlib import Path

import yaml

from test_quality_gate import make_harness


def test_proposed_decision_blocks_gate_preflight(tmp_path: Path):
    """Break caught: Gate permits unresolved consequential user decision."""
    from harness.decision import propose
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    task_path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-042"
    task_path.write_text(yaml.safe_dump(task))
    propose(harness_dir, {
        "topic": "cache", "question": "Which cache?", "context": ["Redis exists"],
        "options": [{"id": "redis", "description": "shared cache"}],
        "recommendation": {"option": "redis", "reasons": ["existing"], "tradeoffs": []},
        "scope": [], "constraints": [],
    })

    status, blockers = run_gate(harness_dir, allow_preflight=True)

    assert status == "BLOCKED"
    assert any(blocker.code == "DECISION_UNRESOLVED" for blocker in blockers)

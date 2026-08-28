"""Public lifecycle acceptance for Test Plan traceability."""

import json

import yaml

from test_convergence_cli import make_repo, run_cli


NODE = "tests/test_test_plan.py::test_valid_feature_bugfix_and_critical_invariant_plan_passes"


def test_bound_case_with_fresh_evidence_reaches_done(tmp_path):
    """Break caught: traceable plan/evidence cannot complete normal Harness lifecycle."""
    harness_dir = make_repo(tmp_path, state="GATING")
    requirement_path = harness_dir / "requirements.yaml"
    requirements = yaml.safe_load(requirement_path.read_text())
    requirements["requirements"][0]["test_plan"] = {
        "strategies": ["integration"],
        "cases": [{
            "id": "TC-001", "type": "happy_path", "strategy": "integration",
            "description": "bound test passes", "tests": [NODE],
        }],
    }
    requirement_path.write_text(yaml.safe_dump(requirements))

    build = json.loads((harness_dir / "evidence" / "build.json").read_text())
    build["type"] = "integration_test"
    build["covered_tests"] = [NODE]
    (harness_dir / "evidence" / "case-evidence.json").write_text(json.dumps(build))

    gate = run_cli(tmp_path, "gate")
    done = run_cli(tmp_path, "transition", "DONE")

    assert gate.returncode == 0, gate.stdout + gate.stderr
    assert done.returncode == 0, done.stdout + done.stderr
    assert yaml.safe_load((harness_dir / "current-task.yaml").read_text())["state"] == "DONE"

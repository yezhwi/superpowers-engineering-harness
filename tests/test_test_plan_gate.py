"""Final Gate Test Plan coverage integration tests."""

import json

import pytest
import yaml

from evidence_factory import write_evidence
from test_quality_gate import REPO, make_harness

NODE_A = "tests/test_orders.py::test_cancel"
NODE_B = "tests/test_orders.py::test_refund"


def configure_requirement_case(harness_dir, *, tests):
    path = harness_dir / "requirements.yaml"
    document = yaml.safe_load(path.read_text())
    document["requirements"][0]["test_plan"] = {
        "strategies": ["integration"],
        "cases": [
            {
                "id": "TC-001",
                "type": "happy_path",
                "strategy": "integration",
                "description": "order cancellation works",
                "tests": tests,
            }
        ],
    }
    path.write_text(yaml.safe_dump(document))


def integration_evidence(harness_dir, name, covered_tests):
    source = json.loads((harness_dir / "evidence" / "build.json").read_text())
    source["type"] = "integration_test"
    source["covered_tests"] = covered_tests
    (harness_dir / "evidence" / name).write_text(json.dumps(source))


def blocker_codes(blockers):
    return {blocker.code for blocker in blockers}


def test_gate_blocks_deleted_critical_invariant_test_plan(tmp_path):
    """Break caught: implementation deletes critical proof plan after entry Gate."""
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    invariant_path = harness_dir / "invariants.yaml"
    invariants = yaml.safe_load(invariant_path.read_text())
    invariants["invariants"][0]["test_plan"] = {
        "strategies": ["integration"],
        "cases": [
            {
                "id": "TC-099",
                "type": "invariant",
                "strategy": "integration",
                "description": "holds",
                "tests": [NODE_A],
            }
        ],
    }
    del invariants["invariants"][0]["test_plan"]
    invariant_path.write_text(yaml.safe_dump(invariants))

    status, blockers = run_gate(harness_dir)

    assert status == "BLOCKED"
    assert blocker_codes(blockers) == {"TEST_PLAN_INCOMPLETE"}


@pytest.mark.parametrize(
    "priority,status",
    [
        ("must", "pending"),
        ("must", "verified"),
        ("should", "pending"),
        ("should", "verified"),
        ("could", "pending"),
        ("could", "verified"),
    ],
)
def test_gate_blocks_deleted_requirement_test_plan_for_all_priority_statuses(
    tmp_path, priority, status
):
    """Break caught: mutable Requirement metadata bypasses Plan validation."""
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    path = harness_dir / "requirements.yaml"
    requirements = yaml.safe_load(path.read_text())
    requirement = requirements["requirements"][0]
    requirement["priority"] = priority
    requirement["status"] = status
    del requirement["test_plan"]
    path.write_text(yaml.safe_dump(requirements))

    gate_status, blockers = run_gate(harness_dir)

    assert gate_status == "BLOCKED"
    assert "TEST_PLAN_INCOMPLETE" in blocker_codes(blockers)


def test_gate_blocks_manual_case_without_explicit_case_evidence(tmp_path):
    """Break caught: unrelated fresh build evidence proves a manual case."""
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    configure_requirement_case(harness_dir, tests=[])
    requirements_path = harness_dir / "requirements.yaml"
    requirements = yaml.safe_load(requirements_path.read_text())
    requirements["requirements"][0]["test_plan"]["strategies"] = ["manual"]
    requirements["requirements"][0]["test_plan"]["cases"][0]["strategy"] = "manual"
    requirements_path.write_text(yaml.safe_dump(requirements))

    status, blockers = run_gate(harness_dir)

    assert status == "BLOCKED"
    assert blocker_codes(blockers) == {"TEST_EVIDENCE_MISSING"}


def test_gate_accepts_manual_case_with_explicit_case_evidence(tmp_path):
    """Break caught: valid manual verification remains permanently blocked."""
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    configure_requirement_case(harness_dir, tests=[])
    requirements_path = harness_dir / "requirements.yaml"
    requirements = yaml.safe_load(requirements_path.read_text())
    requirements["requirements"][0]["test_plan"]["strategies"] = ["manual"]
    requirements["requirements"][0]["test_plan"]["cases"][0]["strategy"] = "manual"
    requirements_path.write_text(yaml.safe_dump(requirements))
    manual = json.loads((harness_dir / "evidence" / "build.json").read_text())
    manual["covered_test_cases"] = ["TC-001"]
    (harness_dir / "evidence" / "manual.json").write_text(json.dumps(manual))

    status, blockers = run_gate(harness_dir)

    assert status == "PASS"
    assert blockers == []


def test_gate_blocks_automated_case_without_executable_binding(tmp_path):
    """Break caught: plan claims automation but no test can execute it."""
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    configure_requirement_case(harness_dir, tests=[])

    status, blockers = run_gate(harness_dir)

    assert status == "BLOCKED"
    assert blocker_codes(blockers) == {"TEST_BINDING_MISSING"}


def test_gate_blocks_binding_without_fresh_covered_evidence(tmp_path):
    """Break caught: passing unrelated command is treated as case proof."""
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    configure_requirement_case(harness_dir, tests=[NODE_A])
    integration_evidence(harness_dir, "integration.json", [])

    status, blockers = run_gate(harness_dir)

    assert status == "BLOCKED"
    assert blocker_codes(blockers) == {"TEST_EVIDENCE_MISSING"}


def test_gate_uses_multiple_same_type_evidence_records_for_case_coverage(tmp_path):
    """Break caught: type-keyed Evidence map drops proof for one of two cases."""
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    configure_requirement_case(harness_dir, tests=[NODE_A, NODE_B])
    integration_evidence(harness_dir, "case-a.json", [NODE_A])
    integration_evidence(harness_dir, "case-b.json", [NODE_B])

    status, blockers = run_gate(harness_dir)

    assert status == "PASS"
    assert blockers == []

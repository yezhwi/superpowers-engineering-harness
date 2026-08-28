"""Final Gate Test Plan coverage integration tests."""

import json

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
        "cases": [{
            "id": "TC-001", "type": "happy_path", "strategy": "integration",
            "description": "order cancellation works", "tests": tests,
        }],
    }
    path.write_text(yaml.safe_dump(document))


def integration_evidence(harness_dir, name, covered_tests):
    source = json.loads((harness_dir / "evidence" / "build.json").read_text())
    source["type"] = "integration_test"
    source["covered_tests"] = covered_tests
    (harness_dir / "evidence" / name).write_text(json.dumps(source))


def blocker_codes(blockers):
    return {blocker.code for blocker in blockers}


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

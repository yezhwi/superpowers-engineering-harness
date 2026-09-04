from pathlib import Path

import yaml

from test_quality_gate import make_harness


def test_declared_external_interface_without_contract_blocks_gate(tmp_path: Path):
    """Break caught: declared public interface reaches Gate without contract."""
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    (harness_dir / "impact.yaml").write_text(
        yaml.safe_dump(
            {
                "impact": {
                    "changed": [],
                    "direct_dependents": [],
                    "contracts": [],
                    "risks": [],
                    "required_tests": [],
                    "full_suite": {"recommended": False, "reason": None},
                    "interfaces": [
                        {
                            "id": "INT-001",
                            "kind": "cli",
                            "visibility": "external",
                            "consumers": ["agent"],
                            "compatibility": "compatible",
                            "affected_contracts": [],
                            "contract_id": "INT-001",
                        }
                    ],
                }
            }
        )
    )

    status, blockers = run_gate(harness_dir, allow_preflight=True)

    assert status == "BLOCKED"
    assert any(blocker.code == "INTERFACE_CONTRACT_MISSING" for blocker in blockers)


def test_stale_interface_verification_blocks_gate(tmp_path: Path):
    """Break caught: stale proof satisfies external contract verification."""
    from harness.interface_contract import declare, verify
    from harness.quality_gate import run_gate

    harness_dir = make_harness(tmp_path)
    task_path = harness_dir / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-042"
    task_path.write_text(yaml.safe_dump(task))
    contract = declare(
        harness_dir,
        {
            "name": "api",
            "kind": "cli",
            "visibility": "external",
            "consumers": ["agent"],
            "inputs": {"description": "input"},
            "outputs": {"description": "output"},
            "errors": {"description": "error"},
            "compatibility": {
                "classification": "compatible",
                "rationale": "additive",
                "migration": None,
            },
            "versioning": {"required": False, "strategy": None},
            "observability": {"contract": "observability.yaml"},
            "decision_refs": [],
            "verification": [],
        },
    )
    verify(harness_dir, contract["id"], "build.json")
    record = __import__("json").loads(
        (harness_dir / "evidence" / "build.json").read_text()
    )
    record["commit"] = "0" * 40
    (harness_dir / "evidence" / "build.json").write_text(
        __import__("json").dumps(record)
    )
    (harness_dir / "impact.yaml").write_text(
        yaml.safe_dump(
            {
                "impact": {
                    "changed": [],
                    "direct_dependents": [],
                    "contracts": [],
                    "risks": [],
                    "required_tests": [],
                    "full_suite": {"recommended": False, "reason": None},
                    "interfaces": [
                        {
                            "id": contract["id"],
                            "kind": "cli",
                            "visibility": "external",
                            "consumers": ["agent"],
                            "compatibility": "compatible",
                            "affected_contracts": [],
                            "contract_id": contract["id"],
                        }
                    ],
                }
            }
        )
    )

    _, blockers = run_gate(harness_dir, allow_preflight=True)

    assert any(blocker.code == "INTERFACE_VERIFICATION_MISSING" for blocker in blockers)


def test_private_task_has_no_interface_gate_blocker(tmp_path: Path):
    """Break caught: private-only task is forced into interface ceremony."""
    from harness.quality_gate import run_gate

    status, blockers = run_gate(make_harness(tmp_path), allow_preflight=True)

    assert status == "PASS"
    assert not any(blocker.code.startswith("INTERFACE_") for blocker in blockers)

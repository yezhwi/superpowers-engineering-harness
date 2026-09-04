from pathlib import Path

import pytest
import yaml

from harness.init import init_harness


def setup_harness(path: Path) -> Path:
    init_harness(path)
    task_path = path / ".harness" / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["task"]["id"] = "TASK-042"
    task_path.write_text(yaml.safe_dump(task))
    return path / ".harness"


def contract(**overrides) -> dict:
    return {
        "name": "decision-api",
        "kind": "cli",
        "visibility": "external",
        "consumers": ["agent-worker"],
        "inputs": {"description": "command arguments"},
        "outputs": {"description": "machine-readable result"},
        "errors": {"description": "stable error code; not retryable"},
        "compatibility": {
            "classification": "compatible",
            "rationale": "additive commands",
            "migration": None,
        },
        "versioning": {"required": False, "strategy": None},
        "observability": {"contract": "observability.yaml"},
        "decision_refs": [],
        "verification": [],
        **overrides,
    }


def test_declare_persists_schema_valid_external_contract(tmp_path):
    """Break caught: public boundary has no durable consumer contract."""
    from harness.interface_contract import declare, load_interface_contract

    harness_dir = setup_harness(tmp_path)
    declared = declare(harness_dir, contract())

    assert declared["id"] == "INT-001"
    assert declared["task_id"] == "TASK-042"
    assert load_interface_contract(harness_dir, "INT-001")["consumers"] == [
        "agent-worker"
    ]


def test_breaking_contract_requires_explicit_approval(tmp_path):
    """Break caught: known breaking public change silently becomes approved."""
    from harness.interface_contract import approve_breaking, declare

    harness_dir = setup_harness(tmp_path)
    declared = declare(
        harness_dir,
        contract(
            compatibility={
                "classification": "breaking",
                "rationale": "rename command",
                "migration": "clients migrate",
            }
        ),
    )

    assert declared["breaking_change_approved"] is False
    approved = approve_breaking(harness_dir, declared["id"], "user approved migration")
    assert approved["breaking_change_approved"] is True
    assert approved["breaking_change_reason"] == "user approved migration"


def test_interface_verification_rejects_noncanonical_evidence_reference(tmp_path):
    """Break caught: Interface contract stores unvalidated evidence path strings."""
    from harness.interface_contract import InterfaceContractError, declare, verify

    harness_dir = setup_harness(tmp_path)
    declared = declare(harness_dir, contract())

    with pytest.raises(InterfaceContractError, match="EVIDENCE_REFERENCE_INVALID"):
        verify(harness_dir, declared["id"], "../outside.json")


def test_external_contract_rejects_missing_consumers(tmp_path):
    """Break caught: external contract lacks identified dependent consumer."""
    from harness.interface_contract import InterfaceContractError, declare

    with pytest.raises(InterfaceContractError, match="INTERFACE_CONTRACT_INVALID"):
        declare(setup_harness(tmp_path), contract(consumers=[]))

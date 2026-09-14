"""Migrated artifact control reads; package schema access remains separate."""

import hashlib
import inspect

import pytest
import test_context_builder
from source_boundary_checks import direct_io_lines
from test_decision import proposal
from test_interface_contract import contract

from harness import decision, interface_contract
from harness.context.model import ContextBuildError
from harness.source_access import source_scope

harness = test_context_builder.harness


@pytest.mark.parametrize(
    "function",
    [
        decision._task_id,
        decision.load_decisions,
        decision.load_decision,
        interface_contract._task_id,
        interface_contract.load_interface_contracts,
        interface_contract.load_interface_contract,
    ],
)
def test_artifact_control_loaders_have_no_direct_io(function):
    source = "from harness import source_access\n" + inspect.getsource(function)
    assert direct_io_lines(source) == []


@pytest.mark.parametrize("kind", ["decision", "interface"])
def test_artifact_loaders_observe_bytes_members_and_task(harness, kind):
    if kind == "decision":
        record = decision.propose(harness, proposal())
        directory = harness / "decisions"
        load_many, load_one, task_id = (
            decision.load_decisions,
            decision.load_decision,
            decision._task_id,
        )
        pattern = "DEC-*.yaml"
    else:
        record = interface_contract.declare(harness, contract())
        directory = harness / "interface-contracts"
        load_many, load_one, task_id = (
            interface_contract.load_interface_contracts,
            interface_contract.load_interface_contract,
            interface_contract._task_id,
        )
        pattern = "INT-*.yaml"
    path = directory / f"{record['id']}.yaml"
    expected_hash = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    with source_scope(
        harness, allowed=[directory, path, harness / "current-task.yaml"]
    ) as observed:
        assert load_many(harness) == [record]
        assert load_one(harness, record["id"]) == record
        assert task_id(harness) == "TASK-028"
    snapshot = observed.snapshot()
    assert snapshot[path.relative_to(harness).as_posix()]["bytes"] == expected_hash
    assert snapshot[directory.name][f"members:{pattern}"] == (path.name,)
    assert "bytes" in snapshot["current-task.yaml"]
    schema_name = (
        "decision.schema.json"
        if kind == "decision"
        else "interface-contract.schema.json"
    )
    assert schema_name in observed.resource_snapshot()


@pytest.mark.parametrize("kind", ["decision", "interface"])
def test_enumeration_cannot_grant_artifact_read_authority(harness, kind):
    if kind == "decision":
        decision.propose(harness, proposal())
        directory, load = harness / "decisions", decision.load_decisions
    else:
        interface_contract.declare(harness, contract())
        directory, load = (
            harness / "interface-contracts",
            interface_contract.load_interface_contracts,
        )
    with (
        pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"),
        source_scope(harness, allowed=[directory]),
    ):
        load(harness)


@pytest.mark.parametrize("kind", ["decision", "interface"])
def test_loaded_artifact_deleted_before_scope_exit_is_stale(harness, kind):
    if kind == "decision":
        record = decision.propose(harness, proposal())
        directory, load = harness / "decisions", decision.load_decision
    else:
        record = interface_contract.declare(harness, contract())
        directory, load = (
            harness / "interface-contracts",
            interface_contract.load_interface_contract,
        )
    path = directory / f"{record['id']}.yaml"
    with (
        pytest.raises(ContextBuildError, match="CONTEXT_STALE"),
        source_scope(harness, allowed=[path]),
    ):
        assert load(harness, record["id"]) == record
        path.unlink()


@pytest.mark.parametrize("kind", ["decision", "interface"])
def test_missing_artifact_directory_is_observed(tmp_path, kind):
    directory = tmp_path / (
        "decisions" if kind == "decision" else "interface-contracts"
    )
    load = (
        decision.load_decisions
        if kind == "decision"
        else interface_contract.load_interface_contracts
    )
    with source_scope(tmp_path, allowed=[directory]) as observed:
        assert load(tmp_path) == []
    assert observed.snapshot()[directory.name]["is_dir"] is False

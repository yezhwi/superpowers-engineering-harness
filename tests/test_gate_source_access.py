"""Gate read-side migration contract; does not activate production scopes."""

import inspect

import pytest
import test_context_builder
from source_boundary_checks import direct_io_lines
from test_context_integrity import add_core_records

from harness import quality_gate
from harness.source_access import source_scope

harness = test_context_builder.harness


@pytest.mark.parametrize(
    "function",
    [
        quality_gate._load_yaml,
        quality_gate.load_evidence,
        quality_gate.load_findings,
        quality_gate.run_fast_gate,
        quality_gate._evaluate_gate,
    ],
)
def test_gate_read_functions_have_no_direct_io(function):
    assert direct_io_lines(inspect.getsource(function)) == []


def test_gate_contract_loaders_observe_sources(harness):
    add_core_records(harness)
    allowed = [p for p in harness.rglob("*")] + [harness]
    with source_scope(harness, allowed=allowed) as observed:
        assert (
            quality_gate._load_yaml(harness / "current-task.yaml")["task"]["id"]
            == "TASK-028"
        )
        assert quality_gate.load_findings(harness / "findings")
        quality_gate.load_evidence(harness / "evidence")
    snapshot = observed.snapshot()
    assert "bytes" in snapshot["current-task.yaml"]
    assert "members:*.yaml" in snapshot["findings"]
    assert "members:*.json" in snapshot["evidence"]

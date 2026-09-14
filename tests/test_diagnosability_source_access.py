"""Diagnosability source closure reads use observed interfaces."""

# Keep loader error assertions distinct from scope-exit validation.
# ruff: noqa: SIM117

import inspect

import pytest
from source_boundary_checks import direct_io_lines

from harness import diagnosability
from harness.context.model import ContextBuildError
from harness.source_access import source_scope


def test_diagnosability_has_no_direct_file_reads():
    assert direct_io_lines(inspect.getsource(diagnosability)) == []


def test_contract_loader_observes_bytes_and_schema(tmp_path):
    path = tmp_path / "observability.yaml"
    # Use shipped contract so this test targets I/O rather than schema fixtures.
    from harness.templates import templates_dir

    path.write_bytes((templates_dir() / "observability.yaml").read_bytes())
    with source_scope(tmp_path, allowed=[path]) as observed:
        document = diagnosability.load_contract(tmp_path)
        assert document["required"] is False
    assert "bytes" in observed.snapshot()[path.name]
    assert "observability.schema.json" in observed.resource_snapshot()


def test_swallowed_contract_read_error_still_rejects_scope(tmp_path):
    with (
        pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"),
        source_scope(tmp_path, allowed=[]),
    ):
        try:
            diagnosability.load_contract(tmp_path)
        except ValueError:
            pass


def test_invalid_review_records_schema_observation(tmp_path):
    with source_scope(tmp_path, allowed=[]) as observed:
        with pytest.raises(ValueError, match="DIAG_REVIEW_EVIDENCE_INVALID"):
            diagnosability.validate_review_evidence({})
    assert "diagnosability-review-evidence.schema.json" in observed.resource_snapshot()

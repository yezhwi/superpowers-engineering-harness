"""Evidence and Gate schema reads join the observed dependency set."""

# Distinguish loader failure handling from scope exit validation.
# ruff: noqa: SIM117

import hashlib
import json

import pytest

from harness import evidence_validator, quality_gate
from harness.source_access import source_scope


def test_evidence_projection_observes_record_and_schema(tmp_path):
    path = tmp_path / "test.json"
    content = json.dumps(
        {
            "type": "unit_test",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "command": "true",
            "exit_code": 0,
            "commit": "a" * 40,
            "workspace_fingerprint": "sha256:" + "b" * 64,
            "workspace_fingerprint_after": "sha256:" + "b" * 64,
        }
    ).encode()
    path.write_bytes(content)
    with source_scope(tmp_path, allowed=[path]) as observed:
        result = evidence_validator.project_evidence(
            path, "a" * 40, "sha256:" + "b" * 64
        )
        assert result.status == evidence_validator.EvidenceStatus.FRESH
    assert (
        observed.snapshot()[path.name]["bytes"]
        == "sha256:" + hashlib.sha256(content).hexdigest()
    )
    assert "evidence.schema.json" in observed.resource_snapshot()


def test_missing_evidence_is_observed_without_becoming_invalid(tmp_path):
    path = tmp_path / "missing.json"
    with source_scope(tmp_path, allowed=[path]) as observed:
        result = evidence_validator.project_evidence(path, "head", "workspace")
        assert result.status == evidence_validator.EvidenceStatus.MISSING
    assert observed.snapshot()[path.name]["is_file"] is False


def test_gate_schema_validation_observes_resources_even_on_invalid_record(tmp_path):
    with source_scope(tmp_path, allowed=[]) as observed:
        with pytest.raises(quality_gate.InvalidHarnessState):
            quality_gate.validate_schema({}, "task.schema.json", tmp_path / "task.yaml")
    assert "task.schema.json" in observed.resource_snapshot()


def test_migrated_evidence_and_gate_schema_have_no_direct_io():
    import inspect

    from source_boundary_checks import direct_io_lines

    assert direct_io_lines(inspect.getsource(evidence_validator)) == []
    assert direct_io_lines(inspect.getsource(quality_gate.validate_schema)) == []


def test_reuse_schema_validation_observes_resource(tmp_path):
    with source_scope(tmp_path, allowed=[]) as observed:
        assert evidence_validator._schema_valid({}) is False
    assert "evidence.schema.json" in observed.resource_snapshot()

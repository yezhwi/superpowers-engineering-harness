"""Observed Gate workspace helpers; Git fingerprint semantics stay unchanged."""

# Keep the expected path error distinct from scope-exit validation.
# ruff: noqa: SIM117

import inspect

import pytest
import test_context_builder
from source_boundary_checks import direct_io_lines

from harness import paths, workspace
from harness.source_access import source_scope

harness = test_context_builder.harness


@pytest.mark.parametrize(
    "function",
    [
        workspace.observability_inspected_paths,
        workspace.protected_paths_fingerprint,
        paths.evidence_path,
    ],
)
def test_gate_workspace_helpers_have_no_direct_io(function):
    assert direct_io_lines(inspect.getsource(function)) == []


def test_observability_contract_observed(harness):
    path = harness / "observability.yaml"
    path.write_text(
        "required: true\napplicability:\n  inspected_paths: ['src/main.py']\n"
    )
    with source_scope(harness, allowed=[path]) as observed:
        assert workspace.observability_inspected_paths(harness) == ("src/main.py",)
    assert "bytes" in observed.snapshot()[path.name]


def test_protected_file_bytes_are_observed(harness):
    root = harness.parent
    path = root / "protected.txt"
    path.write_text("user data")
    with source_scope(root, allowed=[path]) as observed:
        fingerprint = workspace.protected_paths_fingerprint((path.name,), root)
    assert fingerprint.startswith("sha256:")
    assert "bytes" in observed.snapshot()[path.name]


def test_invalid_evidence_reference_observes_candidate_directory(harness):
    directory = harness / "evidence"
    with source_scope(harness, allowed=[directory]) as observed:
        with pytest.raises(paths.EvidenceReferenceError):
            paths.evidence_path(harness, "../outside.json")
    assert "members:*.json" in observed.snapshot()["evidence"]

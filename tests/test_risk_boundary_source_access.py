"""FAST loader observes its source and cannot swallow a scope violation."""

# Keep inner loader exceptions distinct from outer scope-exit assertions.
# ruff: noqa: SIM117

import hashlib

import pytest

from harness.context.model import ContextBuildError
from harness.risk_boundaries import RiskBoundaryPolicyError, load_boundaries
from harness.source_access import source_scope


def test_risk_loader_records_bytes_used_for_policy(tmp_path):
    path = tmp_path / "risk-boundaries.yaml"
    content = b"boundaries:\n  q2: ['src/api/**']\n  q3: ['src/auth/**']\n"
    path.write_bytes(content)
    with source_scope(tmp_path, allowed=[path]) as observations:
        assert load_boundaries(path) == {"q2": ("src/api/**",), "q3": ("src/auth/**",)}
    assert (
        observations.snapshot()[path.name]["bytes"]
        == "sha256:" + hashlib.sha256(content).hexdigest()
    )


def test_swallowed_risk_loader_error_cannot_hide_undeclared_read(tmp_path):
    path = tmp_path / "risk-boundaries.yaml"
    path.write_text("boundaries: {}")
    with (
        pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"),
        source_scope(tmp_path, allowed=[]),
    ):
        with pytest.raises(
            RiskBoundaryPolicyError, match="RISK_BOUNDARY_POLICY_INVALID"
        ):
            load_boundaries(path)


def test_missing_risk_policy_remains_a_missing_observation(tmp_path):
    path = tmp_path / "risk-boundaries.yaml"
    with source_scope(tmp_path, allowed=[path]) as observations:
        with pytest.raises(
            RiskBoundaryPolicyError, match="RISK_BOUNDARY_POLICY_INVALID"
        ):
            load_boundaries(path)
    assert observations.snapshot()[path.name]["bytes"] is None

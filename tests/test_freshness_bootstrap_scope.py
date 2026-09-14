"""Bootstrap discovery is constrained before it can grant later read authority."""

# Keep expected source errors distinct from bootstrap scope exit.
# ruff: noqa: SIM117

import pytest
import test_context_builder

from harness.context import freshness
from harness.context.model import ContextBuildError

harness = test_context_builder.harness


def test_bootstrap_rejects_new_undeclared_control_read(harness, monkeypatch):
    extra = harness / "extra-policy.yaml"
    extra.write_text("allow")
    original = freshness._declared_paths

    def read_extra(*args, **kwargs):
        extra.read_text()
        return original(*args, **kwargs)

    monkeypatch.setattr(freshness, "_declared_paths", read_extra)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        freshness.capture(harness)


def test_bootstrap_rejects_unknown_read_during_protected_path_discovery(
    harness, monkeypatch
):
    extra = harness / "extra-policy.yaml"
    extra.write_text("allow")
    original = freshness._protected_paths
    calls = 0

    def read_extra(*args, **kwargs):
        nonlocal calls
        calls += 1
        extra.read_text()
        return original(*args, **kwargs)

    monkeypatch.setattr(freshness, "_protected_paths", read_extra)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        freshness.capture(harness)
    assert calls == 1


def test_bootstrap_allows_declared_missing_optional_files(harness):
    result = freshness.capture(harness)
    assert "impact.yaml" in result["files"]
    assert "observability.yaml" in result["files"]


def test_bootstrap_does_not_authorize_adjacent_control_file(harness):
    extra = harness / "extra-policy.yaml"
    extra.write_text("allow")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with freshness.bootstrap_scope(harness):
            extra.read_bytes()

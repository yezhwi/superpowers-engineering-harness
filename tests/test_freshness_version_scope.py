"""Version capture cannot read an undeclared file after bootstrap discovery."""

import pytest
import test_context_builder

from harness.context import freshness
from harness.context.model import ContextBuildError

harness = test_context_builder.harness


def test_version_phase_rejects_injected_unknown_file_read(harness, monkeypatch):
    extra = harness / "extra-policy.yaml"
    extra.write_text("allow")
    original = freshness.file_version

    def read_extra(path):
        extra.read_text()
        return original(path)

    monkeypatch.setattr(freshness, "file_version", read_extra)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        freshness.capture(harness)


def test_version_phase_keeps_existing_canonical_artifacts_readable(harness):
    result = freshness.capture(harness)
    assert result["files"]["current-task.yaml"]
    assert result["files"]["evidence/"] is not None


def test_new_canonical_member_after_freeze_rejects_capture(harness, monkeypatch):
    original = freshness._capture_versions

    def add_member(*args, **kwargs):
        root = args[0]
        (root / "evidence" / "late.json").write_text("{}")
        return original(*args, **kwargs)

    monkeypatch.setattr(freshness, "_capture_versions", add_member)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        freshness.capture(harness)


def test_new_product_file_after_untracked_discovery_is_not_silently_hashed(
    harness, monkeypatch
):
    original = freshness._capture_versions

    def add_product(*args, **kwargs):
        root = args[1]
        (root / "late_product.py").write_text("value = 1\n")
        return original(*args, **kwargs)

    monkeypatch.setattr(freshness, "_capture_versions", add_product)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        freshness.capture(harness)

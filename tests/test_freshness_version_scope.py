"""Version capture cannot read an undeclared file after bootstrap discovery."""

import pytest
import test_context_builder
import yaml

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


def test_enabled_plan_artifacts_are_conditional_named_freshness_inputs(harness):
    path = harness / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["risk"]["level"] = "Q2"
    task["risk"]["profile"] = "STANDARD"
    task["plan_reconciliation"] = {"enabled": True, "mode": "final"}
    path.write_text(yaml.safe_dump(task))

    missing = freshness.capture(harness)
    assert missing["files"]["plan.yaml"] is None
    assert missing["files"]["plan-execution.yaml"] is None
    assert missing["plan_hash"] is None
    assert missing["plan_execution_hash"] is None

    (harness / "plan.yaml").write_text("version: 1\nitems: []\n")
    plan_present = freshness.capture(harness)
    assert plan_present["plan_hash"] == plan_present["files"]["plan.yaml"]
    assert plan_present["plan_hash"].startswith("sha256:")
    assert plan_present["plan_execution_hash"] is None

    (harness / "plan-execution.yaml").write_text("version: 1\n")
    both_present = freshness.capture(harness)
    assert both_present["plan_execution_hash"] == both_present["files"]["plan-execution.yaml"]
    assert both_present != plan_present

    (harness / "plan.yaml").unlink()
    assert freshness.capture(harness)["plan_hash"] is None


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

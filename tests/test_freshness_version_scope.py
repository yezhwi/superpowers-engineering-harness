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


def test_required_architecture_is_conditional_named_freshness_input(harness):
    test_context_builder.enable_required_architecture(harness)

    before = freshness.capture(harness)
    assert before["projection_version"] == 4
    assert before["files"]["architecture.yaml"].startswith("sha256:")

    (harness / "architecture.yaml").write_text(
        (harness / "architecture.yaml").read_text() + "\n"
    )
    assert freshness.capture(harness) != before


def test_fast_and_off_capture_do_not_include_architecture_source(harness):
    assert "architecture.yaml" not in freshness.capture(harness)["files"]

    test_context_builder.set_profile(harness, "Q2")
    assert "architecture.yaml" not in freshness.capture(harness)["files"]


def test_architecture_schema_bytes_are_conditional_freshness_inputs(harness, monkeypatch):
    from harness import schema_resources

    seen = []
    original = schema_resources._resource_bytes

    def recording_resource(name):
        seen.append(name)
        return original(name)

    monkeypatch.setattr(schema_resources, "_resource_bytes", recording_resource)

    freshness.capture(harness)
    assert "architecture.schema.json" not in seen

    seen.clear()
    test_context_builder.set_profile(harness, "Q2")
    freshness.capture(harness)
    assert "architecture.schema.json" not in seen

    seen.clear()
    test_context_builder.enable_required_architecture(harness)
    freshness.capture(harness)
    assert "architecture.schema.json" in seen


def test_required_to_off_race_rejects_before_architecture_versioning(harness, monkeypatch):
    test_context_builder.enable_required_architecture(harness)
    gate_path = harness / "gate.yaml"
    original = freshness._architecture_source_names
    calls = 0

    def switch_mode(root):
        nonlocal calls
        calls += 1
        if calls == 2:
            gate = yaml.safe_load(gate_path.read_text())
            gate["gate"]["architecture"]["mode"] = "off"
            gate_path.write_text(yaml.safe_dump(gate, sort_keys=False))
        return original(root)

    monkeypatch.setattr(freshness, "_architecture_source_names", switch_mode)

    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        freshness.capture(harness)
    assert calls == 2


def test_architecture_module_ids_never_enter_declared_path_resolution(harness, monkeypatch):
    test_context_builder.enable_required_architecture(harness)
    seen = []
    original = freshness.contained_path

    def recording_contained_path(root, ref):
        seen.append(ref)
        return original(root, ref)

    monkeypatch.setattr(freshness, "contained_path", recording_contained_path)

    result = freshness.capture(harness)

    assert result["files"]["architecture.yaml"]
    assert "app" not in seen
    assert not any(ref.endswith("/app") for ref in seen)


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

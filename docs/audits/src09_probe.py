"""SRC-09 audit probes: reject unknown reads; version explicitly declared inputs.

Run: PYTHONPATH=src:tests python -m pytest -q docs/audits/src09_probe.py
Uses synthetic repositories only. Never touches the active Harness task.
"""

import pytest
import test_context_builder
import yaml

from harness import quality_gate
from harness.context.freshness import capture
from harness.context.model import ContextBuildError
from harness.context.store import generate_context

harness = test_context_builder.harness


def install_extra_gate_read(root, monkeypatch, relative):
    flag = root / relative
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("allow")
    original = quality_gate.assess_gate

    def gate_with_new_input(*args, **kwargs):
        # Simulate a future Gate feature reading an unregistered control input.
        if flag.read_text().strip() != "allow":
            raise quality_gate.InvalidHarnessState("probe policy denied")
        return original(*args, **kwargs)

    monkeypatch.setattr(quality_gate, "assess_gate", gate_with_new_input)
    return flag


def test_unregistered_gate_read_must_prevent_publication(harness, monkeypatch):
    install_extra_gate_read(harness, monkeypatch, "extra-policy.yaml")
    with pytest.raises(ContextBuildError):
        generate_context(harness)
    assert not (harness / "context/current.yaml").exists()


def test_explicitly_declared_control_change_must_change_manifest(harness, monkeypatch):
    # Approved design rejects unknown reads rather than hashing all unknown
    # files. Once explicitly declared, the input must participate in freshness.
    flag = install_extra_gate_read(harness, monkeypatch, "extra-policy.yaml")
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["scope"]["owned_paths"].append(".harness/extra-policy.yaml")
    task_path.write_text(yaml.safe_dump(task))
    generate_context(harness)
    before = capture(harness)
    flag.write_text("deny")
    assert capture(harness) != before


def test_fast_ignored_user_change_input_must_be_versioned(harness):
    from harness.context.integrity import build_context
    from harness.workspace import protected_paths_fingerprint

    root = harness.parent
    hidden = root / "private/protected.txt"
    hidden.parent.mkdir()
    hidden.write_text("before")
    with (root / ".git/info/exclude").open("a") as stream:
        stream.write("\nprivate/\n")
    task_path = harness / "current-task.yaml"
    task = yaml.safe_load(task_path.read_text())
    task["risk"]["user_changes"] = {
        "paths": ["private/protected.txt"],
        "fingerprint": protected_paths_fingerprint(("private/protected.txt",), root),
    }
    task_path.write_text(yaml.safe_dump(task))
    before_context = build_context(harness)
    before = capture(harness)
    hidden.write_text("after")
    after_context = build_context(harness)
    assert not any(
        b["code"] == "FAST_USER_CHANGE_MODIFIED"
        for b in before_context["control"]["blockers"]
    )
    assert any(
        b["code"] == "FAST_USER_CHANGE_MODIFIED"
        for b in after_context["control"]["blockers"]
    )
    assert capture(harness) != before


def test_registered_gate_change_does_change_manifest(harness):
    before = capture(harness)
    with (harness / "gate.yaml").open("a") as stream:
        stream.write("\n# registered source changed\n")
    assert capture(harness) != before

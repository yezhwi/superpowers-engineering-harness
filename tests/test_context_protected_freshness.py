"""FAST protected input bytes must bind Context, independently of task.scope."""

import pytest
import test_context_builder
import yaml

from harness import quality_gate
from harness.context.freshness import capture
from harness.context.integrity import build_context, validate_context
from harness.context.model import ContextBuildError
from harness.workspace import snapshot

harness = test_context_builder.harness


def protect(root, name="private/protected.txt"):
    with (root.parent / ".git/info/exclude").open("a") as stream:
        stream.write("\nprivate/\n")
    path = root / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["risk"]["user_changes"]["paths"] = [name]
    path.write_text(yaml.safe_dump(task))
    return root.parent / name


@pytest.mark.parametrize("change", ["modify", "appear", "delete"])
def test_ignored_protected_input_changes_stale_context_not_product(harness, change):
    path = protect(harness)
    path.parent.mkdir(exist_ok=True)
    if change != "appear":
        path.write_text("before")
    document = build_context(harness)
    product = snapshot(harness.parent).fingerprint
    if change == "delete":
        path.unlink()
    else:
        path.write_text("after")
    assert snapshot(harness.parent).fingerprint == product
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        validate_context(harness, document)


@pytest.mark.parametrize("name", ["../outside.txt", "/tmp/src09-outside.txt"])
def test_protected_input_cannot_escape_repository(harness, name):
    protect(harness, name)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        capture(harness)


def test_protected_input_external_symlink_is_rejected(harness, tmp_path_factory):
    outside = tmp_path_factory.mktemp("protected-outside") / "file"
    outside.write_text("external")
    path = protect(harness)
    path.parent.mkdir()
    path.symlink_to(outside)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        capture(harness)


def test_protected_input_change_during_gate_assessment_rejects_build(
    harness, monkeypatch
):
    path = protect(harness)
    path.parent.mkdir()
    path.write_text("before")
    original = quality_gate.assess_gate

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        path.write_text("after")
        return result

    monkeypatch.setattr(quality_gate, "assess_gate", mutate)
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        build_context(harness)


@pytest.mark.parametrize("name", ["private/literal*.txt", "private/name::suffix"])
def test_protected_paths_are_literal_files_not_globs_or_test_selectors(harness, name):
    path = protect(harness, name)
    path.parent.mkdir()
    path.write_text("before")
    before = capture(harness)
    assert name in before["declared_files"]
    path.write_text("after")
    assert capture(harness) != before


def test_empty_protected_paths_remain_compatible(harness):
    path = harness / "current-task.yaml"
    task = yaml.safe_load(path.read_text())
    task["risk"]["user_changes"]["paths"] = []
    path.write_text(yaml.safe_dump(task))
    assert build_context(harness)["control"]["task"]["risk"] == task["risk"]

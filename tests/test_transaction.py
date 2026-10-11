import os
from pathlib import Path

import pytest

from harness.task_replacement import publish_replacement
from harness.transaction import StagedArtifact, publish, stage


@pytest.mark.parametrize("relative_path", ["../escape", "/tmp/escape"])
def test_stage_rejects_artifact_path_outside_staging_root(tmp_path, relative_path):
    with pytest.raises(ValueError, match="STAGED_ARTIFACT_PATH_INVALID"):
        stage(tmp_path / ".harness", [StagedArtifact(relative_path, b"bad")])


def test_publish_rejects_existing_fifo_without_blocking(tmp_path):
    harness = tmp_path / ".harness"
    harness.mkdir()
    os.mkfifo(harness / "artifact.yaml")
    staged = stage(harness, [StagedArtifact("artifact.yaml", b"new")])

    with pytest.raises(OSError, match="regular file"):
        publish(harness, staged, replace_paths=frozenset({"artifact.yaml"}))


def test_replacement_workspace_restores_original_when_swap_fails(tmp_path, monkeypatch):
    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "current-task.yaml").write_text("old")
    staged = tmp_path / ".harness.replacement"
    staged.mkdir()
    (staged / "current-task.yaml").write_text("new")
    original_replace = Path.replace

    def fail_staged_swap(self, target):
        if self == staged:
            raise OSError("injected replacement failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_staged_swap)

    with pytest.raises(OSError, match="injected replacement failure"):
        publish_replacement(harness, staged)

    assert (harness / "current-task.yaml").read_text() == "old"


def test_publish_rolls_back_all_targets_when_callback_fails(tmp_path):
    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "current-task.yaml").write_bytes(b"old task")
    (harness / "seal.yaml").write_bytes(b"old seal")
    staged = stage(harness, [
        StagedArtifact("current-task.yaml", b"new task"),
        StagedArtifact("plan.yaml", b"new plan"),
    ])

    def fail_callback():
        assert (harness / "current-task.yaml").read_bytes() == b"new task"
        assert (harness / "plan.yaml").read_bytes() == b"new plan"
        assert not (harness / "seal.yaml").exists()
        raise OSError("callback failed")

    with pytest.raises(OSError, match="callback failed"):
        publish(
            harness, staged,
            replace_paths=frozenset({"current-task.yaml"}),
            delete_paths=frozenset({"seal.yaml"}),
            after_publish=fail_callback,
        )

    assert (harness / "current-task.yaml").read_bytes() == b"old task"
    assert not (harness / "plan.yaml").exists()
    assert (harness / "seal.yaml").read_bytes() == b"old seal"
    assert staged.exists()


def test_publish_callback_success_cleans_staging(tmp_path):
    harness = tmp_path / ".harness"
    staged = stage(harness, [StagedArtifact("plan.yaml", b"new plan")])
    observed = []
    publish(
        harness, staged,
        after_publish=lambda: observed.append((harness / "plan.yaml").read_bytes()),
    )
    assert observed == [b"new plan"]
    assert not staged.exists()


def test_atomic_write_replaces_complete_single_artifact(tmp_path):
    """Break caught: standalone artifact writes can expose partial content."""
    from harness.transaction import atomic_write

    target = tmp_path / "artifact.json"
    target.write_text("old")
    atomic_write(target, b"new")

    assert target.read_bytes() == b"new"
    assert not list(tmp_path.glob("*.tmp"))


def test_publish_rolls_back_when_later_target_cannot_publish(tmp_path, monkeypatch):
    harness = tmp_path / ".harness"
    staged = stage(
        harness,
        [
            StagedArtifact("findings/FND-001.yaml", b"finding"),
            StagedArtifact("evidence/review.json", b"evidence"),
        ],
        operation_id="test",
    )
    original_replace = Path.replace

    def fail_evidence(self, target):
        if str(target).endswith("evidence/review.json"):
            raise OSError("injected publish failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_evidence)

    with pytest.raises(OSError, match="injected publish failure"):
        publish(harness, staged)

    assert not (harness / "findings/FND-001.yaml").exists()
    assert not (harness / "evidence/review.json").exists()
    assert staged.exists()

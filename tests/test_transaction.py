from pathlib import Path

import pytest

from harness.transaction import StagedArtifact, publish, stage


def test_publish_rolls_back_when_later_target_cannot_publish(tmp_path, monkeypatch):
    harness = tmp_path / ".harness"
    staged = stage(harness, [
        StagedArtifact("findings/FND-001.yaml", b"finding"),
        StagedArtifact("evidence/review.json", b"evidence"),
    ], operation_id="test")
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

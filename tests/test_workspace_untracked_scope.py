"""Git-discovered product names need no pre-scope filesystem metadata probe."""

from pathlib import Path

import pytest

from harness import workspace


def test_untracked_discovery_does_not_probe_paths_before_scope(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(
        workspace, "_run", lambda *args: b"product.py\n.harness/ignored.yaml\n"
    )
    original = Path.is_file

    def forbid_probe(self):
        if self == tmp_path / "product.py":
            raise AssertionError("untracked discovery used raw Path.is_file")
        return original(self)

    monkeypatch.setattr(Path, "is_file", forbid_probe)
    assert workspace._untracked_paths(tmp_path) == {"product.py"}


@pytest.mark.parametrize(
    "name", ["../outside.py", "/tmp/outside.py", "", ".harness/extra.yaml"]
)
def test_untracked_discovery_filters_noncanonical_or_control_names(
    tmp_path, monkeypatch, name
):
    monkeypatch.setattr(workspace, "_run", lambda *args: f"{name}\n".encode())
    assert workspace._untracked_paths(tmp_path) == set()

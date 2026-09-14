"""Source observations version actual reads, not just declared filenames."""

# Keep exit-time assertions separate from the scopes they exercise.
# ruff: noqa: SIM117

import hashlib

import pytest

from harness.context.model import ContextBuildError
from harness.source_access import exists, read_bytes, source_scope


def test_bytes_returned_to_parser_are_versioned(tmp_path):
    path = tmp_path / "input"
    path.write_bytes(b"original")
    with source_scope(tmp_path, allowed=[path]) as observations:
        assert read_bytes(path) == b"original"
        assert (
            observations.snapshot()["input"]["bytes"]
            == "sha256:" + hashlib.sha256(b"original").hexdigest()
        )


def test_source_changed_after_last_read_is_stale(tmp_path):
    path = tmp_path / "input"
    path.write_bytes(b"original")
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        with source_scope(tmp_path, allowed=[path]):
            read_bytes(path)
            path.write_bytes(b"changed")


def test_swallowed_repeated_read_conflict_still_fails(tmp_path):
    path = tmp_path / "input"
    path.write_bytes(b"original")
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        with source_scope(tmp_path, allowed=[path]):
            read_bytes(path)
            path.write_bytes(b"changed")
            try:
                read_bytes(path)
            except ContextBuildError:
                pass


def test_optional_missing_then_appearing_is_stale(tmp_path):
    path = tmp_path / "optional"
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        with source_scope(tmp_path, allowed=[path]):
            assert not exists(path)
            path.write_text("now exists")


def test_caught_missing_read_is_recorded(tmp_path):
    path = tmp_path / "optional"
    with source_scope(tmp_path, allowed=[path]) as observations:
        with pytest.raises(FileNotFoundError):
            read_bytes(path)
        assert observations.snapshot()["optional"]["bytes"] is None


def test_observation_snapshot_cannot_mutate_guard_state(tmp_path):
    path = tmp_path / "input"
    path.write_bytes(b"original")
    with source_scope(tmp_path, allowed=[path]) as observations:
        read_bytes(path)
        snapshot = observations.snapshot()
        snapshot.clear()
        assert "input" in observations.snapshot()


@pytest.mark.parametrize("pattern", ["../*", "**", "sub/*.yaml", "", ".."])
def test_directory_patterns_cannot_expand_scope(tmp_path, pattern):
    from harness.source_access import members

    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[tmp_path]):
            members(tmp_path, pattern)


def test_listing_does_not_authorize_reading_members(tmp_path):
    from harness.source_access import members

    path = tmp_path / "input.yaml"
    path.write_text("value")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[tmp_path]):
            assert members(tmp_path, "*.yaml") == (path,)
            read_bytes(path)


def test_directory_nonmatching_change_does_not_stale_observation(tmp_path):
    from harness.source_access import members

    path = tmp_path / "output.txt"
    with source_scope(tmp_path, allowed=[tmp_path, path]) as observations:
        assert members(tmp_path, "*.yaml") == ()
        path.write_text("not a member")
    assert observations.snapshot()["."]["members:*.yaml"] == ()


def test_nested_read_observation_survives_inner_scope_exit(tmp_path):
    path = tmp_path / "input"
    path.write_bytes(b"original")
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        with source_scope(tmp_path, allowed=[path]):
            with source_scope(tmp_path, allowed=[path]):
                read_bytes(path)
            path.write_bytes(b"after inner scope")


@pytest.mark.parametrize("query", ["is_file", "is_dir", "is_symlink"])
def test_is_file_type_change_is_stale(tmp_path, query):
    from harness import source_access

    path = tmp_path / "input"
    path.write_bytes(b"original")
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        with source_scope(tmp_path, allowed=[path, tmp_path / "target"]):
            assert getattr(source_access, query)(path) is (query == "is_file")
            path.unlink()
            if query == "is_symlink":
                (tmp_path / "target").write_text("target")
                path.symlink_to(tmp_path / "target")
            else:
                path.mkdir()


def test_directory_membership_change_is_stale(tmp_path):
    from harness.source_access import members

    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        with source_scope(tmp_path, allowed=[tmp_path, tmp_path / "new.yaml"]):
            assert members(tmp_path, "*.yaml") == ()
            (tmp_path / "new.yaml").write_text("new")

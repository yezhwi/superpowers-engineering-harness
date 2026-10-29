"""Guard behavior in isolation; integration with Gate is a separate step."""

# Keep exception assertions separate from the scopes whose exit they test.
# ruff: noqa: SIM117

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest


def test_declared_member_pattern_allows_missing_file_not_other_names(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import exists, source_scope

    directory = tmp_path / "evidence"
    directory.mkdir()
    with source_scope(tmp_path, allowed=[], member_rules=[(directory, "*.json")]):
        assert not exists(directory / "missing.json")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[], member_rules=[(directory, "*.json")]):
            exists(directory / "unexpected.yaml")


def test_unknown_read_is_rejected(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    root = tmp_path / ".harness"
    root.mkdir()
    file = root / "unknown.yaml"
    file.write_text("secret")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(root, allowed=[]):
            file.read_text()


def test_swallowed_violation_still_fails_scope(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    root = tmp_path / ".harness"
    root.mkdir()
    file = root / "unknown"
    file.write_text("secret")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN") as error:
        with source_scope(root, allowed=[]):
            try:
                file.read_bytes()
            except Exception:  # noqa: BLE001, S110 -- simulate Gate swallowing a loader error
                pass
    assert "secret" not in str(error.value)
    assert file.read_text() == "secret"  # scope restored on failure


def test_declared_read_and_missing_probe(tmp_path):
    from harness.source_access import exists, read_bytes, source_scope

    file = tmp_path / ".harness" / "optional"
    file.parent.mkdir()
    with source_scope(file.parent, allowed=[file]):
        assert not exists(file)
    file.write_bytes(b"declared")
    with source_scope(file.parent, allowed=[file]):
        assert read_bytes(file) == b"declared"


def test_unknown_exists_is_rejected(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import exists, source_scope

    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[]):
            exists(tmp_path / "absent")


def test_nested_scope_cannot_expand_parent_authority(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    file = tmp_path / "unknown"
    file.write_text("value")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[]):
            with source_scope(tmp_path, allowed=[file]):
                file.read_text()


def test_external_symlink_cannot_escape_guard(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    root = tmp_path / ".harness"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("private")
    link = root / "link"
    link.symlink_to(outside)
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(root, allowed=[link]):
            link.read_text()


def test_catching_nested_scope_error_does_not_clear_outer_violation(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    file = tmp_path / "declared"
    file.write_text("value")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(tmp_path, allowed=[file]):
            try:
                with source_scope(tmp_path, allowed=[]):
                    file.read_text()
            except ContextBuildError:
                pass


@pytest.mark.parametrize("method", ["builtin", "bytes", "fd"])
def test_other_open_routes_cannot_bypass_guard(tmp_path, method):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    file = tmp_path / "unknown"
    file.write_text("value")
    with file.open("rb") as prior:
        with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
            with source_scope(tmp_path, allowed=[]):
                if method == "builtin":
                    with open(file) as stream:
                        stream.read()
                elif method == "bytes":
                    file.read_bytes()
                else:
                    with open(prior.fileno(), closefd=False) as stream:
                        stream.read()


def test_parallel_scope_permissions_are_isolated(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope

    file = tmp_path / "shared"
    file.write_text("value")
    barrier = Barrier(2)

    def read(allowed):
        try:
            with source_scope(tmp_path, allowed=[file] if allowed else []):
                barrier.wait(timeout=5)
                return file.read_text()
        except ContextBuildError:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        yes, no = pool.submit(read, True), pool.submit(read, False)
        assert yes.result(timeout=10) == "value"
        assert no.result(timeout=10) == "denied"


@pytest.mark.parametrize('size,accepted', [(16 * 1024 * 1024, True), (16 * 1024 * 1024 + 1, False)])
def test_bounded_snapshot_inclusive_raw_limit(tmp_path, size, accepted):
    from harness import source_access
    file = tmp_path / 'metadata'
    file.write_bytes(b'x' * size)
    if accepted:
        result = source_access.read_regular_snapshot_beneath(file, tmp_path, max_bytes=16 * 1024 * 1024)
        assert len(result.content) == size
        assert (result.device, result.inode) == (file.stat().st_dev, file.stat().st_ino)
    else:
        with pytest.raises(source_access.RegularFileTooLargeError):
            source_access.read_regular_snapshot_beneath(file, tmp_path, max_bytes=16 * 1024 * 1024)


@pytest.mark.parametrize('kind', ['file_symlink', 'parent_symlink', 'directory', 'fifo', 'outside', 'parent_escape'])
def test_bounded_snapshot_rejects_non_regular_and_escape(tmp_path, kind):
    import os

    from harness import source_access
    root = tmp_path / 'root'
    root.mkdir()
    file = root / 'data'
    if kind == 'file_symlink':
        (root / 'actual').write_text('value')
        file.symlink_to('actual')
    elif kind == 'parent_symlink':
        (tmp_path / 'actual').mkdir()
        (tmp_path / 'actual/data').write_text('value')
        (root / 'link').symlink_to(tmp_path / 'actual', target_is_directory=True)
        file = root / 'link/data'
    elif kind == 'directory':
        file.mkdir()
    elif kind == 'fifo':
        os.mkfifo(file)
    elif kind == 'outside':
        file = tmp_path / 'outside'
        file.write_text('value')
    else:
        (tmp_path / 'outside').write_text('value')
        file = root / '../outside'
    with pytest.raises((OSError, ValueError)):
        source_access.read_regular_snapshot_beneath(file, root, max_bytes=8)


def test_bounded_snapshot_preserves_scope_authority_and_observation(tmp_path):
    from harness import source_access
    from harness.context.model import ContextBuildError
    file = tmp_path / 'data'
    file.write_bytes(b'abc')
    with source_access.source_scope(tmp_path, allowed=[file]):
        assert source_access.read_regular_snapshot_beneath(file, tmp_path, max_bytes=3).content == b'abc'
    with pytest.raises(ContextBuildError, match='CONTEXT_REFERENCE_BROKEN'):
        with source_access.source_scope(tmp_path, allowed=[]):
            source_access.read_regular_snapshot_beneath(file, tmp_path, max_bytes=3)


def test_bounded_snapshot_never_reads_beyond_limit_plus_one(tmp_path, monkeypatch):
    from harness import source_access
    file = tmp_path / 'data'
    file.write_bytes(b'x' * 1000)
    original = source_access.os.read
    total = []
    def observed(fd, amount):
        assert amount <= 4 - sum(total)
        data = original(fd, amount)
        total.append(len(data))
        return data
    monkeypatch.setattr(source_access.os, 'read', observed)
    with pytest.raises(source_access.RegularFileTooLargeError):
        source_access.read_regular_snapshot_beneath(file, tmp_path, max_bytes=3)
    assert sum(total) <= 4

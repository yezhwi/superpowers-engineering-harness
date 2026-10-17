"""Native publication boundary: never discard displaced canonical objects."""

import errno
import os
from types import SimpleNamespace

import pytest


def backend():
    from harness import publication_fs

    return publication_fs


def test_exchange_retains_both_objects(tmp_path):
    fs = backend()
    left = tmp_path / 'left'
    right = tmp_path / 'right'
    left.write_bytes(b'operator')
    right.write_bytes(b'candidate')
    before = (left.stat().st_ino, right.stat().st_ino)
    fd = fs.open_directory(tmp_path)
    held = os.open(left, os.O_RDWR)
    try:
        fs.exchange(fd, 'left', fd, 'right')
        assert (left.read_bytes(), right.read_bytes()) == (b'candidate', b'operator')
        assert (left.stat().st_ino, right.stat().st_ino) == before[::-1]
        os.write(held, b'late edit')
        assert right.read_bytes() == b'late edit'
        assert left.read_bytes() == b'candidate'
    finally:
        os.close(held)
        os.close(fd)


def test_noreplace_preserves_concurrent_creation(tmp_path):
    fs = backend()
    (tmp_path / 'source').write_bytes(b'candidate')
    (tmp_path / 'target').write_bytes(b'operator')
    fd = fs.open_directory(tmp_path)
    try:
        with pytest.raises(FileExistsError):
            fs.move_noreplace(fd, 'source', fd, 'target')
        assert (tmp_path / 'source').read_bytes() == b'candidate'
        assert (tmp_path / 'target').read_bytes() == b'operator'
        fs.move_noreplace(fd, 'source', fd, 'absent')
        assert not (tmp_path / 'source').exists()
        assert (tmp_path / 'absent').read_bytes() == b'candidate'
    finally:
        os.close(fd)


@pytest.mark.parametrize('name', ['', '.', '..', '../outside', 'nested/file', '/absolute', 'bad\x00name', 'a\\b'])
def test_native_boundary_rejects_non_basename(tmp_path, name):
    fs = backend()
    (tmp_path / 'source').write_bytes(b'candidate')
    fd = fs.open_directory(tmp_path)
    try:
        with pytest.raises(ValueError, match='PUBLICATION_NAME_INVALID'):
            fs.move_noreplace(fd, 'source', fd, name)
        assert (tmp_path / 'source').read_bytes() == b'candidate'
    finally:
        os.close(fd)


@pytest.mark.parametrize('ancestor', [False, True])
def test_open_directory_rejects_symlink_components(tmp_path, ancestor):
    fs = backend()
    actual = tmp_path / 'actual'
    actual.mkdir()
    (actual / 'nested').mkdir()
    link = tmp_path / 'link'
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(OSError):
        fs.open_directory(link / 'nested' if ancestor else link)


def test_pinned_directory_cannot_redirect_to_replaced_path(tmp_path):
    fs = backend()
    parent = tmp_path / 'parent'
    parent.mkdir()
    (parent / 'source').write_bytes(b'candidate')
    fd = fs.open_directory(parent)
    parent.rename(tmp_path / 'moved')
    parent.mkdir()
    (parent / 'source').write_bytes(b'operator')
    try:
        fs.move_noreplace(fd, 'source', fd, 'target')
        assert (parent / 'source').read_bytes() == b'operator'
        assert not (parent / 'target').exists()
        assert (tmp_path / 'moved/target').read_bytes() == b'candidate'
    finally:
        os.close(fd)


def test_unsupported_never_falls_back(tmp_path, monkeypatch):
    fs = backend()
    (tmp_path / 'left').write_bytes(b'operator')
    (tmp_path / 'right').write_bytes(b'candidate')
    fd = fs.open_directory(tmp_path)
    monkeypatch.setattr(fs.ctypes, 'CDLL', lambda *a, **kw: SimpleNamespace())
    try:
        with pytest.raises(fs.PublicationUnsupported, match='PUBLICATION_UNSUPPORTED'):
            fs.exchange(fd, 'left', fd, 'right')
        assert (tmp_path / 'left').read_bytes() == b'operator'
        assert (tmp_path / 'right').read_bytes() == b'candidate'
    finally:
        os.close(fd)


@pytest.mark.parametrize('code', [errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EXDEV])
def test_kernel_refusal_never_falls_back(tmp_path, monkeypatch, code):
    fs = backend()
    (tmp_path / 'left').write_bytes(b'operator')
    (tmp_path / 'right').write_bytes(b'candidate')

    def refused(*args):
        fs.ctypes.set_errno(code)
        return -1

    # Native call failure only; validation and public operation remain real.
    monkeypatch.setattr(fs, '_native', lambda: (refused, 2, 4))
    fd = fs.open_directory(tmp_path)
    try:
        with pytest.raises(fs.PublicationUnsupported) as exc:
            fs.exchange(fd, 'left', fd, 'right')
        assert exc.value.errno == code
        assert (tmp_path / 'left').read_bytes() == b'operator'
        assert (tmp_path / 'right').read_bytes() == b'candidate'
    finally:
        os.close(fd)


def test_capability_probe_retains_probes_and_unrelated_bytes(tmp_path):
    fs = backend()
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    (private / 'unrelated').write_bytes(b'operator')
    fd = fs.open_directory(private)
    try:
        fs.check_capabilities(fd)
        assert (private / 'unrelated').read_bytes() == b'operator'
        assert sorted(path.read_bytes() for path in private.iterdir()) == [b'left', b'operator', b'right']
    finally:
        os.close(fd)


def test_cross_directory_exchange_keeps_both_inodes(tmp_path):
    fs = backend()
    left = tmp_path / 'left'
    right = tmp_path / 'right'
    left.mkdir()
    right.mkdir()
    (left / 'value').write_bytes(b'operator')
    (right / 'value').write_bytes(b'candidate')
    lfd, rfd = fs.open_directory(left), fs.open_directory(right)
    try:
        fs.exchange(lfd, 'value', rfd, 'value')
        assert (left / 'value').read_bytes() == b'candidate'
        assert (right / 'value').read_bytes() == b'operator'
        fs.sync_directory(lfd)
        fs.sync_directory(rfd)
    finally:
        os.close(lfd)
        os.close(rfd)


def test_missing_exchange_target_preserves_source(tmp_path):
    fs = backend()
    (tmp_path / 'source').write_bytes(b'candidate')
    fd = fs.open_directory(tmp_path)
    try:
        with pytest.raises(FileNotFoundError):
            fs.exchange(fd, 'source', fd, 'missing')
        assert (tmp_path / 'source').read_bytes() == b'candidate'
        assert not (tmp_path / 'missing').exists()
    finally:
        os.close(fd)


def test_unsupported_platform_refuses_without_probe_files(tmp_path, monkeypatch):
    fs = backend()
    fd = fs.open_directory(tmp_path)
    monkeypatch.setattr(fs.sys, 'platform', 'win32')
    try:
        with pytest.raises(fs.PublicationUnsupported):
            fs.check_capabilities(fd)
        assert list(tmp_path.iterdir()) == []
    finally:
        os.close(fd)


@pytest.mark.parametrize('platform', ['linux', 'linux2', 'win32', 'freebsd14'])
@pytest.mark.parametrize('entry', ['open_directory', 'exchange', 'move_noreplace', 'check_capabilities'])
def test_unsupported_platform_refuses_before_native_access(tmp_path, monkeypatch, platform, entry):
    """Break caught: an unsupported OS enters native publication or creates probes."""
    fs = backend()
    left, right = tmp_path / 'left', tmp_path / 'right'
    left.write_bytes(b'operator')
    right.write_bytes(b'candidate')
    before = [(path.stat().st_ino, path.read_bytes()) for path in (left, right)]
    fd = fs.open_directory(tmp_path)
    opened = None

    def unexpected_abi(*args, **kwargs):
        pytest.fail('unsupported platform must refuse before loading native ABI')

    def unexpected_open(*args, **kwargs):
        pytest.fail('unsupported platform must refuse before opening directories')

    try:
        with monkeypatch.context() as patch:
            patch.setattr(fs.sys, 'platform', platform)
            patch.setattr(fs.ctypes, 'CDLL', unexpected_abi)
            if entry == 'open_directory':
                patch.setattr(fs.os, 'open', unexpected_open)
            with pytest.raises(fs.PublicationUnsupported, match='PUBLICATION_UNSUPPORTED') as exc:
                if entry == 'open_directory':
                    opened = fs.open_directory(tmp_path)
                elif entry == 'check_capabilities':
                    fs.check_capabilities(fd)
                else:
                    getattr(fs, entry)(fd, 'left', fd, 'right')
            assert exc.value.errno == errno.ENOTSUP
        assert set(tmp_path.iterdir()) == {left, right}
        assert [(path.stat().st_ino, path.read_bytes()) for path in (left, right)] == before
    finally:
        if opened is not None:
            os.close(opened)
        os.close(fd)


def test_fsync_failure_prevents_capability_success(tmp_path, monkeypatch):
    fs = backend()
    (tmp_path / 'unrelated').write_bytes(b'operator')
    fd = fs.open_directory(tmp_path)

    def failed(fd):
        raise OSError(errno.EIO, 'injected synchronization failure')

    monkeypatch.setattr(fs.os, 'fsync', failed)
    try:
        with pytest.raises(OSError, match='injected synchronization failure'):
            fs.check_capabilities(fd)
        assert (tmp_path / 'unrelated').read_bytes() == b'operator'
    finally:
        os.close(fd)

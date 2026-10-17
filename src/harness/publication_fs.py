"""Narrow native name operations; exchange preserves objects, not content CAS.

Callers own directory FDs, journals, inode classification and retained objects.
No fallback to replacing rename. Capability probes are mutating and must only run
inside private transaction storage, never from read-only diagnostic commands.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from pathlib import Path
from uuid import uuid4


class PublicationUnsupported(OSError):
    """Platform/filesystem lacks required publication primitive."""


def _unsupported(code: int = errno.ENOTSUP) -> PublicationUnsupported:
    return PublicationUnsupported(code, 'PUBLICATION_UNSUPPORTED')


def _native():
    # Darwin ABI: apple-oss-distributions/xnu, tag xnu-11417.101.15,
    # bsd/sys/stdio.h: renameatx_np(..., unsigned int); SWAP=2, EXCL=4.
    if sys.platform != 'darwin':
        raise _unsupported()
    symbol, exchange_flag, exclusive_flag = 'renameatx_np', 2, 4
    try:
        function = getattr(ctypes.CDLL(None, use_errno=True), symbol)
    except (AttributeError, OSError) as exc:
        raise _unsupported(errno.ENOSYS) from exc
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                         ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    return function, exchange_flag, exclusive_flag


def _basename(name: str) -> bytes:
    if (not isinstance(name, str) or not name or name in {'.', '..'}
            or any(char in name for char in ('/', '\\', '\x00'))):
        raise ValueError('PUBLICATION_NAME_INVALID')
    return os.fsencode(name)


def _directory(fd: int) -> None:
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        raise NotADirectoryError(errno.ENOTDIR, 'publication directory required')


def open_directory(path: Path) -> int:
    """Walk every component no-follow; returned descriptor pins actual object."""
    if sys.platform != 'darwin':
        raise _unsupported()
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('PUBLICATION_DIRECTORY_INVALID')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _move(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str,
          *, swap: bool) -> None:
    source, destination = _basename(src_name), _basename(dst_name)
    _directory(src_dir_fd)
    _directory(dst_dir_fd)
    function, exchange_flag, exclusive_flag = _native()
    ctypes.set_errno(0)
    if function(src_dir_fd, source, dst_dir_fd, destination,
                exchange_flag if swap else exclusive_flag) != 0:
        code = ctypes.get_errno() or errno.EIO
        if code in {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EXDEV}:
            raise _unsupported(code)
        raise OSError(code, os.strerror(code))


def exchange(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None:
    """Exchange two existing names; neither displaced inode is discarded."""
    _move(src_dir_fd, src_name, dst_dir_fd, dst_name, swap=True)


def move_noreplace(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None:
    """Move source only when destination name is absent atomically."""
    _move(src_dir_fd, src_name, dst_dir_fd, dst_name, swap=False)


def sync_directory(dir_fd: int) -> None:
    _directory(dir_fd)
    os.fsync(dir_fd)


def check_capabilities(private_dir_fd: int) -> None:
    """Verify actual filesystem; retain probes rather than unlink raced names.

    Caller supplies dedicated retained capability directory. No automatic cleanup:
    even a checked probe basename could be replaced before an unlink. Native
    success does not prove remote-filesystem or power-loss semantics.
    """
    _directory(private_dir_fd)
    _native()  # Refuse absent ABI before even creating probe files.
    names = tuple(f'.cap-{uuid4().hex}-{suffix}' for suffix in ('a', 'b', 'c'))
    def identity(name):
        info = os.stat(name, dir_fd=private_dir_fd, follow_symlinks=False)
        return info.st_dev, info.st_ino

    for name, content in zip(names[:2], (b'left', b'right'), strict=True):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600, dir_fd=private_dir_fd)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    before = identity(names[0]), identity(names[1])
    exchange(private_dir_fd, names[0], private_dir_fd, names[1])
    if (identity(names[0]), identity(names[1])) != before[::-1]:
        raise _unsupported()
    try:
        move_noreplace(private_dir_fd, names[0], private_dir_fd, names[1])
    except FileExistsError:
        pass
    else:
        raise _unsupported()
    if (identity(names[0]), identity(names[1])) != before[::-1]:
        raise _unsupported()
    move_noreplace(private_dir_fd, names[0], private_dir_fd, names[2])
    if identity(names[2]) != before[1] or identity(names[1]) != before[0]:
        raise _unsupported()
    try:
        identity(names[0])
    except FileNotFoundError:
        pass
    else:
        raise _unsupported()
    sync_directory(private_dir_fd)
    # Observe final names, but never truncate/unlink them even if they now differ.
    if identity(names[2]) != before[1] or identity(names[1]) != before[0]:
        raise _unsupported()

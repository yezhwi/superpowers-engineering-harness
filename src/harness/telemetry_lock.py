"""Process-shared, reentrant lock for task-bound telemetry publication."""

import hashlib
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

_HELD = threading.local()


def _owner_key(harness_dir: Path) -> str:
    """One workspace owner, including legacy custom roots before activation.

    Non-Git isolated regular-file roots retain their existing path owner. Git
    worktrees use their own physical root, never the common-dir of a checkout.
    """
    from .repository import RepositoryNotFoundError, find_git_root

    root = Path(harness_dir).resolve()
    try:
        repo = find_git_root(root.parent)
    except RepositoryNotFoundError:
        return str(root)
    return str((repo / '.harness').resolve())


@contextmanager
def telemetry_lock(harness_dir: Path):
    """Keep lock identity stable across atomic Harness directory replacement.

    Lock files live outside the workspace so they cannot stale product evidence.
    Never unlink them: queued processes may still hold the old inode.
    """
    key = _owner_key(harness_dir)
    held = getattr(_HELD, "paths", None)
    if held is None:
        held = _HELD.paths = set()
    if key in held:
        yield
        return
    digest = hashlib.sha256(os.fsencode(key)).hexdigest()
    path = Path(tempfile.gettempdir()) / f"harness-telemetry-{digest}.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            from .context.telemetry import phase

            with phase('lock_wait'):
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            from .context.telemetry import phase

            with phase('lock_wait'):
                fcntl.flock(fd, fcntl.LOCK_EX)
        held.add(key)
        try:
            yield
        finally:
            held.remove(key)
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)

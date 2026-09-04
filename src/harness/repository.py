"""Git repository root discovery (guide section 7)."""

from pathlib import Path


class RepositoryNotFoundError(Exception):
    """Raised when no git repository root is found above the start path."""


def find_git_root(start: Path) -> Path:
    """Walk up from `start` until a directory containing `.git` is found.

    Accepts `.git` as file or directory (worktree compatible).
    Raises RepositoryNotFoundError when the filesystem root is reached.
    """
    start = Path(start).resolve()
    current = start
    while True:
        if (current / ".git").exists():
            return current
        if current.parent == current:
            raise RepositoryNotFoundError(f"no git repository found above {start}")
        current = current.parent

"""Shared Git workspace facts for evidence, Gate, status, and review scope."""

from dataclasses import dataclass
import hashlib
import subprocess
from pathlib import Path


class WorkspaceError(RuntimeError):
    """Git repository state cannot be read deterministically."""


@dataclass(frozen=True)
class WorkspaceSnapshot:
    head: str
    fingerprint: str
    changed_paths: tuple[str, ...]


@dataclass(frozen=True)
class ReviewScope:
    base_ref: str
    base_commit: str
    head_commit: str
    workspace: WorkspaceSnapshot
    files: tuple[str, ...]


def _root(repo_root: Path | None) -> Path:
    return (repo_root or Path.cwd()).resolve()


def _run(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo_root, capture_output=True)
    if result.returncode:
        raise WorkspaceError(result.stderr.decode().strip())
    return result.stdout


def git_head(repo_root: Path | None = None) -> str:
    """Return current full Git HEAD SHA."""
    root = _root(repo_root)
    try:
        return _run(root, "rev-parse", "HEAD").decode().strip()
    except WorkspaceError as exc:
        raise WorkspaceError(f"cannot resolve git HEAD: {exc}") from exc


def _untracked_paths(repo_root: Path) -> set[str]:
    paths = set()
    for name in _run(repo_root, "ls-files", "--others", "--exclude-standard").decode().splitlines():
        if not name.startswith(".harness/") and (repo_root / name).is_file():
            paths.add(name)
    return paths


def _working_paths(repo_root: Path) -> set[str]:
    exclude = ":(exclude).harness/**"
    paths = set()
    for args in (
        ("diff", "--name-only", "HEAD", "--", ".", exclude),
        ("diff", "--cached", "--name-only", "HEAD", "--", ".", exclude),
    ):
        paths.update(name for name in _run(repo_root, *args).decode().splitlines() if name)
    return paths | _untracked_paths(repo_root)


def _fingerprint(repo_root: Path) -> str:
    """Preserve established Evidence fingerprint semantics."""
    exclude = ":(exclude).harness/**"
    parts = [
        _run(repo_root, "rev-parse", "HEAD"),
        _run(repo_root, "diff", "--binary", "HEAD", "--", ".", exclude),
        _run(repo_root, "diff", "--cached", "--binary", "HEAD", "--", ".", exclude),
    ]
    for name in sorted(_untracked_paths(repo_root)):
        parts.extend([name.encode(), hashlib.sha256((repo_root / name).read_bytes()).digest()])
    return "sha256:" + hashlib.sha256(b"\0".join(parts)).hexdigest()


def snapshot(repo_root: Path | None = None) -> WorkspaceSnapshot:
    """Return HEAD plus all current business changes under one ignore policy."""
    root = _root(repo_root)
    return WorkspaceSnapshot(
        head=git_head(root),
        fingerprint=_fingerprint(root),
        changed_paths=tuple(sorted(_working_paths(root))),
    )


def review_scope(base_ref: str, repo_root: Path | None = None) -> ReviewScope:
    """Return effective review files from merge-base through current workspace."""
    root = _root(repo_root)
    base_commit = _run(root, "merge-base", base_ref, "HEAD").decode().strip()
    current = snapshot(root)
    exclude = ":(exclude).harness/**"
    committed = _run(
        root, "diff", "--name-only", f"{base_commit}..{current.head}", "--", ".", exclude
    ).decode().splitlines()
    files = tuple(sorted(set(name for name in committed if name) | set(current.changed_paths)))
    return ReviewScope(
        base_ref=base_ref,
        base_commit=base_commit,
        head_commit=current.head,
        workspace=current,
        files=files,
    )

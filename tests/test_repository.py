"""M1: git repository root discovery (guide sections 7, 24)."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from harness.repository import RepositoryNotFoundError, find_git_root


def _git(tmp_path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=tmp_path, check=True,
                   capture_output=True)


def make_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    return tmp_path


def test_find_root_from_root(tmp_path):
    repo = make_repo(tmp_path)
    assert find_git_root(repo) == repo


def test_find_root_from_nested_directory(tmp_path):
    repo = make_repo(tmp_path)
    nested = repo / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert find_git_root(nested) == repo


def test_accept_git_file_worktree_style(tmp_path):
    # .git as a FILE (worktree) still counts as a repo root.
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: ../main/.git\n")
    assert find_git_root(worktree) == worktree


def test_fail_outside_repository(tmp_path):
    with pytest.raises(RepositoryNotFoundError):
        find_git_root(tmp_path)


def test_nearest_root_wins_when_nested_repo(tmp_path):
    outer = make_repo(tmp_path)
    inner = outer / "sub"
    inner.mkdir()
    _git(inner, "init", "-q")
    assert find_git_root(inner / "deep") == inner

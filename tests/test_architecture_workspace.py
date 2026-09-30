"""Typed four-layer Architecture Git adapter tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from harness import workspace
from harness.workspace import ArchitectureChangeRecord, WorkspaceError


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "tracked.py").write_text("value = 1\n")
    (repo / "old.py").write_text("old = True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def records(*items: tuple[str, str]) -> tuple[ArchitectureChangeRecord, ...]:
    return tuple(ArchitectureChangeRecord(kind, path) for kind, path in items)


def test_adapter_collects_committed_cached_worktree_and_untracked_layers(tmp_path):
    repo, base = repository(tmp_path)
    (repo / "committed.py").write_text("committed = True\n")
    git(repo, "add", "committed.py")
    git(repo, "commit", "-qm", "committed layer")
    (repo / "cached.py").write_text("cached = True\n")
    git(repo, "add", "cached.py")
    (repo / "tracked.py").write_text("value = 2\n")
    (repo / "untracked.py").write_text("untracked = True\n")

    assert workspace.architecture_changes(base, repo) == records(
        ("added", "cached.py"),
        ("added", "committed.py"),
        ("modified", "tracked.py"),
        ("untracked", "untracked.py"),
    )


def test_same_path_keeps_distinct_layer_kinds(tmp_path):
    repo, base = repository(tmp_path)
    path = repo / "layered.py"
    path.write_text("value = 1\n")
    git(repo, "add", "layered.py")
    git(repo, "commit", "-qm", "add layered")
    path.write_text("value = 2\n")

    assert workspace.architecture_changes(base, repo) == records(
        ("added", "layered.py"), ("modified", "layered.py")
    )


def test_committed_add_plus_worktree_delete_keeps_both_records(tmp_path):
    repo, base = repository(tmp_path)
    path = repo / "transient.py"
    path.write_text("value = 1\n")
    git(repo, "add", "transient.py")
    git(repo, "commit", "-qm", "add transient")
    path.unlink()

    assert workspace.architecture_changes(base, repo) == records(
        ("added", "transient.py"), ("deleted", "transient.py")
    )


def test_cached_modify_restored_in_worktree_still_reports_cached_fact(tmp_path):
    repo, base = repository(tmp_path)
    path = repo / "tracked.py"
    path.write_text("value = 2\n")
    git(repo, "add", "tracked.py")
    path.write_text("value = 1\n")

    assert workspace.architecture_changes(base, repo) == records(
        ("modified", "tracked.py"),
    )


def test_cached_modify_plus_worktree_delete_keeps_both_records(tmp_path):
    repo, base = repository(tmp_path)
    path = repo / "tracked.py"
    path.write_text("value = 2\n")
    git(repo, "add", "tracked.py")
    path.unlink()

    assert workspace.architecture_changes(base, repo) == records(
        ("deleted", "tracked.py"), ("modified", "tracked.py")
    )


def test_rename_is_deleted_plus_added_and_copy_destination_is_added(tmp_path):
    repo, base = repository(tmp_path)
    git(repo, "mv", "old.py", "new.py")
    shutil.copyfile(repo / "tracked.py", repo / "copy.py")
    git(repo, "add", "copy.py")

    assert workspace.architecture_changes(base, repo) == records(
        ("added", "copy.py"),
        ("added", "new.py"),
        ("deleted", "old.py"),
    )


def test_docs_tests_and_support_are_included_but_harness_is_excluded(tmp_path):
    repo, base = repository(tmp_path)
    for name in ("docs/new.md", "tests/test_new.py", "README.md", ".harness/state.yaml"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(name)

    changed = workspace.architecture_changes(base, repo)

    assert changed == records(
        ("untracked", "README.md"),
        ("untracked", "docs/new.md"),
        ("untracked", "tests/test_new.py"),
    )


def test_path_index_uses_tracked_minus_deleted_plus_untracked(tmp_path):
    repo, _base = repository(tmp_path)
    (repo / "tracked.py").unlink()
    (repo / "staged.py").write_text("staged = True\n")
    git(repo, "add", "staged.py")
    (repo / "untracked.py").write_text("untracked = True\n")
    (repo / ".harness").mkdir()
    (repo / ".harness" / "ignored.py").write_text("ignored = True\n")

    assert workspace.architecture_path_index(repo) == (
        "old.py",
        "staged.py",
        "untracked.py",
    )


def _mock_outputs(monkeypatch, change_output: bytes) -> None:
    calls = 0

    def run(_root, *args):
        nonlocal calls
        if args[:2] == ("rev-parse", "--verify"):
            return b"a" * 40 + b"\n"
        if args[0] == "diff":
            calls += 1
            return change_output if calls == 1 else b""
        if args[:3] == ("ls-files", "--others", "--exclude-standard"):
            return b""
        raise AssertionError(args)

    monkeypatch.setattr(workspace, "_run", run)


@pytest.mark.parametrize("status", [b"U", b"X", b"B", b"R100", b"Z"])
def test_adapter_fails_closed_for_unsupported_status(monkeypatch, tmp_path, status):
    _mock_outputs(monkeypatch, status + b"\0path.py\0")

    with pytest.raises(WorkspaceError, match="^ARCHITECTURE_CHANGESET_INVALID$"):
        workspace.architecture_changes("base", tmp_path)


@pytest.mark.parametrize(
    "output",
    [
        b"M\0\xff.py\0",
        b"M\0/absolute.py\0",
        b"M\0../outside.py\0",
        b"M\0src/../outside.py\0",
        b"M\0src\\file.py\0",
        b"M\0src//file.py\0",
        b"M\0.\0",
        b"M\0path.py",
    ],
)
def test_adapter_fails_closed_for_invalid_git_path_or_framing(
    monkeypatch, tmp_path, output
):
    _mock_outputs(monkeypatch, output)

    with pytest.raises(WorkspaceError, match="^ARCHITECTURE_CHANGESET_INVALID$"):
        workspace.architecture_changes("base", tmp_path)

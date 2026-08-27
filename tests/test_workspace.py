"""Repository-state snapshots used by evidence, Gate, status, and review."""

import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def committed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "tracked.py").write_text("value = 1\n")
    git(repo, "add", "tracked.py")
    git(repo, "commit", "-qm", "base")
    return repo


def test_snapshot_lists_all_business_changes_and_ignores_harness(tmp_path):
    """Break caught: a dirty/staged/untracked implementation file escapes evidence scope."""
    from harness.workspace import snapshot

    repo = committed_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    (repo / "staged.py").write_text("staged = True\n")
    git(repo, "add", "staged.py")
    (repo / "untracked.py").write_text("untracked = True\n")
    (repo / ".harness").mkdir()
    (repo / ".harness" / "runtime.json").write_text("{}")

    state = snapshot(repo)

    assert state.changed_paths == ("staged.py", "tracked.py", "untracked.py")
    assert state.fingerprint.startswith("sha256:")
    assert len(state.fingerprint) == 71


def test_review_scope_with_base_at_head_includes_dirty_and_untracked_files(tmp_path):
    """Break caught: base==HEAD produces empty complexity review despite workspace changes."""
    from harness.workspace import review_scope

    repo = committed_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    (repo / "new_service.py").write_text("enabled = True\n")

    scope = review_scope("HEAD", repo)

    assert scope.base_commit == scope.head_commit
    assert scope.files == ("new_service.py", "tracked.py")


def test_review_scope_includes_committed_delta_from_merge_base(tmp_path):
    """Break caught: committed changes between base and HEAD are absent from review scope."""
    from harness.workspace import review_scope

    repo = committed_repo(tmp_path)
    (repo / "committed.py").write_text("committed = True\n")
    git(repo, "add", "committed.py")
    git(repo, "commit", "-qm", "feature")

    scope = review_scope("HEAD~1", repo)

    assert scope.files == ("committed.py",)
    assert scope.base_commit == git(repo, "rev-parse", "HEAD~1")
    assert scope.head_commit == git(repo, "rev-parse", "HEAD")

"""Repository-state snapshots used by evidence, Gate, status, and review."""

import subprocess
from pathlib import Path

import pytest


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


def test_product_fingerprint_ignores_tracked_and_untracked_harness_metadata(tmp_path):
    """Break caught: writing requirement verification stale-s product evidence."""
    from harness.workspace import control_plane_fingerprint, snapshot

    repo = committed_repo(tmp_path)
    harness = repo / ".harness"
    harness.mkdir()
    (harness / "requirements.yaml").write_text("requirements: []\n")
    git(repo, "add", "-f", ".harness/requirements.yaml")
    git(repo, "commit", "-qm", "track harness")
    before = snapshot(repo)
    control_before = control_plane_fingerprint(harness)

    (harness / "requirements.yaml").write_text("requirements: [{id: REQ-001}]\n")
    (harness / "evidence").mkdir()
    (harness / "evidence" / "unit-test.json").write_text("{}\n")
    after = snapshot(repo)

    assert after.fingerprint == before.fingerprint
    assert after.changed_paths == before.changed_paths
    assert control_plane_fingerprint(harness) != control_before


def test_product_fingerprint_changes_when_covered_product_test_changes(tmp_path):
    """Break caught: editing a product test leaves evidence marked fresh."""
    from harness.workspace import snapshot

    repo = committed_repo(tmp_path)
    backend = repo / "backend" / "tests"
    backend.mkdir(parents=True)
    target = backend / "test_foo.py"
    target.write_text("def test_ok():\n    assert True\n")
    git(repo, "add", "backend/tests/test_foo.py")
    git(repo, "commit", "-qm", "product tests")
    before = snapshot(repo).fingerprint
    target.write_text("def test_ok():\n    assert False\n")

    assert snapshot(repo).fingerprint != before


def test_changed_paths_since_includes_committed_and_working_paths(tmp_path):
    from harness.workspace import changed_paths_since

    repo = committed_repo(tmp_path)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (repo / "committed.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "committed.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "change"], cwd=repo, check=True)
    (repo / "working.py").write_text("value = 2\n")

    assert changed_paths_since(base, repo) == ("committed.py", "working.py")


def test_protected_paths_fingerprint_changes_when_preexisting_dirty_file_changes(
    tmp_path,
):
    from harness.workspace import protected_paths_fingerprint

    repo = committed_repo(tmp_path)
    path = repo / "tracked.py"
    path.write_text("value = 2\n")
    before = protected_paths_fingerprint(("tracked.py",), repo)
    path.write_text("value = 3\n")

    assert protected_paths_fingerprint(("tracked.py",), repo) != before


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


def test_v2_user_change_fingerprint_preserves_unadopted_path_baseline(tmp_path):
    from harness.workspace import (
        aggregate_protected_path_fingerprints,
        protected_path_fingerprints,
        protected_user_changes_fingerprint,
    )

    repo = committed_repo(tmp_path)
    (repo / "other.py").write_text("value = 1\n")
    git(repo, "add", "other.py")
    git(repo, "commit", "-qm", "add other")
    baseline = protected_path_fingerprints(("other.py", "tracked.py"), repo)
    (repo / "tracked.py").write_text("value = 2\n")
    user_changes = {
        "version": 2,
        "paths": ["other.py"],
        "path_fingerprints": {"other.py": baseline["other.py"]},
        "fingerprint": aggregate_protected_path_fingerprints(
            {"other.py": baseline["other.py"]}
        ),
    }

    assert protected_user_changes_fingerprint(user_changes, repo_root=repo) == user_changes["fingerprint"]


def test_v2_git_fingerprint_handles_tracked_deletion(tmp_path):
    from harness.workspace import protected_path_fingerprints

    repo = committed_repo(tmp_path)
    baseline = protected_path_fingerprints(("tracked.py",), repo)
    (repo / "tracked.py").unlink()
    assert protected_path_fingerprints(("tracked.py",), repo) != baseline


def test_v2_missing_untracked_path_fails_closed(tmp_path):
    from harness.workspace import WorkspaceError, protected_path_fingerprints

    repo = committed_repo(tmp_path)
    path = repo / "user.md"
    path.write_text("baseline\n")
    protected_path_fingerprints(("user.md",), repo)
    path.unlink()
    with pytest.raises(WorkspaceError):
        protected_path_fingerprints(("user.md",), repo)


def test_v2_protected_fingerprint_detects_changed_path(tmp_path):
    from harness.workspace import (
        aggregate_protected_path_fingerprints,
        protected_path_fingerprints,
        protected_user_changes_fingerprint,
    )

    repo = committed_repo(tmp_path)
    baseline = protected_path_fingerprints(("tracked.py",), repo)
    user_changes = {
        "version": 2,
        "paths": ["tracked.py"],
        "path_fingerprints": baseline,
        "fingerprint": aggregate_protected_path_fingerprints(baseline),
    }
    (repo / "tracked.py").write_text("value = 2\n")

    assert protected_user_changes_fingerprint(user_changes, repo_root=repo) != user_changes["fingerprint"]


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("staged_baseline", [False, True])
def test_protected_fingerprint_binds_index_separately(
    tmp_path, version, staged_baseline
):
    from harness import workspace

    repo = committed_repo(tmp_path)
    path = repo / "tracked.py"
    if staged_baseline:
        path.write_text("value = 2\n")
        git(repo, "add", "tracked.py")
    fingerprint = (
        workspace.protected_paths_fingerprint
        if version == 1
        else workspace.protected_path_fingerprints
    )
    before = fingerprint(("tracked.py",), repo)
    if staged_baseline:
        git(repo, "restore", "--staged", "tracked.py")
    else:
        path.write_text("value = 2\n")
        git(repo, "add", "tracked.py")
        path.write_text("value = 1\n")

    assert fingerprint(("tracked.py",), repo) != before


@pytest.mark.parametrize("version", [1, 2])
def test_protected_index_fix_preserves_unstaged_legacy_digest(tmp_path, version):
    import hashlib

    from harness import workspace

    repo = committed_repo(tmp_path)
    (repo / "tracked.py").write_text("value = 2\n")
    diff = workspace._run(repo, "diff", "--binary", "HEAD", "--", "tracked.py")
    material = b"\0".join([b"tracked.py", diff])
    legacy = (
        "sha256:"
        + hashlib.sha256(material if version == 1 else material + b"\0").hexdigest()
    )
    if version == 1:
        assert workspace.protected_paths_fingerprint(("tracked.py",), repo) == legacy
    else:
        assert (
            workspace.protected_path_fingerprints(("tracked.py",), repo)["tracked.py"]
            == legacy
        )


def test_untracked_symlink_is_refused_without_reading_target(tmp_path):
    from harness import workspace

    repo = committed_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("outside bytes")
    (repo / "link").symlink_to(outside)

    with pytest.raises(
        workspace.WorkspaceError, match="WORKSPACE_UNTRACKED_FILE_UNSAFE"
    ):
        workspace.snapshot(repo)


def test_untracked_file_fingerprint_enforces_size_limit(tmp_path, monkeypatch):
    from harness import workspace

    repo = committed_repo(tmp_path)
    monkeypatch.setattr(workspace, "MAX_UNTRACKED_FILE_BYTES", 16, raising=False)
    path = repo / "large"
    path.write_bytes(b"x" * 17)

    with pytest.raises(
        workspace.WorkspaceError, match="WORKSPACE_UNTRACKED_FILE_TOO_LARGE"
    ):
        workspace.snapshot(repo)


def test_untracked_file_at_size_limit_is_accepted(tmp_path, monkeypatch):
    from harness import workspace

    repo = committed_repo(tmp_path)
    monkeypatch.setattr(workspace, "MAX_UNTRACKED_FILE_BYTES", 16, raising=False)
    (repo / "bounded").write_bytes(b"x" * 16)
    assert workspace.snapshot(repo).fingerprint.startswith("sha256:")


def test_untracked_reader_refuses_symlink_directory_components(tmp_path):
    from harness import workspace

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data").write_text("external")
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(
        workspace.WorkspaceError, match="WORKSPACE_UNTRACKED_FILE_UNSAFE"
    ):
        workspace._untracked_digest(root / "link/data", root)
    with pytest.raises(
        workspace.WorkspaceError, match="WORKSPACE_UNTRACKED_FILE_UNSAFE"
    ):
        workspace._untracked_digest(root / "link/data", root / "link")


def test_untracked_reader_limits_actual_bytes_not_only_stat_size(tmp_path, monkeypatch):
    import os
    import stat
    from types import SimpleNamespace

    from harness import workspace

    path = tmp_path / "grew"
    path.write_bytes(b"x" * 17)
    monkeypatch.setattr(workspace, "MAX_UNTRACKED_FILE_BYTES", 16)
    monkeypatch.setattr(
        workspace,
        "os",
        SimpleNamespace(
            fstat=lambda fd: SimpleNamespace(st_mode=stat.S_IFREG, st_size=0),
            read=os.read,
            close=os.close,
        ),
    )
    with pytest.raises(
        workspace.WorkspaceError, match="WORKSPACE_UNTRACKED_FILE_TOO_LARGE"
    ):
        workspace._untracked_digest(path, tmp_path)


def test_untracked_reader_rejects_fifo_without_blocking(tmp_path):
    import os
    import sys

    pipe = tmp_path / "pipe"
    os.mkfifo(pipe)
    command = (
        "from pathlib import Path; from harness.workspace import _untracked_digest, WorkspaceError; "
        '\ntry: _untracked_digest(Path.cwd()/"pipe", Path.cwd())'
        "\nexcept WorkspaceError: raise SystemExit(0)"
        "\nraise SystemExit(1)"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", command],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("regular-file adapter blocked while opening FIFO")
    assert result.returncode == 0, result.stderr


def test_snapshot_refuses_head_change_during_capture(tmp_path, monkeypatch):
    from harness import workspace

    repo = committed_repo(tmp_path)
    original = workspace._fingerprint

    def advance_after_fingerprint(*args, **kwargs):
        value = original(*args, **kwargs)
        (repo / "tracked.py").write_text("value = 2\n")
        git(repo, "add", "tracked.py")
        git(repo, "commit", "-qm", "advance during capture")
        return value

    monkeypatch.setattr(workspace, "_fingerprint", advance_after_fingerprint)
    with pytest.raises(workspace.WorkspaceError, match="WORKSPACE_HEAD_CHANGED"):
        workspace.snapshot(repo)


@pytest.mark.parametrize('name,risk_path', [
    ('docs/guide.md', False), ('tests/test_x.py', False), ('test/fixture.txt', False),
    ('README.md', False), ('src/config.py', True), ('src/notes.md', True),
])
def test_freshness_paths_are_distinct_from_fast_risk_paths(tmp_path, name, risk_path):
    from harness.risk_boundaries import business_paths
    from harness.workspace import snapshot

    repo = committed_repo(tmp_path)
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('first\n')
    git(repo, 'add', name)
    git(repo, 'commit', '-qm', 'track policy example')
    before = snapshot(repo).fingerprint
    path.write_text('second\n')
    after = snapshot(repo)

    assert before != after.fingerprint
    assert name in after.changed_paths
    assert (name in business_paths(after.changed_paths)) is risk_path

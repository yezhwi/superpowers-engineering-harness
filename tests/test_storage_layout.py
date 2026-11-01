"""Read-only identity contracts: ownership is not inferred from a directory name."""
import json

import pytest
from storage_factory import fixture_store, repository


def test_absent_store_keeps_legacy_without_creating_paths(tmp_path):
    from harness.storage import inspect_layout

    repo = repository(tmp_path)
    before = sorted(p.name for p in repo.iterdir())
    assert inspect_layout(repo).mode == "legacy"
    assert sorted(p.name for p in repo.iterdir()) == before


def test_bound_header_and_binding_require_exact_identity(tmp_path):
    from harness.storage import inspect_layout

    repo = repository(tmp_path)
    store, header, _ = fixture_store(repo)
    assert inspect_layout(repo).mode == "bound"
    header["workspace_identity"][1] += 1
    (store / "store.yaml").write_text(json.dumps(header))
    result = inspect_layout(repo)
    assert result.mode == "blocked"
    assert result.code == "STORE_IDENTITY_CHANGED"


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling", "fifo"])
def test_same_named_user_node_is_never_claimed(tmp_path, kind):
    import os

    from harness.storage import inspect_layout

    repo = repository(tmp_path)
    target = repo / ".harness-store"
    if kind == "directory":
        target.mkdir()
    elif kind in {"symlink", "dangling"}:
        target.symlink_to(repo / (".harness" if kind == "symlink" else "missing"))
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.write_text("user-owned")
    before = target.lstat()
    result = inspect_layout(repo)
    assert result.mode == "blocked"
    assert result.code == "STORE_UNOWNED"
    assert target.lstat().st_ino == before.st_ino


@pytest.mark.parametrize("change", ["capability", "header_version", "binding_version", "root_identity", "workspace_root"])
def test_bound_layout_rejects_mismatch_or_unsupported_reader(tmp_path, change):
    from harness.storage import inspect_layout

    repo = repository(tmp_path)
    store, header, binding = fixture_store(repo)
    if change == "capability":
        header["capabilities"].append("future/v99")
    elif change == "header_version":
        header["version"] = 99
    elif change == "binding_version":
        binding["version"] = 99
    elif change == "root_identity":
        binding["root_identity"][1] += 1
    else:
        header["workspace_root"] = str(tmp_path)
    (store / "store.yaml").write_text(json.dumps(header))
    (repo / ".harness/storage-binding.yaml").write_text(json.dumps(binding))
    assert inspect_layout(repo).mode == "blocked"


def test_worktrees_cannot_reuse_common_repository_store_identity(tmp_path):
    import subprocess

    from harness.storage import inspect_layout

    repo = repository(tmp_path)
    _, header, _ = fixture_store(repo)
    worktree = tmp_path / "other-worktree"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "fixture-other", str(worktree)],
                   cwd=repo, check=True, capture_output=True)
    from storage_factory import cli

    assert cli(worktree, "init").returncode == 0
    store, _, _ = fixture_store(worktree)
    (store / "store.yaml").write_text(json.dumps(header))
    result = inspect_layout(worktree)
    assert result.mode == "blocked"
    assert result.code == "STORE_IDENTITY_CHANGED"
    assert inspect_layout(repo).mode == "bound"


def test_dangling_binding_is_not_legacy(tmp_path):
    from harness.storage import inspect_layout

    repo = repository(tmp_path)
    (repo / ".harness/storage-binding.yaml").symlink_to(repo / "missing")
    assert inspect_layout(repo).mode == "blocked"


def test_storage_namespace_scope_does_not_grant_payload_reads(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import read_bytes, source_scope
    from harness.storage import inspect_layout
    from harness.storage.layout import observation_paths

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    secret = store / "private.txt"
    secret.write_text("undeclared payload")
    with pytest.raises(ContextBuildError, match="CONTEXT_REFERENCE_BROKEN"):
        with source_scope(repo, allowed=[repo, repo / ".harness", *observation_paths(repo / ".harness")]):
            assert inspect_layout(repo).mode == "bound"
            read_bytes(secret)


@pytest.mark.parametrize('gate_payload', ['gate: []\n', 'gate: null\n', 'gate: true\n'])
def test_malformed_gate_container_has_stable_layout_refusal(tmp_path, gate_payload):
    from harness.storage import inspect_layout

    repo = repository(tmp_path)
    fixture_store(repo)
    (repo / '.harness/gate.yaml').write_text(gate_payload)
    result = inspect_layout(repo)
    assert result.mode == 'blocked'
    assert result.code == 'STORE_READER_UNSUPPORTED'


def test_deep_malformed_layout_yaml_cannot_escape_as_recursion_traceback(tmp_path):
    from harness.storage import inspect_layout

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    (store / 'store.yaml').write_text('[' * 2000 + '0' + ']' * 2000)
    result = inspect_layout(repo)
    assert result.mode == 'blocked'
    assert result.code == 'STORE_IDENTITY_CHANGED'


def test_public_admission_preserves_typed_storage_refusal(tmp_path):
    from harness.storage import StorageError, admit_storage

    repo = repository(tmp_path)
    (repo / ".harness-store").mkdir()
    with pytest.raises(StorageError, match="STORE_UNOWNED"):
        with admit_storage(repo / ".harness"):
            pytest.fail("unowned store was admitted")


def test_late_coordination_membership_invalidates_observed_scope(tmp_path):
    from harness.context.model import ContextBuildError
    from harness.source_access import source_scope
    from harness.storage import inspect_layout
    from harness.storage.layout import observation_paths

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    pending = store / "operations/late.json"
    # Permit our deliberate external-writer simulation, not any production reader.
    allowed = [repo, repo / ".harness", *observation_paths(repo / ".harness"), pending]
    with pytest.raises(ContextBuildError, match="CONTEXT_STALE"):
        with source_scope(repo, allowed=allowed):
            assert inspect_layout(repo).mode == "bound"
            pending.write_text("{}")

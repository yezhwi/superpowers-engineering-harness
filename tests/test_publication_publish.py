"""Exact publish inputs and byte-preserving disposable stage handling."""

import os

import pytest

from harness import publication_fs as fs
from harness import transaction


@pytest.mark.parametrize('mutation', ['extra', 'payload'])
def test_publish_rejects_extra_stage_member_or_payload_drift(tmp_path, mutation):
    root = tmp_path / '.harness'
    declared = (transaction.StagedArtifact('impact.yaml', b'approved'),)
    staged = transaction.stage(root, list(declared))
    if mutation == 'extra':
        (staged / 'unexpected.yaml').write_bytes(b'unknown')
    else:
        (staged / 'impact.yaml').write_bytes(b'operator')
    with pytest.raises(OSError, match='STAGED_ARTIFACTS_CHANGED'):
        transaction.publish(root, staged, expected_artifacts=declared,
                            expected_sources={'impact.yaml': None})
    assert not (root / 'impact.yaml').exists()
    assert not (root / 'unexpected.yaml').exists()
    assert not list((root / '.transactions').glob('*'))


@pytest.mark.parametrize('sources', [{}, {'impact.yaml': None, 'extra.yaml': None}])
def test_expected_sources_requires_exact_members(tmp_path, sources):
    root = tmp_path / '.harness'
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'approved')])
    with pytest.raises(OSError, match='expected source'):
        transaction.publish(root, staged, expected_sources=sources)
    assert not (root / 'impact.yaml').exists()


def test_stage_symlink_cannot_import_outside_bytes(tmp_path):
    root = tmp_path / '.harness'
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'approved')])
    outside = tmp_path / 'operator'
    outside.write_bytes(b'outside bytes')
    (staged / 'impact.yaml').unlink()
    (staged / 'impact.yaml').symlink_to(outside)
    with pytest.raises(OSError):
        transaction.publish(root, staged)
    assert outside.read_bytes() == b'outside bytes'
    assert not (root / 'impact.yaml').exists()


def test_callback_stage_drift_aborts_without_deleting_unknown_bytes(tmp_path):
    root = tmp_path / '.harness'
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'approved')])

    def operator_edit():
        (staged / 'impact.yaml').write_bytes(b'unmanaged stage bytes')

    with pytest.raises(OSError, match='STAGED_ARTIFACTS_CHANGED'):
        transaction.publish(root, staged, after_publish=operator_edit)
    assert not (root / 'impact.yaml').exists()
    assert (staged / 'impact.yaml').read_bytes() == b'unmanaged stage bytes'


def test_race_at_success_stage_retention_keeps_unmanaged_bytes(tmp_path, monkeypatch):
    root = tmp_path / '.harness'
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'approved')])
    move = fs.move_noreplace
    injected = False

    def operator_at_retirement(*args):
        nonlocal injected
        if args[3] == 'input' and not injected:
            injected = True
            (staged / 'impact.yaml').write_bytes(b'unmanaged archive boundary bytes')
        return move(*args)

    monkeypatch.setattr(fs, 'move_noreplace', operator_at_retirement)
    with pytest.raises(OSError, match='STAGED_ARTIFACTS_CHANGED'):
        transaction.publish(root, staged)
    assert injected, 'native directory-retention hook must execute'
    assert (root / 'impact.yaml').read_bytes() == b'approved', 'postcommit housekeeping cannot compensate canonical state'
    assert b'unmanaged archive boundary bytes' in [path.read_bytes() for path in root.rglob('*') if path.is_file()]
    assert not list((root / '.transactions').iterdir())


def test_stale_stage_cleanup_never_unlinks_raced_unmanaged_inode(tmp_path, monkeypatch):
    root = tmp_path / '.harness'
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'approved')])
    unlink, move = os.unlink, fs.move_noreplace
    injected = False
    inode = None

    def edit():
        nonlocal injected, inode
        injected = True
        source = staged / 'operator-source'
        source.write_bytes(b'unmanaged stale-stage bytes')
        source.replace(staged / 'impact.yaml')
        inode = (staged / 'impact.yaml').stat().st_ino

    def raced_unlink(path, *args, **kwargs):
        if not injected and str(path).endswith('impact.yaml'):
            edit()
        return unlink(path, *args, **kwargs)

    def raced_move(*args):
        if args[3] == 'input' and not injected:
            edit()
        return move(*args)

    monkeypatch.setattr(os, 'unlink', raced_unlink)
    monkeypatch.setattr(fs, 'move_noreplace', raced_move)
    transaction.cleanup_stale_staging(root)
    assert injected
    kept = [path for path in root.rglob('*') if path.is_file() and path.stat().st_ino == inode]
    assert len(kept) == 1
    assert kept[0].read_bytes() == b'unmanaged stale-stage bytes'


def test_missing_target_concurrent_creation_cannot_be_replaced(tmp_path, monkeypatch):
    root = tmp_path / '.harness'
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'approved')])
    move = fs.move_noreplace
    injected = False

    def operator_creates(*args):
        nonlocal injected
        if args[3] == 'impact.yaml':
            injected = True
            (root / 'impact.yaml').write_bytes(b'operator created')
        return move(*args)

    monkeypatch.setattr(fs, 'move_noreplace', operator_creates)
    with pytest.raises(OSError):
        transaction.publish(root, staged, expected_sources={'impact.yaml': None})
    assert injected
    assert (root / 'impact.yaml').read_bytes() == b'operator created'


def test_stage_retention_compares_device_as_well_as_inode(tmp_path, monkeypatch):
    root = tmp_path / '.harness'
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'approved')])
    pinned = fs.open_directory(root)
    fstat = os.fstat

    def other_device(fd):
        value = fstat(fd)
        if fd == pinned:
            fields = list(value)
            fields[2] += 1
            return os.stat_result(fields)
        return value

    monkeypatch.setattr(os, 'fstat', other_device)
    try:
        with pytest.raises(OSError, match='STAGED_ARTIFACTS_CHANGED'):
            transaction._retain_stage(root, staged, root_fd=pinned)
        assert (staged / 'impact.yaml').read_bytes() == b'approved'
    finally:
        os.close(pinned)


def test_stale_cleanup_refuses_symlink_storage(tmp_path):
    root = tmp_path / '.harness'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'operator').write_bytes(b'operator bytes')
    (root / '.staging').symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        transaction.cleanup_stale_staging(root)
    assert (outside / 'operator').read_bytes() == b'operator bytes'


def test_retention_verifies_pinned_storage_before_writing_foreign_tree(tmp_path, monkeypatch):
    from harness import publication_journal

    root = tmp_path / '.harness'
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'approved')])
    retained = root / '.publication-retained'
    retained.mkdir()
    foreign = root / 'foreign'
    foreign.mkdir()
    opened = publication_journal._open_child
    injected = False

    def substituted(fd, name, **kwargs):
        nonlocal injected
        if name == '.publication-retained' and not injected:
            injected = True
            retained.rename(root / 'saved-retained')
            foreign.rename(retained)
            try:
                result = opened(fd, name, **kwargs)
            finally:
                retained.rename(foreign)
                (root / 'saved-retained').rename(retained)
            return result
        return opened(fd, name, **kwargs)

    monkeypatch.setattr(publication_journal, '_open_child', substituted)
    with pytest.raises(OSError, match='STAGED_ARTIFACTS_CHANGED'):
        transaction._retain_stage(root, staged)
    assert injected
    assert list(foreign.iterdir()) == []
    assert (staged / 'impact.yaml').read_bytes() == b'approved'


def test_stage_operation_collision_cannot_truncate_prior_bytes(tmp_path):
    root = tmp_path / '.harness'
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'original')], operation_id='fixed')
    (staged / 'impact.yaml').write_bytes(b'operator')
    with pytest.raises(FileExistsError):
        transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'replacement')], operation_id='fixed')
    assert (staged / 'impact.yaml').read_bytes() == b'operator'


@pytest.mark.parametrize('identifier', ['../escape', '/absolute', '..', ''])
def test_stage_rejects_invalid_operation_id_before_creating_root(tmp_path, identifier):
    root = tmp_path / '.harness'
    with pytest.raises(ValueError, match='STAGED_ARTIFACT_PATH_INVALID'):
        transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'value')], operation_id=identifier)
    assert not root.exists()


def test_stage_rejects_duplicate_payload_before_creating_root(tmp_path):
    root = tmp_path / '.harness'
    with pytest.raises(ValueError, match='STAGED_ARTIFACT_PATH_INVALID'):
        transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'a'),
                                 transaction.StagedArtifact('impact.yaml', b'b')])
    assert not root.exists()


def test_stage_transient_parent_substitution_never_writes_foreign_tree(tmp_path, monkeypatch):
    from pathlib import Path

    from harness import publication_journal

    root = tmp_path / '.harness'
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    opened = publication_journal._open_parent
    injected = False

    def substitute(fd, parent, **kwargs):
        nonlocal injected
        if parent == Path('nested') and kwargs.get('create') and not injected:
            injected = True
            os.mkdir('nested', dir_fd=fd)
            nested = root / '.staging/fixed/nested'
            saved = root / '.staging/fixed/saved'
            nested.rename(saved)
            foreign.rename(nested)
            try:
                result = opened(fd, parent, **kwargs)
            finally:
                nested.rename(foreign)
                saved.rename(nested)
            return result
        return opened(fd, parent, **kwargs)

    monkeypatch.setattr(publication_journal, '_open_parent', substitute)
    with pytest.raises(OSError, match='STAGED_ARTIFACTS_CHANGED'):
        transaction.stage(root, [transaction.StagedArtifact('nested/impact.yaml', b'value')], operation_id='fixed')
    assert injected
    assert list(foreign.iterdir()) == []

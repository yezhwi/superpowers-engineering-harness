"""Inode retention, forward publication, and abort share durable authority."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness.telemetry_lock import telemetry_lock


def journal():
    from harness import publication_journal

    return publication_journal


def retained(root):
    return [path for path in (root / '.publication-retained').rglob('*') if path.is_file()]


def test_commit_retains_displaced_inode_and_retires_active_record(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'original')
    inode = target.stat().st_ino
    with telemetry_lock(root), api.prepare(root, (api.Member('impact.yaml', b'original', b'new'),)) as operation:
        operation.apply()
        assert target.read_bytes() == b'new'
        assert list((root / '.transactions').iterdir())
        operation.commit()
    assert not list((root / '.transactions').iterdir())
    kept = [path for path in retained(root) if path.stat().st_ino == inode]
    assert len(kept) == 1
    assert kept[0].read_bytes() == b'original'


def test_held_fd_write_survives_terminal_handoff(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'current-task.yaml'
    target.write_bytes(b'original')
    held = os.open(target, os.O_RDWR)
    inode = os.fstat(held).st_ino
    try:
        with telemetry_lock(root), api.prepare(root, (api.Member('current-task.yaml', b'original', b'new'),)) as operation:
            operation.apply()
            operation.commit()
        os.write(held, b'late operator bytes')
        kept = [path for path in retained(root) if path.stat().st_ino == inode]
        assert len(kept) == 1
        assert kept[0].read_bytes() == b'late operator bytes'
        assert target.read_bytes() == b'new'
    finally:
        os.close(held)


def test_abort_restores_old_inodes_without_discarding_candidates(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    (root / 'impact.yaml').write_bytes(b'original impact')
    (root / 'seal.yaml').write_bytes(b'original seal')
    old = {name: (root / name).stat().st_ino for name in ('impact.yaml', 'seal.yaml')}
    members = (api.Member('impact.yaml', b'original impact', b'new impact'),
               api.Member('seal.yaml', b'original seal', b'new seal'),
               api.Member('created.yaml', None, b'created'))
    with telemetry_lock(root), api.prepare(root, members) as operation:
        operation.apply()
        operation.abort()
    assert (root / 'impact.yaml').read_bytes() == b'original impact'
    assert (root / 'seal.yaml').read_bytes() == b'original seal'
    assert {name: (root / name).stat().st_ino for name in old} == old
    assert not (root / 'created.yaml').exists()
    kept_bytes = [path.read_bytes() for path in retained(root)]
    assert b'new impact' in kept_bytes
    assert b'new seal' in kept_bytes
    assert b'created' in kept_bytes


def test_authorized_deletion_retains_original_inode(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'deleted.yaml'
    target.write_bytes(b'old mapping')
    inode = target.stat().st_ino
    with telemetry_lock(root), api.prepare(root, (api.Member('deleted.yaml', b'old mapping', None),)) as operation:
        operation.apply()
        assert not target.exists()
        operation.commit()
    kept = [path for path in retained(root) if path.stat().st_ino == inode]
    assert len(kept) == 1 and kept[0].read_bytes() == b'old mapping'


def test_concurrent_creation_is_not_overwritten(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'created.yaml'
    with telemetry_lock(root), api.prepare(root, (api.Member('created.yaml', None, b'candidate'),)) as operation:
        target.write_bytes(b'operator')
        with pytest.raises(OSError):
            operation.apply()
        assert target.read_bytes() == b'operator'
    assert target.read_bytes() == b'operator'


def test_unknown_canonical_bytes_block_abort_without_truncation(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'original')
    with telemetry_lock(root), api.prepare(root, (api.Member('impact.yaml', b'original', b'candidate'),)) as operation:
        operation.apply()
        target.write_bytes(b'operator')
        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
            operation.abort()
        preserved = [target.read_bytes(), *(path.read_bytes() for path in root.rglob('*') if path.is_file())]
        assert b'operator' in preserved
        assert b'original' in preserved
        assert list((root / '.transactions').iterdir())


@pytest.mark.parametrize('name', ['../escape', '/absolute', '.transactions/evil',
                                 '.publication-retained/evil', '.staging/evil'])
def test_prepare_rejects_recovery_storage_and_path_escape(tmp_path, name):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    with telemetry_lock(root), pytest.raises((OSError, ValueError)):
        api.prepare(root, (api.Member(name, None, b'candidate'),))
    assert not (tmp_path / 'escape').exists()


def test_prepare_requires_lock_before_creating_storage(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    with pytest.raises(OSError, match='lock required'):
        api.prepare(root, (api.Member('impact.yaml', None, b'candidate'),))
    assert list(root.iterdir()) == []


@pytest.mark.parametrize('boundary', ['apply_exchange', 'abort_exchange', 'apply_move',
                                      'abort_move', 'state_record', 'manifest', 'retirement'])
@pytest.mark.parametrize('moment', ['before', 'after'])
def test_kill_recovers_every_operation_boundary(tmp_path, boundary, moment):
    journal()
    from harness import transaction, transaction_recovery

    root = tmp_path / '.harness'
    root.mkdir()
    for name, content in [('impact.yaml', b'old impact'), ('deleted.yaml', b'old delete')]:
        (root / name).write_bytes(content)
    original_inodes = {(root / name).stat().st_ino for name in ('impact.yaml', 'deleted.yaml')}
    script = r'''
import os
from pathlib import Path
from harness import publication_fs as fs, publication_journal as api
from harness.telemetry_lock import telemetry_lock
root = Path(os.environ['FIXTURE_ROOT'])
boundary, moment = os.environ['BOUNDARY'], os.environ['MOMENT']
phase = 'apply'
exchange, move, write = fs.exchange, fs.move_noreplace, api._write_new
def crash(kind, when):
    if kind == boundary and when == moment:
        os._exit(91)
def exchanged(*args):
    if 'impact.yaml' in args:
        crash(phase + '_exchange', 'before')
    result = exchange(*args)
    if 'impact.yaml' in args:
        crash(phase + '_exchange', 'after')
    return result
def moved(*args):
    kind = 'retirement' if 'active.json' in args else phase + '_move'
    relevant = kind == 'retirement' or 'created.yaml' in args or 'deleted.yaml' in args
    if relevant:
        crash(kind, 'before')
    result = move(*args)
    if relevant:
        crash(kind, 'after')
    return result
def written(fd, name, document):
    kind = 'manifest' if name == 'manifest.json' else 'state_record' if name == 'state-00000001.json' else ''
    crash(kind, 'before')
    result = write(fd, name, document)
    crash(kind, 'after')
    return result
fs.exchange, fs.move_noreplace, api._write_new = exchanged, moved, written
members = (api.Member('impact.yaml', b'old impact', b'new impact'),
           api.Member('created.yaml', None, b'new created'),
           api.Member('deleted.yaml', b'old delete', None))
with telemetry_lock(root), api.prepare(root, members) as operation:
    operation.apply()
    if boundary.startswith('abort'):
        phase = 'abort'
        operation.abort()
    else:
        operation.commit()
os._exit(92)
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                                 'FIXTURE_ROOT': str(root), 'BOUNDARY': boundary, 'MOMENT': moment},
                            check=False, timeout=30)
    assert result.returncode == 91, f'kill hook missed: {result.returncode}: {result.stderr}'
    transaction.cleanup_stale_staging(root)
    with telemetry_lock(root):
        transaction_recovery.recover_pending_publications(root)
    before = (b'old impact', None, b'old delete')
    committed = (b'new impact', b'new created', None)
    current = tuple((root / name).read_bytes() if (root / name).exists() else None
                    for name in ('impact.yaml', 'created.yaml', 'deleted.yaml'))
    assert current in (before, committed), 'restart must not expose a mixed known operation'
    all_inodes = {path.stat().st_ino for path in root.rglob('*') if path.is_file()}
    assert original_inodes <= all_inodes, 'even committed old objects remain retained'
    assert not list((root / '.transactions').iterdir())


def test_parent_substitution_never_targets_new_tree(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    (root / 'context').mkdir()
    target = root / 'context/current.yaml'
    target.write_bytes(b'original')
    with telemetry_lock(root), api.prepare(root, (api.Member('context/current.yaml', b'original', b'new'),)) as operation:
        (root / 'context').rename(root / 'moved-context')
        (root / 'context').mkdir()
        target.write_bytes(b'operator')
        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
            operation.apply()
    assert target.read_bytes() == b'operator'
    assert (root / 'moved-context/current.yaml').read_bytes() == b'original'


def test_retention_only_does_not_block_next_operation(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    (root / 'impact.yaml').write_bytes(b'original')
    for before, after in ((b'original', b'first'), (b'first', b'second')):
        with telemetry_lock(root), api.prepare(root, (api.Member('impact.yaml', before, after),)) as operation:
            operation.apply()
            operation.commit()
    assert (root / 'impact.yaml').read_bytes() == b'second'
    assert b'original' in [path.read_bytes() for path in retained(root)]


def test_unknown_active_version_refuses_without_mutation(tmp_path):
    journal()
    from harness import transaction_recovery

    root = tmp_path / '.harness'
    (root / '.transactions').mkdir(parents=True)
    active = root / '.transactions/unknown.json'
    active.write_text(json.dumps({'version': 99}))
    before = active.read_bytes()
    with telemetry_lock(root), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        transaction_recovery.recover_pending_publications(root)
    assert active.read_bytes() == before


def test_unknown_slot_blocks_commit_without_cleaning_bytes(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    (root / 'impact.yaml').write_bytes(b'original')
    with telemetry_lock(root), api.prepare(root, (api.Member('impact.yaml', b'original', b'new'),)) as operation:
        operation.apply()
        storage = next((root / '.publication-retained').iterdir())
        unknown = storage / 'operator-notes'
        unknown.write_bytes(b'unmanaged private object')
        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
            operation.commit()
        assert unknown.read_bytes() == b'unmanaged private object'
        assert list((root / '.transactions').iterdir())


def test_terminal_active_recovery_does_not_adopt_external_edit(tmp_path, monkeypatch):
    api = journal()
    from harness import publication_fs, transaction_recovery

    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'original')
    move = publication_fs.move_noreplace

    def leave_active(*args):
        if 'active.json' in args:
            raise OSError('injected before retirement')
        return move(*args)

    with telemetry_lock(root), api.prepare(root, (api.Member('impact.yaml', b'original', b'new'),)) as operation:
        operation.apply()
        with monkeypatch.context() as patch:
            patch.setattr(publication_fs, 'move_noreplace', leave_active)
            with pytest.raises(OSError, match='injected before retirement'):
                operation.commit()
    target.write_bytes(b'operator')
    with telemetry_lock(root), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        transaction_recovery.recover_pending_publications(root)
    assert target.read_bytes() == b'operator'
    assert list((root / '.transactions').iterdir())


@pytest.mark.parametrize('change', ['corrupt_chain', 'unknown_slot', 'symlink_slot'])
def test_recovery_blocks_unknown_storage_without_destroying_it(tmp_path, change):
    api = journal()
    from harness import transaction_recovery

    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'original')
    with telemetry_lock(root), api.prepare(root, (api.Member('impact.yaml', b'original', b'new'),)) as operation:
        operation.apply()
    storage = next((root / '.publication-retained').iterdir())
    if change == 'corrupt_chain':
        record = storage / 'state-00000001.json'
        document = json.loads(record.read_text())
        document['previous'] = '0' * 64
        record.write_text(json.dumps(document))
    elif change == 'symlink_slot':
        (storage / 'new-0').rename(storage / 'saved-original')
        (storage / 'new-0').symlink_to(target)
    else:
        (storage / 'unknown').write_bytes(b'operator notes')
    before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    with telemetry_lock(root), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        transaction_recovery.recover_pending_publications(root)
    after = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    assert after == before


def test_deletion_recreation_cannot_be_overwritten_by_abort(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'deleted.yaml'
    target.write_bytes(b'original')
    with telemetry_lock(root), api.prepare(root, (api.Member('deleted.yaml', b'original', None),)) as operation:
        operation.apply()
        target.write_bytes(b'operator recreation')
        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
            operation.abort()
        assert target.read_bytes() == b'operator recreation'
        assert b'original' in [path.read_bytes() for path in root.rglob('*') if path.is_file()]


@pytest.mark.parametrize('phase', ['apply', 'abort'])
@pytest.mark.parametrize('writer', ['in_place', 'rename'])
def test_operator_edit_at_atomic_boundary_is_retained(tmp_path, monkeypatch, phase, writer):
    api = journal()
    from harness import publication_fs

    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'original')
    exchange = publication_fs.exchange
    injected = False

    def operator_edit(*args):
        nonlocal injected
        if 'impact.yaml' in args:
            injected = True
            if writer == 'in_place':
                target.write_bytes(b'operator boundary bytes')
            else:
                candidate = root / 'operator-source'
                candidate.write_bytes(b'operator boundary bytes')
                candidate.replace(target)
        return exchange(*args)

    with telemetry_lock(root), api.prepare(root, (api.Member('impact.yaml', b'original', b'new'),)) as operation:
        if phase == 'abort':
            operation.apply()
        monkeypatch.setattr(publication_fs, 'exchange', operator_edit)
        with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
            operation.apply() if phase == 'apply' else operation.abort()
        assert injected
        assert b'operator boundary bytes' in [path.read_bytes() for path in root.rglob('*') if path.is_file()]
        assert list((root / '.transactions').iterdir())


def test_recovery_cannot_silently_rebind_relocated_root(tmp_path):
    api = journal()
    from harness import transaction_recovery

    root = tmp_path / '.harness'
    root.mkdir()
    (root / 'impact.yaml').write_bytes(b'original')
    with telemetry_lock(root), api.prepare(root, (api.Member('impact.yaml', b'original', b'new'),)) as operation:
        operation.apply()
    moved = tmp_path / 'moved-harness'
    root.rename(moved)
    with telemetry_lock(moved), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        transaction_recovery.recover_pending_publications(moved)
    assert (moved / 'impact.yaml').read_bytes() == b'new'
    assert b'original' in [path.read_bytes() for path in moved.rglob('*') if path.is_file()]


def test_no_pending_admission_is_read_only_and_ignores_terminal_retention(tmp_path):
    api = journal()
    from harness import transaction_recovery

    root = tmp_path / '.harness'
    root.mkdir()
    with telemetry_lock(root):
        transaction_recovery.require_no_pending_publications(root)
        assert list(root.iterdir()) == []
        with api.prepare(root, (api.Member('impact.yaml', None, b'new'),)) as operation:
            before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
            with pytest.raises(OSError, match='TRANSACTION_RECOVERY_REQUIRED'):
                transaction_recovery.require_no_pending_publications(root)
            assert {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()} == before
            operation.apply()
            operation.commit()
        transaction_recovery.require_no_pending_publications(root)


def test_duplicate_member_or_expected_drift_never_publishes(tmp_path):
    api = journal()
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'operator')
    with telemetry_lock(root):
        with pytest.raises(OSError):
            api.prepare(root, (api.Member('impact.yaml', b'old', b'new'),))
        with pytest.raises(OSError):
            api.prepare(root, (api.Member('impact.yaml', b'operator', b'a'),
                               api.Member('impact.yaml', b'operator', b'b')))
    assert target.read_bytes() == b'operator'
    assert not list((root / '.transactions').iterdir())


def test_recovery_verifies_stored_parent_fd_not_only_named_parent(tmp_path, monkeypatch):
    api = journal()
    from harness import transaction_recovery

    root = tmp_path / '.harness'
    root.mkdir()
    parent = root / 'context'
    parent.mkdir()
    (parent / 'current.yaml').write_bytes(b'original')
    foreign = root / 'foreign'
    foreign.mkdir()
    with telemetry_lock(root), api.prepare(root, (api.Member('context/current.yaml', b'original', None),)) as operation:
        operation.apply()
    opened = api._open_parent
    injected = False

    def transient_parent(fd, path, **kwargs):
        nonlocal injected
        if not injected and path == Path('context'):
            injected = True
            parent.rename(root / 'saved')
            foreign.rename(parent)
            try:
                result = opened(fd, path, **kwargs)
            finally:
                parent.rename(foreign)
                (root / 'saved').rename(parent)
            return result
        return opened(fd, path, **kwargs)

    monkeypatch.setattr(api, '_open_parent', transient_parent)
    with telemetry_lock(root), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        transaction_recovery.recover_pending_publications(root)
    assert injected
    assert not (foreign / 'current.yaml').exists(), 'recovery must never mutate foreign pinned tree'
    assert list((root / '.transactions').iterdir())


def test_recovery_rejects_illegal_committed_tail_transition(tmp_path):
    api = journal()
    from harness import transaction_recovery

    root = tmp_path / '.harness'
    root.mkdir()
    (root / 'impact.yaml').write_bytes(b'original')
    with telemetry_lock(root), api.prepare(root, (api.Member('impact.yaml', b'original', b'new'),)) as operation:
        operation.apply()
    storage = next((root / '.publication-retained').iterdir())
    tail = max(storage.glob('state-*.json'))
    frame = json.loads(tail.read_bytes())
    assert frame['operation']['state'] == 'VALIDATING'
    frame['operation']['state'] = 'COMMITTED'
    # Preserve exact canonical encoding and predecessor digest; only illegal state changes.
    tail.write_bytes(json.dumps(frame, sort_keys=True, separators=(',', ':')).encode())
    before = {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    with telemetry_lock(root), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        transaction_recovery.recover_pending_publications(root)
    assert {str(path): path.read_bytes() for path in root.rglob('*') if path.is_file()} == before

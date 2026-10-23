"""EF-T06/07: restart recovery survives staging cleanup and never reverts user bytes."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import publication_fs, transaction
from harness.telemetry_lock import telemetry_lock


@pytest.mark.parametrize('members', [
    ('current-task.yaml', 'context/expansions.yaml'),
    ('impact.yaml', 'test-scope-audit.yaml', 'test-scope-seal.yaml'),
    ('context/current.yaml', 'context/manifest.yaml', 'context/evidence.yaml'),
])
def test_recovery_after_process_kill_survives_staging_cleanup(tmp_path, members):
    root = tmp_path / '.harness'
    root.mkdir()
    for name in members:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'old')
    repo = Path(__file__).resolve().parents[1]
    # Kill at real native member publication; stage retirement cannot affect journal.
    script = '''
import os
from pathlib import Path
from harness import publication_fs, transaction
from harness.telemetry_lock import telemetry_lock
root = Path(ROOT)
members = MEMBERS
staged = transaction.stage(root, [transaction.StagedArtifact(n, b'new') for n in members])
original = publication_fs.exchange
def killed(*args):
    result = original(*args)
    if args[1] == Path(members[0]).name:
        os._exit(91)
    return result
publication_fs.exchange = killed
with telemetry_lock(root):
    transaction.publish(root, staged, replace_paths=frozenset(members), durable=True)
'''.replace('ROOT', repr(str(root))).replace('MEMBERS', repr(members))
    result = subprocess.run([sys.executable, '-c', script], env={**os.environ, 'PYTHONPATH': str(repo / 'src')}, capture_output=True, text=True, check=False, timeout=20)
    assert result.returncode == 91, result.stderr
    assert any((root / '.transactions').iterdir())
    transaction.cleanup_stale_staging(root)
    with telemetry_lock(root):
        transaction.recover_pending_publications(root)
    assert [(root / name).read_bytes() for name in members] == [b'old'] * len(members)
    assert not list((root / '.transactions').iterdir())


@pytest.mark.parametrize('durable', [False, True])
def test_post_check_external_edit_is_not_destroyed_by_replace(tmp_path, monkeypatch, durable):
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'current-task.yaml'
    target.write_bytes(b'original task')
    staged = transaction.stage(root, [transaction.StagedArtifact('current-task.yaml', b'published task')])
    replace = Path.replace
    exchange = publication_fs.exchange
    inode = target.stat().st_ino
    injected = False

    def operator_edit_at_replace(path, destination):
        nonlocal injected
        if Path(destination) == target and not injected:
            injected = True
            target.write_bytes(b'unmanaged operator task')
        return replace(path, destination)

    def operator_edit_at_exchange(*args):
        nonlocal injected
        if 'current-task.yaml' in args and not injected:
            injected = True
            target.write_bytes(b'unmanaged operator task')
        return exchange(*args)

    monkeypatch.setattr(Path, 'replace', operator_edit_at_replace)
    monkeypatch.setattr(publication_fs, 'exchange', operator_edit_at_exchange)
    error = None
    with telemetry_lock(root):
        try:
            transaction.publish(root, staged, replace_paths=frozenset({'current-task.yaml'}),
                                expected_sources={'current-task.yaml': b'original task'}, durable=durable)
        except OSError as exc:
            error = exc
    assert injected, 'race injection must execute at actual replacement boundary'
    kept = [path for path in root.rglob('*') if path.is_file()
            and path.stat().st_ino == inode and path.read_bytes() == b'unmanaged operator task']
    assert len(kept) == 1, 'unmanaged actual inode must survive canonically or at retained location'
    assert error is not None, 'unmanaged race must halt publication, not report success'


@pytest.mark.parametrize('durable', [False, True])
def test_failure_rollback_does_not_overwrite_unmanaged_edit(tmp_path, durable):
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'old')
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'ours')])
    def user_edit_then_fail():
        target.write_bytes(b'user bytes')
        raise OSError('publication failed')
    with telemetry_lock(root), pytest.raises(OSError):
        transaction.publish(root, staged, replace_paths=frozenset({'impact.yaml'}), after_publish=user_edit_then_fail, durable=durable)
    assert target.read_bytes() == b'user bytes'
    if durable:
        with telemetry_lock(root), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
            transaction.recover_pending_publications(root)
        assert target.read_bytes() == b'user bytes'


def test_rollback_restores_owned_sibling_without_following_user_symlink(tmp_path):
    root = tmp_path / '.harness'
    root.mkdir()
    task = root / 'current-task.yaml'
    log = root / 'expansions.yaml'
    task.write_bytes(b'old task')
    log.write_bytes(b'old log')
    user = tmp_path / 'user'
    user.write_bytes(b'user bytes')
    staged = transaction.stage(root, [transaction.StagedArtifact('current-task.yaml', b'new task'),
                                      transaction.StagedArtifact('expansions.yaml', b'new log')])
    def user_symlink():
        task.unlink()
        task.symlink_to(user)
        raise OSError('publication failed')
    with telemetry_lock(root), pytest.raises(OSError):
        transaction.publish(root, staged, replace_paths=frozenset({'current-task.yaml', 'expansions.yaml'}), after_publish=user_symlink, durable=True)
    assert user.read_bytes() == b'user bytes'
    assert task.is_symlink()
    assert log.read_bytes() == b'old log'
    assert list((root / '.transactions').iterdir())


def test_keyboardinterrupt_rolls_back_owned_members(tmp_path):
    root = tmp_path / '.harness'
    root.mkdir()
    target = root / 'impact.yaml'
    target.write_bytes(b'old')
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'ours')])
    def interrupt():
        raise KeyboardInterrupt
    with telemetry_lock(root), pytest.raises(KeyboardInterrupt):
        transaction.publish(root, staged, replace_paths=frozenset({'impact.yaml'}), after_publish=interrupt, durable=True)
    assert target.read_bytes() == b'old'
    assert not list((root / '.transactions').iterdir())


def test_committed_publication_recovery_is_idempotent(tmp_path):
    root = tmp_path / '.harness'
    root.mkdir()
    staged = transaction.stage(root, [transaction.StagedArtifact('impact.yaml', b'new')])
    with telemetry_lock(root):
        transaction.publish(root, staged, durable=True)
        transaction.recover_pending_publications(root)
        transaction.recover_pending_publications(root)
    assert (root / 'impact.yaml').read_bytes() == b'new'


@pytest.mark.parametrize('attack', ['symlink', 'invalid_json', 'unknown_member'])
def test_invalid_journal_stops_without_cleaning_user_bytes(tmp_path, attack):
    root = tmp_path / '.harness'
    root.mkdir()
    directory = root / '.transactions'
    directory.mkdir()
    target = directory / 'operation.json'
    if attack == 'symlink':
        outside = tmp_path / 'user'
        outside.write_bytes(b'user bytes')
        target.symlink_to(outside)
    elif attack == 'invalid_json':
        target.write_bytes(b'{broken')
    else:
        target.write_bytes(b'{"version":1,"state":"PREPARED","members":[{"path":"../escape"}]}')
    with telemetry_lock(root), pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        transaction.recover_pending_publications(root)
    assert target.exists()
    if attack == 'symlink':
        assert outside.read_bytes() == b'user bytes'

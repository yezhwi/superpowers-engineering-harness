"""Actual process death around native directory lifecycle boundaries."""
import json
import os
import subprocess
import sys

import pytest

from storage_factory import ROOT, cli, fixture_store, identity, repository
from storage_journal_factory import OP, activation_plan, turnover_plan

_SCRIPT = r'''
import json, os, sys
from harness.storage import admit_storage
from harness.storage.journal import prepare_activation, prepare_turnover
from harness.storage import journal
from harness import publication_fs as fs
from harness.telemetry_lock import telemetry_lock
from storage_journal_factory import authority
from pathlib import Path
value, boundary = json.loads(sys.argv[1]), sys.argv[2]
root = Path.cwd()/'.harness'
write, mkdir, move, sync = journal._write_new, os.mkdir, fs.move_noreplace, fs.sync_directory
moved = False

def die():
    os._exit(87)

def write_then_kill(fd, name, document):
    if (boundary == 'reservation-before-ack' and document.get('event') == 'ACK'
        and document.get('action') == 0):
        die()
    write(fd, name, document)
    if boundary == 'prepare' and document.get('version') == 3:
        die()
    event = document.get('event')
    if (boundary == 'intent' and event == 'INTENT' and document.get('action') == 0
        or boundary == 'ack' and event == 'ACK' and document.get('action') == 0
        or boundary == 'overlay-ack' and event == 'ACK' and document.get('action') == 4
        or boundary == 'commit-intent' and event == 'COMMIT_INTENT'
        or boundary == 'committed' and event == 'COMMITTED'
        or boundary == 'undo-intent' and event == 'UNDO_INTENT'
        or boundary == 'undone' and event == 'UNDONE'
        or boundary == 'aborted' and event == 'ABORTED'):
        die()

def mkdir_then_kill(name, *args, **kwargs):
    mkdir(name, *args, **kwargs)
    if boundary == 'create-before-ack' and str(name) == '.harness-store-prepare-' + value['operation_id']:
        die()

def move_then_kill(srcfd, src, dstfd, dst):
    global moved
    move(srcfd, src, dstfd, dst)
    if dst in {'.harness-store', 'previous'}:
        moved = True
        if boundary == 'move':
            die()
    if dst == 'index.yaml':
        moved = True
        if boundary == 'index-pointer':
            die()
    if boundary == 'new-root' and dst == '.harness':
        die()
    if boundary == 'frames-retired' and dst == 'storage-' + value['operation_id']:
        die()
    if boundary == 'retired' and dst == 'descriptor.json':
        die()
    if boundary == 'inverse-move' and src == '.harness' and dst == 'candidate':
        die()

def sync_then_kill(fd):
    sync(fd)
    if boundary == 'sync' and moved:
        die()

journal._write_new, os.mkdir = write_then_kill, mkdir_then_kill
fs.move_noreplace, fs.sync_directory = move_then_kill, sync_then_kill
with telemetry_lock(root):
    if value['operation'] == 'ACTIVATE':
        operation = prepare_activation(root, value, authority(value))
    else:
        with admit_storage(root) as session:
            operation = prepare_turnover(session, {'plan':value, 'authority':authority(value)})
    for action in value['actions']:
        operation.advance(action)
    if boundary in {'undo-intent','inverse-move','undone','aborted'}:
        operation.abort()
    else:
        operation.commit()
raise SystemExit('kill boundary was not reached')
'''


def killed(repo, value, boundary):
    result = subprocess.run([sys.executable, '-B', '-c', _SCRIPT, json.dumps(value), boundary],
                            cwd=repo, env={**os.environ, 'PYTHONPATH': f'{ROOT}/src:{ROOT}/tests'},
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 87, result.stdout + result.stderr


@pytest.mark.parametrize('boundary', ['prepare', 'intent', 'ack', 'move', 'sync', 'commit-intent',
                                      'committed', 'frames-retired', 'retired'])
def test_activation_kill_retains_objects_and_has_unambiguous_terminal_direction(tmp_path, boundary):
    from harness.storage import recover_operation

    repo = repository(tmp_path)
    value = activation_plan(repo)
    killed(repo, value, boundary)
    result = recover_operation(repo, OP)
    committed = boundary in {'committed', 'frames-retired', 'retired'}
    assert result['status'] == ('COMMITTED' if committed else 'ABORTED')
    assert (repo / '.harness').is_dir()
    assert (repo / '.harness-store').exists() == committed
    assert (repo / result['receipt']).is_file()
    assert recover_operation(repo, OP) == result


def test_creation_before_identity_ack_remains_blocked_and_untouched(tmp_path):
    from harness.storage import StorageError, recover_operation

    repo = repository(tmp_path)
    value = activation_plan(repo)
    killed(repo, value, 'create-before-ack')
    unknown = repo / value['actions'][0]['target']
    before = identity(unknown)
    with pytest.raises(StorageError, match='STORE_IDENTITY_CHANGED'):
        recover_operation(repo, OP)
    assert identity(unknown) == before
    assert (repo / '.harness/.transactions' / ('storage-activation-' + OP + '.json')).is_file()


@pytest.mark.parametrize('boundary', ['move', 'sync', 'new-root', 'commit-intent', 'committed',
                                      'undo-intent', 'inverse-move', 'undone', 'aborted', 'retired'])
def test_turnover_kill_uses_inode_not_root_name(tmp_path, boundary):
    from harness.storage import recover_operation

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    original = identity(repo / '.harness')
    value = turnover_plan(repo)
    candidate = identity(store / 'retained/roots' / OP / 'candidate')
    killed(repo, value, boundary)
    if not (repo / '.harness').exists():
        result = cli(repo, 'init')
        assert result.returncode == 2
        assert 'STORE_RECOVERY_REQUIRED' in result.stderr
        assert not (repo / '.harness').exists()
    result = recover_operation(repo, OP)
    committed = boundary in {'committed', 'retired'}
    assert result['status'] == ('COMMITTED' if committed else 'ABORTED')
    assert identity(repo / '.harness') == (candidate if committed else original)
    if not committed:
        assert identity(store / 'retained/roots' / OP / 'candidate') == candidate
    assert not list((store / 'operations').iterdir())


def test_bootstrap_pending_precedes_partially_installed_store_facts(tmp_path):
    """Init must not mistake operation-owned partial store for an unrelated root."""
    repo = repository(tmp_path)
    value = activation_plan(repo)
    killed(repo, value, 'move')
    result = cli(repo, 'init')
    assert result.returncode == 2
    assert 'STORE_RECOVERY_REQUIRED' in result.stderr
    assert (repo / '.harness/.transactions' / ('storage-activation-' + OP + '.json')).is_file()

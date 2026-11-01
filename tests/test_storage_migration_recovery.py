"""Real death during selected-grant activation/M1, not just generic moves."""
import json
import os
import subprocess
import sys

import pytest
import yaml
from test_context_builder import harness  # noqa: F401
from test_storage_activation import qualified_grant
from test_storage_migration import activate

from storage_factory import ROOT, cli, identity

_SCRIPT = r'''
import json,os,sys
from pathlib import Path
from harness.storage import apply_operation
from harness.storage import journal
from harness import publication_fs as fs
plan,decision,maintenance,boundary=json.loads(sys.argv[1]),sys.argv[2],json.loads(sys.argv[3]),sys.argv[4]
write,move,sync=journal._write_new,fs.move_noreplace,fs.sync_directory
moved=False
def die(): os._exit(87)
def after_write(fd,name,document):
    event=document.get('event')
    index=document.get('action')
    if boundary=='file-before-ack' and event=='ACK' and plan['actions'][index]['target'].endswith('/store.yaml'):
        die()
    write(fd,name,document)
    if boundary=='prepare' and document.get('version')==3: die()
    if boundary=='intent' and event=='INTENT' and index==0: die()
    if boundary=='binding' and event=='ACK' and plan['actions'][index]['target']=='.harness/storage-binding.yaml': die()
    if boundary=='commit-intent' and event=='COMMIT_INTENT': die()
    if boundary=='committed' and event=='COMMITTED': die()
def after_move(srcfd,src,dstfd,dst):
    global moved
    move(srcfd,src,dstfd,dst)
    if dst=='.harness-store' or (dst=='index.yaml' and src=='index-candidate.yaml'):
        moved=True
        if boundary=='pointer': die()
    if boundary=='retired' and dst=='descriptor.json': die()
def after_sync(fd):
    sync(fd)
    if boundary=='sync' and moved: die()
journal._write_new=after_write
fs.move_noreplace,fs.sync_directory=after_move,after_sync
apply_operation(Path.cwd(),plan,decision,maintenance)
raise SystemExit('boundary was not reached')
'''


def kill_apply(harness, plan, decision_id, maintenance, boundary):
    result = subprocess.run([sys.executable, '-B', '-c', _SCRIPT, json.dumps(plan), decision_id,
                             json.dumps(maintenance), boundary], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': f'{ROOT}/src:{ROOT}/tests'},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 87, result.stderr


@pytest.mark.parametrize('boundary', ['prepare', 'intent', 'pointer', 'sync', 'binding',
                                      'commit-intent', 'committed', 'retired'])
def test_activation_recovery_restores_previous_gate_or_finishes_commit(harness, boundary):
    from harness.storage import StorageRequest, inspect_layout, plan_operation, recover_operation

    gate_before = (harness / 'gate.yaml').read_bytes()
    root_before, gate_id = identity(harness), identity(harness / 'gate.yaml')
    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, plan)
    kill_apply(harness, plan, decision_id, maintenance, boundary)
    if boundary != 'retired':
        refused = cli(harness.parent, 'status')
        assert refused.returncode == 2
        assert 'RECOVERY_REQUIRED' in refused.stderr
    result = recover_operation(harness.parent, plan['operation_id'])
    committed = boundary in {'committed', 'retired'}
    assert result['status'] == ('COMMITTED' if committed else 'ABORTED')
    assert inspect_layout(harness.parent).mode == ('bound' if committed else 'legacy')
    assert identity(harness) == root_before
    if not committed:
        assert (harness / 'gate.yaml').read_bytes() == gate_before
        assert identity(harness / 'gate.yaml') == gate_id
    assert not list((harness / '.transactions').iterdir())


def test_read_only_inspection_reports_bootstrap_before_store_creation(harness):
    from harness.storage import StorageRequest, inspect_layout, plan_operation, recover_operation

    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, plan)
    kill_apply(harness, plan, decision_id, maintenance, 'prepare')
    assert not (harness.parent / '.harness-store').exists()
    inspected = inspect_layout(harness.parent)
    assert inspected.mode == 'blocked'
    assert inspected.code == 'STORE_RECOVERY_REQUIRED'
    assert recover_operation(harness.parent, plan['operation_id'])['status'] == 'ABORTED'


def test_preack_layout_file_is_never_adopted_even_inside_owned_prepare(harness):
    from harness.storage import StorageError, StorageRequest, plan_operation, recover_operation

    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, plan)
    kill_apply(harness, plan, decision_id, maintenance, 'file-before-ack')
    path = harness.parent / ('.harness-store-prepare-' + plan['operation_id']) / 'store.yaml'
    before = identity(path), path.read_bytes()
    with pytest.raises(StorageError, match='STORE_IDENTITY_CHANGED'):
        recover_operation(harness.parent, plan['operation_id'])
    assert (identity(path), path.read_bytes()) == before
    assert not (harness.parent / '.harness-store').exists()


@pytest.mark.parametrize('boundary', ['prepare', 'intent', 'pointer', 'sync', 'commit-intent', 'committed', 'retired'])
def test_m1_recovery_returns_original_archive_or_keeps_committed_alias(harness, boundary):
    from harness.storage import StorageRequest, plan_operation, recover_operation

    archive = harness / 'history/TASK-007-prior'
    archive.mkdir(parents=True)
    (archive / 'current-task.yaml').write_text('task:\n  id: TASK-007\n')
    original = identity(archive)
    activate(harness)
    index_path = harness.parent / '.harness-store/history/index.yaml'
    index_before = identity(index_path), index_path.read_bytes()
    plan = plan_operation(harness.parent, StorageRequest(kind='M1'))
    decision_id, maintenance = qualified_grant(harness, plan)
    kill_apply(harness, plan, decision_id, maintenance, boundary)
    result = recover_operation(harness.parent, plan['operation_id'])
    committed = boundary in {'committed', 'retired'}
    assert result['status'] == ('COMMITTED' if committed else 'ABORTED')
    index = yaml.safe_load(index_path.read_bytes())
    if committed:
        record = next(row for row in index['aliases'] if row['logical_archive_alias'] == archive.name)
        assert identity(harness.parent / '.harness-store/history/archives' / record['archive_id']) == original
        assert not archive.exists()
    else:
        assert identity(archive) == original
        assert (identity(index_path), index_path.read_bytes()) == index_before
    assert not list((harness.parent / '.harness-store/operations').iterdir())

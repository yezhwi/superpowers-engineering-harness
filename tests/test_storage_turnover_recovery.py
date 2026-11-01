"""Actual child death during bound new-root publication, original objects retained."""
import json
import os
import subprocess
import sys

import pytest
import yaml
from test_context_builder import harness  # noqa: F401
from test_storage_migration import activate
from storage_factory import ROOT, cli, identity

_SCRIPT = r'''
import os,sys,yaml
from pathlib import Path
from harness.storage import journal
from harness import publication_fs as fs, workspace
from harness.storage.turnover import replace_bound_task
from harness.task_replacement import trusted_architecture_mode
boundary=sys.argv[1]
root=Path.cwd()/'.harness'
task=yaml.safe_load((root/'current-task.yaml').read_bytes())
write,move=journal._write_new,fs.move_noreplace
plan=None
def die(): os._exit(87)
def after_write(fd,name,document):
    global plan
    if document.get('version')==3 and document.get('plan',{}).get('operation')=='TURNOVER':
        plan=document['plan']
    write(fd,name,document)
    if boundary=='prepared' and plan and document.get('version')==3: die()
    event=document.get('event')
    if event=='ACK':
        entry=plan['actions'][document['action']]
        if boundary=='reservation' and entry['kind']=='reserve_ids': die()
        if boundary=='archive' and entry['kind']=='archive_descriptor': die()
    if boundary=='commit-intent' and event=='COMMIT_INTENT': die()
    if boundary=='committed' and event=='COMMITTED': die()
def after_move(srcfd,src,dstfd,dst):
    move(srcfd,src,dstfd,dst)
    if boundary=='old-root' and src=='.harness' and dst=='previous': die()
    if boundary=='new-root' and src=='candidate' and dst=='.harness': die()
    if boundary=='index' and src=='index-candidate.yaml' and dst=='index.yaml': die()
    if boundary=='retired' and dst=='descriptor.json': die()
journal._write_new=after_write
fs.move_noreplace=after_move
replace_bound_task(root,task,'TASK-029','','RECOVER',workspace.git_head(root.parent),trusted_architecture_mode(root,task),'kill fixture')
raise SystemExit('boundary was not reached')
'''


@pytest.mark.parametrize('entrypoint', ['owner', 'replacement'])
def test_owner_rejects_aborted_reserved_id_and_zero_alias_before_any_writes(harness, entrypoint):
    from harness import workspace
    from harness.storage import admit_storage, recover_operation
    from harness.storage.turnover import replace_bound_task
    from harness.task_identity import TaskIdentityError, require_available
    from harness.task_replacement import publish_bound_replacement, trusted_architecture_mode

    activate(harness)
    task_path = harness / 'current-task.yaml'
    old = yaml.safe_load(task_path.read_bytes())
    old['state'] = 'DONE'  # Fixture only, enables ordinary task new preconditions.
    task_path.write_text(yaml.safe_dump(old))
    program = _SCRIPT.replace("'TASK-029'", "'TASK-999'").replace("'RECOVER'", "'NEW'")
    result = subprocess.run([sys.executable, '-B', '-c', program, 'reservation'], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': f'{ROOT}/src:{ROOT}/tests'},
                            capture_output=True, text=True, timeout=100)
    assert result.returncode == 87, result.stderr
    store = harness.parent / '.harness-store'
    pending = next((store / 'operations').iterdir())
    operation_id = json.loads(pending.read_bytes())['plan']['operation_id']
    assert recover_operation(harness.parent, operation_id)['status'] == 'ABORTED'
    assert yaml.safe_load(task_path.read_bytes()) == old
    reservation = store / 'history/reservations' / (operation_id + '.json')
    assert 'TASK-999' in json.loads(reservation.read_bytes())['task_ids']
    mode = trusted_architecture_mode(harness, old)
    head = workspace.git_head(harness.parent)
    call = replace_bound_task if entrypoint == 'owner' else publish_bound_replacement
    before = identity(harness), identity(task_path), task_path.read_bytes(), reservation.read_bytes()
    namespaces = ['history/archives', 'history/reservations', 'retained/roots', 'operations', 'receipts']
    membership = {name: sorted(p.name for p in (store / name).iterdir()) for name in namespaces}
    for candidate in ['TASK-999', 'TASK-0999']:
        with admit_storage(harness), pytest.raises(TaskIdentityError, match='TASK_ID_ALREADY_USED'):
            require_available(harness, candidate, old)
        refused = cli(harness.parent, 'task', 'new', candidate)
        assert refused.returncode == 2 and 'TASK_ID_ALREADY_USED' in refused.stdout + refused.stderr
        with pytest.raises(TaskIdentityError, match='TASK_ID_ALREADY_USED'):
            call(harness, old, candidate, 'reserved retry', 'NEW', head, mode)
        assert (identity(harness), identity(task_path), task_path.read_bytes(), reservation.read_bytes()) == before
        assert {name: sorted(p.name for p in (store / name).iterdir()) for name in namespaces} == membership
    fresh = call(harness, old, 'TASK-1000', 'fresh identity', 'NEW', head, mode)
    if entrypoint == 'replacement':
        assert fresh is True
    else:
        assert fresh['status'] == 'COMMITTED'
    assert yaml.safe_load(task_path.read_bytes())['task']['id'] == 'TASK-1000'
    assert reservation.read_bytes() == before[3]


@pytest.mark.parametrize('boundary', ['prepared', 'reservation', 'archive', 'old-root', 'new-root', 'index',
                                      'commit-intent', 'committed', 'retired'])
def test_explicit_turnover_recovery_preserves_root_and_reservations(harness, boundary):
    from harness.storage import StorageError, recover_operation
    from harness.storage.archive import load_history
    from harness.storage.layout import admit_storage
    from harness.task_identity import require_available

    activate(harness)
    before = identity(harness), (harness / 'current-task.yaml').read_bytes()
    result = subprocess.run([sys.executable, '-B', '-c', _SCRIPT, boundary], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': f'{ROOT}/src:{ROOT}/tests'},
                            capture_output=True, text=True, timeout=100)
    assert result.returncode == 87, result.stderr
    store = harness.parent / '.harness-store'
    pending = list((store / 'operations').iterdir())
    if pending:
        descriptor = json.loads(pending[0].read_bytes())
        operation_id = descriptor['plan']['operation_id']
    else:
        descriptors = [json.loads(path.read_bytes()) for path in (store / 'receipts').glob('*/descriptor.json')]
        operation_id = next(item['plan']['operation_id'] for item in descriptors if item['plan']['operation'] == 'TURNOVER')
    if boundary != 'retired':
        for args in [('init',), ('status',), ('context', '--compact')]:
            refused = cli(harness.parent, *args)
            assert refused.returncode == 2, (boundary, args, refused.stdout, refused.stderr)
            assert 'RECOVERY_REQUIRED' in refused.stderr
    recovered = recover_operation(harness.parent, operation_id)
    committed = boundary in {'committed', 'retired'}
    assert recovered['status'] == ('COMMITTED' if committed else 'ABORTED')
    if not committed:
        assert (identity(harness), (harness / 'current-task.yaml').read_bytes()) == before
    else:
        assert yaml.safe_load((harness / 'current-task.yaml').read_bytes())['task']['id'] == 'TASK-029'
    assert not list((store / 'operations').iterdir())
    with admit_storage(harness):
        history = load_history(harness)
        assert len(history['archives']) == int(committed)
        # Observation reserves candidate ID even if archive/root publication aborts.
        with pytest.raises((StorageError, ValueError)):
            require_available(harness, 'TASK-00029', yaml.safe_load((harness / 'current-task.yaml').read_bytes()))

"""Archive metadata derives from acknowledged objects, never guessed inodes."""
import base64
import hashlib
import json

import pytest

from storage_archive_factory import encoded, install_archive
from storage_factory import fixture_store, identity, repository
from storage_journal_factory import OP, action, authority, plan


def overlay_plan(repo):
    store = repo / '.harness-store'
    (store / 'history/reservations').mkdir(mode=0o700)
    slot = store / 'retained/roots' / OP
    slot.mkdir(mode=0o700)
    index_path = store / 'history/index.yaml'
    base = json.loads(index_path.read_bytes())
    obj = '.harness-store/history/archives/' + 'c' * 32
    origin = {'workspace_id': '2' * 32, 'generation_id': '4' * 32, 'original_workspace_root': str(repo)}
    blueprint = {'archive_id': 'c' * 32, 'task_id': 'TASK-8', 'origin': origin,
                 'source_snapshot': {'operation_id': OP, 'source_identity': identity(repo / '.harness'),
                                     'manifest_digest': '8' * 64}, 'members': ['current-task.yaml']}
    reservation = {'version': 1, 'kind': 'storage_reservation', 'operation_id': OP,
                   'workspace_id': '2' * 32, 'store_id': '1' * 32, 'task_ids': ['TASK-8']}
    overlay = {'base': base, 'base_sha256': hashlib.sha256(index_path.read_bytes()).hexdigest(),
               'archives': [{'path': obj, 'aliases': ['TASK-8-snapshot']}], 'reserve_ids': ['TASK-8']}
    def data(value):
        return base64.b64encode(encoded(value)).decode()
    entries = [
        action('reserve_ids', f'.harness-store/history/reservations/{OP}.json', content=data(reservation)),
        action('mkdir', obj),
        action('write', obj + '/current-task.yaml', content=data({'task': {'id': 'TASK-8'}})),
        action('archive_descriptor', obj + '/archive.yaml', content=data(blueprint)),
        action('history_overlay', f'.harness-store/retained/roots/{OP}/overlay.yaml', content=data(overlay)),
        action('move', f'.harness-store/retained/roots/{OP}/index-before.yaml',
               source='.harness-store/history/index.yaml', node_identity=identity(index_path),
               sha256=hashlib.sha256(index_path.read_bytes()).hexdigest()),
        action('move', '.harness-store/history/index.yaml', source=f'.harness-store/retained/roots/{OP}/overlay.yaml'),
    ]
    return plan(repo, entries, bound=True), origin


@pytest.mark.parametrize('damage', ['foreign-workspace', 'missing-reservation', 'unknown-member', 'duplicate-alias', 'task-document-mismatch', 'forged-base'])
def test_invalid_overlay_never_publishes_new_alias(tmp_path, damage):
    from harness.storage import StorageError, admit_storage
    from harness.storage.journal import prepare_turnover

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    install_archive(repo)
    value, _ = overlay_plan(repo)
    if damage == 'missing-reservation':
        value['actions'].pop(0)
    elif damage in {'foreign-workspace', 'unknown-member'}:
        entry = value['actions'][3]
        body = json.loads(base64.b64decode(entry['content']))
        if damage == 'foreign-workspace':
            body['origin']['workspace_id'] = '9' * 32
        else:
            body['members'].append('unknown.json')
        entry['content'] = base64.b64encode(encoded(body)).decode()
    elif damage == 'task-document-mismatch':
        value['actions'][2]['content'] = base64.b64encode(encoded({'task': {'id': 'TASK-99'}})).decode()
    else:
        entry = value['actions'][4]
        body = json.loads(base64.b64decode(entry['content']))
        if damage == 'forged-base':
            body['base']['archives'] = {}
            body['base']['aliases'] = []
            body['base']['reserved_task_ids'] = []
        else:
            body['archives'][0]['aliases'] *= 2
        entry['content'] = base64.b64encode(encoded(body)).decode()
    value.pop('plan_digest')
    value['plan_digest'] = hashlib.sha256(encoded(value)).hexdigest()
    with admit_storage(repo / '.harness') as session:
        with pytest.raises(StorageError):
            operation = prepare_turnover(session, {'plan': value, 'authority': authority(value)})
            for entry in value['actions']:
                operation.advance(entry)
            operation.commit()
    assert 'c' * 32 not in json.loads((store / 'history/index.yaml').read_bytes())['archives']


@pytest.mark.parametrize('boundary', ['prepare', 'intent', 'ack', 'overlay-ack', 'index-pointer', 'sync', 'commit-intent', 'committed', 'retired'])
def test_overlay_kill_preserves_ids_and_exposes_only_committed_aliases(tmp_path, boundary):
    from harness.storage import StorageError, admit_storage, recover_operation
    from harness.task_identity import TaskIdentityError, require_available
    from test_storage_kill_recovery import killed

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    install_archive(repo)
    value, _ = overlay_plan(repo)
    killed(repo, value, boundary)
    if boundary != 'retired':
        with pytest.raises(StorageError, match='STORE_RECOVERY_REQUIRED'):
            with admit_storage(repo / '.harness'):
                pytest.fail('pending overlay was admitted')
    result = recover_operation(repo, OP)
    committed = boundary in {'committed', 'retired'}
    assert result['status'] == ('COMMITTED' if committed else 'ABORTED')
    index = json.loads((store / 'history/index.yaml').read_bytes())
    assert ('c' * 32 in index['archives']) == committed
    with admit_storage(repo / '.harness'):
        with pytest.raises(TaskIdentityError, match='TASK_ID_ALREADY_USED'):
            require_available(repo / '.harness', 'TASK-008', {'task': {'id': 'TASK-2'}})


def test_unacknowledged_reservation_creation_is_not_adopted_by_matching_bytes(tmp_path):
    from harness.storage import StorageError, recover_operation
    from test_storage_kill_recovery import killed

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    install_archive(repo)
    value, _ = overlay_plan(repo)
    killed(repo, value, 'reservation-before-ack')
    path = store / 'history/reservations' / (OP + '.json')
    before = identity(path), path.read_bytes()
    with pytest.raises(StorageError, match='STORE_IDENTITY_CHANGED'):
        recover_operation(repo, OP)
    assert (identity(path), path.read_bytes()) == before
    assert (store / 'operations' / (OP + '.json')).is_file()


def test_exact_source_snapshot_reuse_requires_original_committed_receipt(tmp_path):
    from harness.storage import admit_storage
    from harness.storage import archive
    from harness.storage.journal import prepare_turnover

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    install_archive(repo)
    value, origin = overlay_plan(repo)
    snapshot = {'task_id': 'TASK-8', 'origin': origin,
                'source_identity': identity(repo / '.harness'), 'manifest_digest': '8' * 64}
    with admit_storage(repo / '.harness') as session:
        operation = prepare_turnover(session, {'plan': value, 'authority': authority(value)})
        for entry in value['actions']:
            operation.advance(entry)
        result = operation.commit()
    lookup = archive.find_receipted_snapshot
    with admit_storage(repo / '.harness') as session:
        assert lookup(session, snapshot) == 'c' * 32
        changed = {**snapshot, 'manifest_digest': '9' * 64}
        assert lookup(session, changed) is None
        changed = {**snapshot, 'source_identity': [snapshot['source_identity'][0], snapshot['source_identity'][1] + 1]}
        assert lookup(session, changed) is None
    receipt = repo / result['receipt']
    receipt.rename(receipt.with_name('unavailable-receipt.json'))
    with admit_storage(repo / '.harness') as session:
        assert lookup(session, snapshot) is None
    assert (store / 'history/archives' / ('c' * 32)).is_dir()


def test_malformed_descriptor_blueprint_returns_safe_typed_refusal(tmp_path):
    from harness.storage import StorageError, admit_storage
    from harness.storage.journal import prepare_turnover

    repo = repository(tmp_path)
    fixture_store(repo)
    install_archive(repo)
    value, _ = overlay_plan(repo)
    entry = value['actions'][3]
    body = json.loads(base64.b64decode(entry['content']))
    body['task_id'] = 'PRIVATE_INVALID_PAYLOAD'
    entry['content'] = base64.b64encode(encoded(body)).decode()
    value.pop('plan_digest')
    value['plan_digest'] = hashlib.sha256(encoded(value)).hexdigest()
    caught = None
    with admit_storage(repo / '.harness') as session:
        try:
            operation = prepare_turnover(session, {'plan': value, 'authority': authority(value)})
            for action_item in value['actions']:
                operation.advance(action_item)
        except Exception as error:
            caught = error
    assert isinstance(caught, StorageError), type(caught).__name__
    assert str(caught) == 'STORE_IDENTITY_CHANGED'


@pytest.mark.parametrize('outcome', ['commit', 'abort'])
def test_overlay_visibility_and_permanent_candidate_id_reservation(tmp_path, outcome):
    from harness.storage import ReferenceOrigin, StorageError, admit_storage, resolve_archive
    from harness.storage.journal import prepare_turnover
    from harness.task_identity import TaskIdentityError, require_available

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    install_archive(repo)
    value, origin = overlay_plan(repo)
    failure = None
    try:
        with admit_storage(repo / '.harness') as session:
            operation = prepare_turnover(session, {'plan': value, 'authority': authority(value)})
            for number, entry in enumerate(value['actions']):
                operation.advance(entry)
                if number == 4:
                    assert 'c' * 32 not in json.loads((store / 'history/index.yaml').read_bytes())['archives']
            with pytest.raises(StorageError, match='STORE_RECOVERY_REQUIRED'):
                resolve_archive(session, 'history/TASK-8-snapshot/current-task.yaml', ReferenceOrigin(**origin))
            result = getattr(operation, outcome)()
            assert result['status'] == ('COMMITTED' if outcome == 'commit' else 'ABORTED')
    except StorageError as error:
        failure = error.code
    assert failure is None, f'owned archive overlay refused: {failure}'
    with admit_storage(repo / '.harness') as session:
        with pytest.raises(TaskIdentityError, match='TASK_ID_ALREADY_USED'):
            require_available(repo / '.harness', 'TASK-0008', {'task': {'id': 'TASK-2'}})
        if outcome == 'commit':
            handle = resolve_archive(session, 'history/TASK-8-snapshot/current-task.yaml', ReferenceOrigin(**origin))
            assert json.loads(handle.read_bytes()) == {'task': {'id': 'TASK-8'}}
        else:
            assert 'c' * 32 not in json.loads((store / 'history/index.yaml').read_bytes())['archives']
            assert not (store / 'history/archives' / ('c' * 32)).exists()
            assert list((store / 'receipts' / ('storage-' + OP) / 'quarantine').iterdir())

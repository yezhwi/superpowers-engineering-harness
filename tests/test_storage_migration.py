"""Explicit fixture grants only; never apply to the harness repository."""
import pytest
import yaml
from test_context_builder import harness  # noqa: F401
from test_storage_activation import qualified_grant

from storage_factory import identity


def activate(root):
    from harness.storage import StorageRequest, apply_operation, plan_operation

    value = plan_operation(root.parent, StorageRequest(kind='ACTIVATE'))
    assert value['ready'], value['qualification']['blocked_reasons']
    decision_id, maintenance = qualified_grant(root, value)
    return value, apply_operation(root.parent, value, decision_id, maintenance)


def test_activation_installs_owned_binding_without_fabricating_current_archive(harness):
    from harness.storage import inspect_layout

    original = identity(harness)
    before = (harness / 'current-task.yaml').read_bytes()
    value, result = activate(harness)
    assert result['status'] == 'COMMITTED'
    assert inspect_layout(harness.parent).mode == 'bound'
    assert identity(harness) == original
    assert (harness / 'current-task.yaml').read_bytes() == before
    index = yaml.safe_load((harness.parent / '.harness-store/history/index.yaml').read_bytes())
    assert index['archives'] == {}
    assert value['task_id'] in index['reserved_task_ids']
    assert not list((harness / '.transactions').iterdir())
    assert not list(harness.parent.glob('.harness-store-prepare-*'))
    gate = yaml.safe_load((harness / 'gate.yaml').read_bytes())
    assert gate['gate']['storage_layout']['required_capabilities'] == ['harness-storage-layout/v1']


def test_m1_moves_original_archive_preserving_inode_receipt_and_origin(harness):
    from harness.storage import ReferenceOrigin, StorageRequest, admit_storage, apply_operation, plan_operation, resolve_archive

    archive = harness / 'history/TASK-007-original'
    archive.mkdir(parents=True)
    task = archive / 'current-task.yaml'
    task.write_text('task:\n  id: TASK-007\n')
    receipt = archive / 'proof.json'
    receipt.write_bytes(b'{"command":"original old absolute path"}')
    before = identity(archive), identity(task), identity(receipt), receipt.read_bytes()
    activate(harness)
    plan = plan_operation(harness.parent, StorageRequest(kind='M1'))
    assert plan['ready'], plan['qualification']['blocked_reasons']
    decision_id, maintenance = qualified_grant(harness, plan)
    result = apply_operation(harness.parent, plan, decision_id, maintenance)
    assert result['status'] == 'COMMITTED'
    assert not archive.exists()
    index = yaml.safe_load((harness.parent / '.harness-store/history/index.yaml').read_bytes())
    selected = next(row for row in index['aliases'] if row['logical_archive_alias'] == archive.name)
    obj = harness.parent / '.harness-store/history/archives' / selected['archive_id']
    assert identity(obj) == before[0]
    assert identity(obj / 'current-task.yaml') == before[1]
    assert identity(obj / 'proof.json') == before[2]
    assert (obj / 'proof.json').read_bytes() == before[3]
    with admit_storage(harness) as session:
        handle = resolve_archive(session, f'history/{archive.name}/proof.json', ReferenceOrigin(**selected['origin']))
        assert handle.read_bytes() == before[3]


def test_same_operation_apply_is_idempotent_after_commit(harness):
    from harness.storage import StorageRequest, apply_operation, plan_operation

    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, plan)
    result = apply_operation(harness.parent, plan, decision_id, maintenance)
    import json

    receipt = json.loads((harness.parent / result['receipt']).read_bytes())
    assert receipt['authority'].get('maintenance_snapshot') == maintenance
    store_before = identity(harness.parent / '.harness-store')
    repeated = apply_operation(harness.parent, plan, decision_id, maintenance)
    assert repeated == result
    assert identity(harness.parent / '.harness-store') == store_before


def test_storage_grant_cannot_expand_into_unrelated_task_mutation(harness):
    from harness.storage import StorageError, StorageRequest, apply_operation, plan_operation
    from harness.storage.migration import _action, _digest

    value = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    value['actions'].append(_action('write', '.harness/NOT_STORAGE', content={'arbitrary': 'task fact'}))
    value.pop('plan_digest')
    value['plan_digest'] = _digest(value)
    decision_id, maintenance = qualified_grant(harness, value)
    with pytest.raises(StorageError, match='STORE_PLAN_STALE'):
        apply_operation(harness.parent, value, decision_id, maintenance)
    assert not (harness / 'NOT_STORAGE').exists()
    assert not (harness.parent / '.harness-store').exists()
    assert not list((harness / '.transactions').glob('*.json'))


def test_m1_large_manifest_keeps_prepare_fd_usage_bounded(harness):
    import json
    import os
    import subprocess
    import sys

    from harness.storage import StorageRequest, plan_operation
    from storage_factory import ROOT

    archive = harness / 'history/TASK-009-many'
    archive.mkdir(parents=True)
    (archive / 'current-task.yaml').write_text('task:\n  id: TASK-009\n')
    for number in range(120):
        (archive / f'member-{number}.txt').write_text('preserve')
    activate(harness)
    plan = plan_operation(harness.parent, StorageRequest(kind='M1'))
    decision_id, maintenance = qualified_grant(harness, plan)
    program = '''
import json,resource,sys
from pathlib import Path
from harness.storage import apply_operation
soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE,(min(96,soft),hard))
result=apply_operation(Path.cwd(),json.loads(sys.argv[1]),sys.argv[2],json.loads(sys.argv[3]))
assert result['status']=='COMMITTED'
'''
    result = subprocess.run([sys.executable, '-B', '-c', program, json.dumps(plan), decision_id,
                             json.dumps(maintenance)], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert not archive.exists()


def test_bound_layout_never_falls_through_to_legacy_copying_turnover(harness):
    from harness.storage import StorageError, admit_storage
    from harness.task_replacement import replacement_workspace

    activate(harness)
    before = {path.name for path in harness.parent.iterdir()}
    with admit_storage(harness), pytest.raises(StorageError, match='STORE_READER_UNSUPPORTED'):
        replacement_workspace(harness, new_task=True)
    assert {path.name for path in harness.parent.iterdir()} == before


def test_missing_minimum_reader_marker_blocks_bound_admission(harness):
    from harness.storage import StorageError, admit_storage

    activate(harness)
    path = harness / 'gate.yaml'
    gate = yaml.safe_load(path.read_bytes())
    gate['gate'].pop('storage_layout')
    path.write_text(yaml.safe_dump(gate))
    with pytest.raises(StorageError, match='STORE_READER_UNSUPPORTED'):
        with admit_storage(harness):
            pytest.fail('markerless bound root admitted')


def test_original_baseline_gate_schema_rejects_new_layout_marker(harness):
    import json
    import subprocess

    from jsonschema import ValidationError, validate
    from storage_factory import ROOT

    baseline = json.loads(subprocess.check_output(
        ['git', 'show', 'dc4cd9d:src/harness/schemas/gate.schema.json'], cwd=ROOT))
    activate(harness)
    gate = yaml.safe_load((harness / 'gate.yaml').read_bytes())
    with pytest.raises(ValidationError):
        validate(gate, baseline)


def test_cross_device_history_never_becomes_ready_migration_input(harness, monkeypatch):
    import os
    from types import SimpleNamespace

    from harness.storage import StorageRequest, plan_operation

    history = harness / 'history'
    history.mkdir(exist_ok=True)
    history_inode = history.stat().st_ino
    fstat = os.fstat

    def different_device(fd):
        info = fstat(fd)
        if info.st_ino == history_inode:
            fields = {name: getattr(info, name) for name in dir(info) if name.startswith('st_')}
            fields['st_dev'] += 1
            return SimpleNamespace(**fields)
        return info

    monkeypatch.setattr(os, 'fstat', different_device)
    value = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    assert not value['ready']
    assert value['qualification']['unsafe_nodes']
    assert not (harness.parent / '.harness-store').exists()


def test_native_io_failure_stays_typed_and_preserves_explicit_recovery(harness, monkeypatch):
    import errno

    from harness import publication_fs
    from harness.storage import StorageError, StorageRequest, apply_operation, inspect_layout, plan_operation, recover_operation

    value = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, value)
    move = publication_fs.move_noreplace

    def fail_install(srcfd, src, dstfd, dst):
        if dst == '.harness-store':
            raise OSError(errno.EIO, 'PRIVATE_NATIVE_DETAIL')
        return move(srcfd, src, dstfd, dst)

    error = None
    with monkeypatch.context() as patch:
        patch.setattr(publication_fs, 'move_noreplace', fail_install)
        try:
            apply_operation(harness.parent, value, decision_id, maintenance)
        except Exception as caught:
            error = caught
    assert isinstance(error, StorageError), type(error).__name__
    assert str(error) == 'STORE_IDENTITY_CHANGED'
    assert recover_operation(harness.parent, value['operation_id'])['status'] == 'ABORTED'
    assert inspect_layout(harness.parent).mode == 'legacy'


def test_plan_cannot_be_applied_under_different_reader_schema_bytes(harness, monkeypatch):
    from harness import schema_resources
    from harness.storage import StorageError, StorageRequest, apply_operation, plan_operation

    value = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, value)
    read = schema_resources._resource_bytes

    def changed(name):
        raw = read(name)
        return raw + b'\n' if name == 'gate.schema.json' else raw

    monkeypatch.setattr(schema_resources, '_resource_bytes', changed)
    with pytest.raises(StorageError, match='STORE_PLAN_STALE'):
        apply_operation(harness.parent, value, decision_id, maintenance)
    assert not (harness.parent / '.harness-store').exists()
    assert not list((harness / '.transactions').glob('*.json'))


@pytest.mark.parametrize('document', ['task: []\n', '- not-a-task\n', 'task: null\n'])
def test_malformed_legacy_archive_document_is_typed_and_preserved(harness, document):
    from harness.storage import StorageError, StorageRequest, plan_operation

    archive = harness / 'history/TASK-009-invalid'
    archive.mkdir(parents=True)
    path = archive / 'current-task.yaml'
    path.write_text(document)
    activate(harness)
    before = identity(path), path.read_bytes()
    error = None
    try:
        plan_operation(harness.parent, StorageRequest(kind='M1'))
    except Exception as caught:
        error = caught
    assert isinstance(error, StorageError), type(error).__name__
    assert str(error) == 'STORE_UNSAFE_NODE'
    assert (identity(path), path.read_bytes()) == before
    assert not list((harness.parent / '.harness-store/operations').iterdir())


def test_business_workspace_drift_during_activation_stops_before_commit(harness, monkeypatch):
    from harness.storage import StorageError, StorageRequest, apply_operation, inspect_layout, plan_operation, recover_operation
    from harness.storage.journal import DirectoryOperation

    value = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, value)
    advance = DirectoryOperation.advance
    outside = harness.parent / 'external-product-change.py'

    def external_writer(operation, action):
        result = advance(operation, action)
        if action['target'] == '.harness/storage-binding.yaml':
            outside.write_text('preserve external edit')
        return result

    with monkeypatch.context() as patch:
        patch.setattr(DirectoryOperation, 'advance', external_writer)
        with pytest.raises(StorageError, match='STORE_PLAN_STALE'):
            apply_operation(harness.parent, value, decision_id, maintenance)
    assert outside.read_text() == 'preserve external edit'
    assert recover_operation(harness.parent, value['operation_id'])['status'] == 'ABORTED'
    assert inspect_layout(harness.parent).mode == 'legacy'
    assert outside.read_text() == 'preserve external edit'


def test_bound_header_drift_during_m1_is_not_committed_or_overwritten(harness, monkeypatch):
    import json

    from harness.storage import StorageError, StorageRequest, apply_operation, plan_operation
    from harness.storage.journal import DirectoryOperation

    archive = harness / 'history/TASK-009-header-drift'
    archive.mkdir(parents=True)
    (archive / 'current-task.yaml').write_text('task:\n  id: TASK-009\n')
    original = identity(archive)
    activate(harness)
    value = plan_operation(harness.parent, StorageRequest(kind='M1'))
    decision_id, maintenance = qualified_grant(harness, value)
    advance = DirectoryOperation.advance
    header = harness.parent / '.harness-store/store.yaml'

    def external_header(operation, action):
        result = advance(operation, action)
        if action['target'] == '.harness-store/history/index.yaml':
            body = json.loads(header.read_bytes())
            body['store_id'] = '9' * 32
            header.write_text(json.dumps(body))
        return result

    with monkeypatch.context() as patch:
        patch.setattr(DirectoryOperation, 'advance', external_header)
        with pytest.raises(StorageError, match='STORE_IDENTITY_CHANGED'):
            apply_operation(harness.parent, value, decision_id, maintenance)
    assert json.loads(header.read_bytes())['store_id'] == '9' * 32
    target = next(row['target'] for row in value['actions']
                  if row['kind'] == 'move' and row['source'] == str(archive.relative_to(harness.parent)))
    assert identity(harness.parent / target) == original
    assert (harness.parent / '.harness-store/operations' / (value['operation_id'] + '.json')).exists()


def test_selected_grant_body_index_disagreement_is_not_authority(harness):
    from harness.storage import StorageError, StorageRequest, plan_operation
    from harness.storage.migration import verify_authority

    value = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, value)
    index = harness / 'decisions/index.yaml'
    document = yaml.safe_load(index.read_bytes())
    next(row for row in document['decisions'] if row['id'] == decision_id)['sha256'] = 'sha256:' + '0' * 64
    index.write_text(yaml.safe_dump(document))
    with pytest.raises(StorageError, match='STORE_AUTHORITY_REQUIRED'):
        verify_authority(harness, value, decision_id, maintenance)
    assert not (harness.parent / '.harness-store').exists()


def test_selected_grant_drift_during_activation_preserves_pending_not_commit(harness, monkeypatch):
    from harness.storage import StorageError, StorageRequest, apply_operation, plan_operation
    from harness.storage.journal import DirectoryOperation

    value = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, value)
    record = harness / 'decisions' / (decision_id + '.yaml')
    advance = DirectoryOperation.advance

    def external_decision(operation, action):
        result = advance(operation, action)
        if action['target'] == '.harness/storage-binding.yaml':
            body = yaml.safe_load(record.read_bytes())
            body['status'] = 'REJECTED'
            record.write_text(yaml.safe_dump(body))
        return result

    with monkeypatch.context() as patch:
        patch.setattr(DirectoryOperation, 'advance', external_decision)
        with pytest.raises(StorageError, match='STORE_IDENTITY_CHANGED'):
            apply_operation(harness.parent, value, decision_id, maintenance)
    assert yaml.safe_load(record.read_bytes())['status'] == 'REJECTED'
    assert list((harness / '.transactions').glob('storage-activation-*.json'))


def test_source_namespace_drift_after_grant_never_creates_store(harness):
    from harness.storage import StorageError, StorageRequest, apply_operation, plan_operation

    value = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, value)
    extra = harness / 'history/TASK-999-new'
    extra.mkdir(parents=True)
    with pytest.raises(StorageError, match='STORE_PLAN_STALE'):
        apply_operation(harness.parent, value, decision_id, maintenance)
    assert not (harness.parent / '.harness-store').exists()
    assert not list((harness / '.transactions').glob('*.json'))

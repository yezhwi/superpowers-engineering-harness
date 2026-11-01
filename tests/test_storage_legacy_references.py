"""Explicit M2 inputs: never infer origin or roles from legacy names."""
import os
import pytest
import yaml
from test_context_builder import harness  # noqa: F401
from test_storage_activation import qualified_grant
from test_storage_migration import activate
from storage_factory import identity


def request(root, source, role='retained_root', alias=None):
    from harness.storage import StorageRequest
    header = yaml.safe_load((root.parent / '.harness-store/store.yaml').read_bytes())
    origin = {'workspace_id': header['workspace_id'], 'generation_id': '9' * 32,
              'original_workspace_root': str(root.parent)}
    selected = {'source': source, 'role': role, 'origin': origin, 'logical_path': source}
    if alias is not None:
        selected['alias'] = alias
    return StorageRequest(kind='M2', sources=(selected,))


def test_m2_moves_only_explicit_opaque_package_without_inspecting_nested_pending(harness):
    from harness.storage import apply_operation, plan_operation

    old = harness / '.publication-retained/explicit-package'
    nested = old / 'fixture/.harness/.transactions'
    nested.mkdir(parents=True)
    (nested / 'unknown.json').write_bytes(b'opaque fixture, not current authority')
    os.mkfifo(old / 'fifo')
    (old / 'link').symlink_to('/not-followed')
    receipt = old / 'receipt.json'
    receipt.write_bytes(b'{"command":"/old/unchanged/path"}')
    before = identity(old), identity(receipt), receipt.read_bytes()
    activate(harness)
    spec = request(harness, old.relative_to(harness.parent).as_posix())
    plan = plan_operation(harness.parent, spec)
    assert plan['ready'], plan['qualification']['blocked_reasons']
    assert len(plan['qualification']['entries']) == 1
    assert plan['qualification'].get('logical_bytes_complete') is False
    assert not list((harness.parent / '.harness-store/operations').iterdir())
    decision, maintenance = qualified_grant(harness, plan)
    result = apply_operation(harness.parent, plan, decision, maintenance)
    assert result['status'] == 'COMMITTED'
    action = next(item for item in plan['actions'] if item['source'] == spec.sources[0]['source'])
    target = harness.parent / action['target']
    assert (identity(target), identity(target / 'receipt.json'), (target / 'receipt.json').read_bytes()) == before
    assert (target / 'link').is_symlink()
    assert (target / 'fifo').stat().st_ino != 0
    assert not old.exists()
    assert plan['relocations'][0]['origin'] == spec.sources[0]['origin']
    assert plan['relocations'][0]['logical_path'] == spec.sources[0]['logical_path']
    assert apply_operation(harness.parent, plan, decision, maintenance) == result
    from harness.storage import ReferenceOrigin, StorageError, admit_storage
    from harness.storage import archive as archive_reader
    resolver = getattr(archive_reader, 'resolve_relocated_object', None)
    assert callable(resolver), 'M2 needs explicit receipt-qualified object location resolver'
    origin = ReferenceOrigin(**spec.sources[0]['origin'])
    with admit_storage(harness) as session:
        location = resolver(session, plan['operation_id'], str(harness.parent / spec.sources[0]['logical_path']), origin)
        assert location['path'] == action['target']
        assert location['identity'] == before[0]
        assert location['origin'] == spec.sources[0]['origin']
        wrong = ReferenceOrigin(origin.workspace_id, '8' * 32, origin.original_workspace_root)
        with pytest.raises(StorageError, match='STORE_REFERENCE_AMBIGUOUS'):
            resolver(session, plan['operation_id'], spec.sources[0]['logical_path'], wrong)
        with pytest.raises(StorageError, match='STORE_REFERENCE_AMBIGUOUS'):
            resolver(session, plan['operation_id'], spec.sources[0]['logical_path'] + '/fixture/.harness', origin)


def test_m2_history_keeps_explicit_old_generation_alias_and_original_member(harness):
    from harness.storage import (ReferenceOrigin, admit_storage, apply_operation, plan_operation,
                                 resolve_archive)

    old = harness / '.publication-retained/old-package/history/same-name'
    old.mkdir(parents=True)
    (old / 'current-task.yaml').write_text('task:\n  id: TASK-007\n')
    proof = old / 'proof.json'
    proof.write_bytes(b'{"command":"original untouched"}')
    before = identity(proof), proof.read_bytes()
    activate(harness)
    selected = request(harness, old.relative_to(harness.parent).as_posix(), 'history', 'same-name')
    plan = plan_operation(harness.parent, selected)
    assert plan['ready'], plan['qualification']['blocked_reasons']
    decision, maintenance = qualified_grant(harness, plan)
    assert apply_operation(harness.parent, plan, decision, maintenance)['status'] == 'COMMITTED'
    origin = ReferenceOrigin(**selected.sources[0]['origin'])
    with admit_storage(harness) as session:
        handle = resolve_archive(session, '.harness/history/same-name/proof.json', origin=origin)
        assert handle.read_bytes() == before[1]
        assert handle.token['member_identity'] == before[0]


@pytest.mark.parametrize('boundary', ['prepare', 'intent', 'pointer', 'committed', 'retired'])
def test_m2_real_process_recovery_returns_or_keeps_exact_original_package(harness, boundary):
    from harness.storage import plan_operation, recover_operation
    from test_storage_migration_recovery import kill_apply

    old = harness / '.publication-retained/explicit-object'
    old.mkdir(parents=True)
    (old / 'receipt.json').write_bytes(b'preserve original failure')
    activate(harness)
    before = identity(old), identity(old / 'receipt.json'), (old / 'receipt.json').read_bytes()
    plan = plan_operation(harness.parent, request(harness, old.relative_to(harness.parent).as_posix()))
    decision, maintenance = qualified_grant(harness, plan)
    kill_apply(harness, plan, decision, maintenance, boundary)
    result = recover_operation(harness.parent, plan['operation_id'])
    committed = boundary in {'committed', 'retired'}
    assert result['status'] == ('COMMITTED' if committed else 'ABORTED')
    relocation = plan['relocations'][0]
    actual = harness.parent / (relocation['target'] if committed else relocation['source'])
    assert (identity(actual), identity(actual / 'receipt.json'), (actual / 'receipt.json').read_bytes()) == before
    assert not list((harness.parent / '.harness-store/operations').iterdir())


def test_m2_occupied_rollback_source_preserves_both_objects(harness):
    from harness.storage import StorageError, plan_operation, recover_operation
    from test_storage_migration_recovery import kill_apply

    old = harness / '.publication-retained/explicit-object'
    old.mkdir(parents=True)
    (old / 'proof.json').write_bytes(b'original')
    activate(harness)
    plan = plan_operation(harness.parent, request(harness, old.relative_to(harness.parent).as_posix()))
    decision, maintenance = qualified_grant(harness, plan)
    before = identity(old)
    kill_apply(harness, plan, decision, maintenance, 'pointer')
    old.mkdir()
    (old / 'external.txt').write_bytes(b'unknown do not overwrite')
    target = harness.parent / plan['relocations'][0]['target']
    with pytest.raises(StorageError, match='STORE_IDENTITY_CHANGED'):
        recover_operation(harness.parent, plan['operation_id'])
    assert identity(target) == before
    assert (target / 'proof.json').read_bytes() == b'original'
    assert (old / 'external.txt').read_bytes() == b'unknown do not overwrite'


def test_m2_opaque_byte_completeness_cannot_be_forged_by_authorized_plan(harness):
    from harness.storage import StorageError, apply_operation, plan_operation
    from harness.storage.migration import _digest

    old = harness / '.publication-retained/explicit-object'
    old.mkdir(parents=True)
    activate(harness)
    plan = plan_operation(harness.parent, request(harness, old.relative_to(harness.parent).as_posix()))
    plan['qualification']['logical_bytes_complete'] = True
    plan['plan_digest'] = _digest({key: value for key, value in plan.items() if key != 'plan_digest'})
    decision, maintenance = qualified_grant(harness, plan)
    with pytest.raises(StorageError, match='STORE_PLAN_STALE'):
        apply_operation(harness.parent, plan, decision, maintenance)
    assert old.exists()
    assert not list((harness.parent / '.harness-store/operations').iterdir())


def test_m2_source_inode_substitution_stales_exact_selected_grant(harness):
    from harness.storage import StorageError, apply_operation, plan_operation

    old = harness / '.publication-retained/explicit-object'
    old.mkdir(parents=True)
    activate(harness)
    plan = plan_operation(harness.parent, request(harness, old.relative_to(harness.parent).as_posix()))
    decision, maintenance = qualified_grant(harness, plan)
    old.rename(old.with_name('displaced-original'))
    old.mkdir()
    with pytest.raises(StorageError, match='STORE_PLAN_STALE'):
        apply_operation(harness.parent, plan, decision, maintenance)
    assert not list((harness.parent / '.harness-store/operations').iterdir())


def test_m2_rejects_unclassified_overlap_foreign_origin_and_live_control_sources(harness):
    from copy import deepcopy
    from harness.storage import StorageError, StorageRequest, plan_operation

    root = harness / '.publication-retained/explicit-object'
    (root / 'child').mkdir(parents=True)
    activate(harness)
    item = request(harness, root.relative_to(harness.parent).as_posix()).sources[0]
    invalid = []
    for source in ['.harness', '.harness/.transactions/active', '.harness/current-task.yaml',
                   '.harness-store/history/archives/object', '../outside', '.harness//history/x']:
        invalid.append(({**item, 'source': source},))
    invalid.extend([({**item, 'role': 'runtime-delete'},),
                    ({**item, 'role': 'history'},),
                    ({**item, 'role': 'history', 'alias': '.'},),
                    ({**item, 'role': 'history', 'alias': '..'},),
                    (item, {**item, 'source': item['source'] + '/child'}),
                    (item, item)])
    foreign = deepcopy(item)
    foreign['origin']['workspace_id'] = 'f' * 32
    invalid.append((foreign,))
    for sources in invalid:
        with pytest.raises(StorageError):
            plan_operation(harness.parent, StorageRequest(kind='M2', sources=sources))
    assert not list((harness.parent / '.harness-store/operations').iterdir())
    assert root.exists()


@pytest.mark.parametrize('bad', [(), ('guessed/path',), ({'source': '.harness', 'role': 'anything'},)])
def test_m2_missing_explicit_classification_never_becomes_ready(harness, bad):
    from harness.storage import StorageError, StorageRequest, plan_operation
    activate(harness)
    try:
        plan = plan_operation(harness.parent, StorageRequest(kind='M2', sources=bad))
    except StorageError as error:
        assert error.code in {'STORE_UNSAFE_NODE', 'STORE_REFERENCE_AMBIGUOUS'}
    else:
        assert not plan['ready']

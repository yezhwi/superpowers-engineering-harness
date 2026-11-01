"""Planning never supplies apply authority or fabricates a maintenance window."""
from copy import deepcopy

import pytest
from test_context_builder import harness  # noqa: F401 -- shared pytest fixture
from storage_factory import repository


def qualified_grant(root, plan, *, change=None, selected='activate', accepted=True):
    from harness import decision

    authorization = {'version': 1, 'task_id': plan['task_id'], 'workspace_id': plan['workspace_id'],
                     'store_id': None if plan['operation'] == 'ACTIVATE' else plan['store_id'], 'operation': plan['operation'],
                     'plan_digest': 'sha256:' + plan['plan_digest'], 'scope_digest': 'sha256:' + plan['scope_digest']}
    if change:
        authorization.update(change)
    proposal = {'topic': 'Fixture storage maintenance', 'question': 'Activate exactly this fixture plan?',
                'context': ['Temporary repository only'],
                'options': [{'id': 'activate', 'description': 'Exact fixture plan', 'storage_authorization': authorization},
                            {'id': 'stay', 'description': 'Keep legacy storage'}],
                'recommendation': {'option': 'activate', 'reasons': ['Fixture test'], 'tradeoffs': []},
                'scope': ['.harness-store'], 'constraints': ['No deletion']}
    record = decision.propose(root, proposal)
    if accepted:
        record = decision.accept(root, record['id'], selected,
                                 'accepted_recommendation' if selected == 'activate' else 'user_override')
    maintenance = {'version': 1, 'workspace_id': plan['workspace_id'], 'operation': plan['operation'],
                   'plan_digest': 'sha256:' + plan['plan_digest'], 'participants_complete': True,
                   'operator_confirmation': True,
                   'participants': [{'name': 'fixture-agent', 'role': 'agent', 'disposition': 'upgraded',
                                     'capabilities': ['harness-storage-layout/v1']}]}
    return record['id'], maintenance


def test_selected_exact_storage_option_and_maintenance_are_recognized(harness):
    from harness.storage import StorageRequest, plan_operation
    from harness.storage.migration import verify_authority

    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    failure = None
    try:
        decision_id, maintenance = qualified_grant(harness, plan)
    except ValueError as error:
        failure = str(error)
    assert failure is None, failure
    authority = verify_authority(harness, plan, decision_id, maintenance)
    assert authority['decision_id'] == decision_id
    assert authority['plan_digest'] == plan['plan_digest']
    assert not (harness.parent / '.harness-store').exists()


@pytest.mark.parametrize('defect', ['unselected', 'proposed', 'wrong-workspace', 'wrong-plan', 'wrong-kind',
                                   'wrong-store', 'wrong-task', 'wrong-scope'])
def test_nearby_or_unselected_grants_never_authorize_storage(harness, defect):
    from harness.storage import StorageError, StorageRequest, plan_operation
    from harness.storage.migration import verify_authority

    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    changes = {'wrong-workspace': {'workspace_id': '9' * 32},
               'wrong-plan': {'plan_digest': 'sha256:' + '9' * 64},
               'wrong-kind': {'operation': 'M1'}, 'wrong-store': {'store_id': '9' * 32},
               'wrong-task': {'task_id': 'TASK-999'}, 'wrong-scope': {'scope_digest': 'sha256:' + '9' * 64}}
    decision_id, maintenance = qualified_grant(harness, plan, change=changes.get(defect),
                                              selected='stay' if defect == 'unselected' else 'activate',
                                              accepted=defect != 'proposed')
    with pytest.raises(StorageError, match='STORE_AUTHORITY_REQUIRED'):
        verify_authority(harness, plan, decision_id, maintenance)
    assert not (harness.parent / '.harness-store').exists()


@pytest.mark.parametrize('defect', ['no-confirmation', 'incomplete-participants', 'no-capability', 'wrong-operation', 'extra-field'])
def test_maintenance_qualification_cannot_be_inferred_from_empty_process_reports(harness, defect):
    from harness.storage import StorageError, StorageRequest, plan_operation
    from harness.storage.migration import verify_authority

    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, plan)
    maintenance = deepcopy(maintenance)
    if defect == 'no-confirmation':
        maintenance['operator_confirmation'] = False
    elif defect == 'incomplete-participants':
        maintenance['participants_complete'] = False
    elif defect == 'no-capability':
        maintenance['participants'][0]['capabilities'] = []
    elif defect == 'wrong-operation':
        maintenance['operation'] = 'M1'
    else:
        maintenance['lsof_empty'] = True
    with pytest.raises(StorageError, match='STORE_AUTHORITY_REQUIRED'):
        verify_authority(harness, plan, decision_id, maintenance)


def test_plan_digest_cannot_be_reused_after_mutating_candidate_scope(harness):
    from harness.storage import StorageError, StorageRequest, plan_operation
    from harness.storage.migration import verify_authority

    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision_id, maintenance = qualified_grant(harness, plan)
    plan['qualification']['entries']['.harness/history/forged'] = {
        'identity': [1, 2], 'kind': 'directory', 'size': 0}
    with pytest.raises(StorageError, match='STORE_PLAN_STALE'):
        verify_authority(harness, plan, decision_id, maintenance)


def test_owned_store_changes_do_not_stale_product_or_enter_architecture(tmp_path):
    from harness.workspace import architecture_changes, architecture_path_index, snapshot
    from storage_factory import fixture_store

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    before = snapshot(repo)
    (store / 'experiments/diagnostic.json').write_text('{"updated":true}')
    after = snapshot(repo)
    assert after.fingerprint == before.fingerprint
    assert after.changed_paths == before.changed_paths
    assert not any('.harness-store/' in name for name in architecture_path_index(repo))
    assert not any('.harness-store/' in item.path for item in architecture_changes(before.head, repo))


def test_unowned_same_name_is_rejected_not_hidden_from_product(tmp_path):
    from harness.workspace import WorkspaceError, snapshot

    repo = repository(tmp_path)
    user = repo / '.harness-store'
    user.mkdir()
    (user / 'user-code.py').write_text('secret = 1')
    with pytest.raises(WorkspaceError, match='STORE_UNOWNED'):
        snapshot(repo)
    assert (user / 'user-code.py').read_text() == 'secret = 1'


def test_activation_requires_exact_selected_user_authority(tmp_path):
    from harness.storage import StorageError, StorageRequest, apply_operation, plan_operation

    repo = repository(tmp_path)
    plan = plan_operation(repo, StorageRequest(kind="ACTIVATE"))
    assert not (repo / ".harness-store").exists()
    with pytest.raises(StorageError, match="STORE_AUTHORITY_REQUIRED"):
        apply_operation(repo, plan, "DEC-999", {})
    assert not (repo / ".harness-store").exists()

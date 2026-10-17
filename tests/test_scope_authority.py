"""Replay selected retirement authority; audit alone never grants permission."""

import copy
import hashlib

import pytest
import test_context_builder
import yaml
from test_context_builder import _frozen_alignment, write_yaml
from test_decision import proposal
from test_evidence_plan import declarations
from test_test_scope import SCOPE_FILES, initialize_test_origin, scope_codes, tree_bytes

from harness import alignment, decision
from harness.context.freshness import digest

harness = test_context_builder.harness


def sha(path):
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def reseal(root, entries):
    """Test-only event publisher, not production apply authority."""
    head = sha(root / SCOPE_FILES[0])
    for i, event in enumerate(entries, 1):
        event.update(sequence=i, previous_hash=head)
        event.pop('hash', None)
        event['hash'] = digest(event)
        head = event['hash']
    write_yaml(root / SCOPE_FILES[1], {'version': 1, 'task_id': 'TASK-028', 'entries': entries})
    seal = yaml.safe_load((root / SCOPE_FILES[2]).read_text())
    seal.update(audit_hash=sha(root / SCOPE_FILES[1]), audit_head=head)
    write_yaml(root / SCOPE_FILES[2], seal)


def retirement(root, *, operation='RETIRE', selected='local', empty=False, plan=False):
    initialize_test_origin(root, ['test_old.py', 'test_new.py'])
    declarations(root, ['test_old.py', 'test_new.py'])
    requirements = yaml.safe_load((root / 'requirements.yaml').read_text())
    requirements['requirements'][0]['test_plan']['cases'][0]['tests'] = ['test_old.py']
    write_yaml(root / 'requirements.yaml', requirements)
    document = _frozen_alignment('TASK-028')
    write_yaml(root / 'alignment.yaml', document)
    impact_before, req_before = sha(root / 'impact.yaml'), sha(root / 'requirements.yaml')
    binding = {'owner': 'REQ-001', 'case': 'TC-001', 'before': ['test_old.py'],
               'after': [] if empty else ['test_new.py']}
    auth = {'version': 1, 'task_id': 'TASK-028', 'operation': operation,
            'expected_impact_hash': impact_before, 'contract_hash': alignment.contract_hash(document),
            'original_source': None, 'retirements': [] if operation == 'REBIND' else [
                {'test': 'test_old.py', 'reason_code': 'REPLACED_DECLARED_COVERAGE', 'replacement_tests': ['test_new.py']}],
            'bindings': [binding], 'plan_refs': ['P-1'] if plan else []}
    if plan:
        write_yaml(root / 'plan.yaml', {'version': 1, 'items': [
            {'id': 'P-1', 'intent': 'Cover requirement', 'requirement_refs': ['REQ-001'], 'test_case_refs': ['REQ-001/TC-001']} ]})
    value = proposal(recommendation='local')
    value['options'][0]['test_scope_authorization'] = auth
    value['scope'] = ['.harness/impact.yaml', '.harness/test-scope-audit.yaml', '.harness/test-scope-seal.yaml',
                      '.harness/requirements.yaml', *(['.harness/plan.yaml'] if plan else [])]
    value['constraints'] = ['PRESERVE_OBLIGATIONS', 'NO_EXECUTION', 'NO_RELEASE']
    created = decision.propose(root, value)
    accepted = decision.accept(root, created['id'], option=selected,
                               source='accepted_recommendation' if selected == 'local' else 'user_override')
    requirements['requirements'][0]['test_plan']['cases'][0]['tests'] = binding['after']
    write_yaml(root / 'requirements.yaml', requirements)
    after = ['test_new.py'] if operation == 'RETIRE' else ['test_old.py', 'test_new.py']
    write_yaml(root / 'impact.yaml', {'impact': {'changed': [], 'required_tests': after}})
    event = {'timestamp': '2026-10-14T00:00:00+00:00', 'operation': operation,
             'before_tests': ['test_new.py', 'test_old.py'], 'after_tests': sorted(after),
             'decision_refs': [{'id': accepted['id'], 'option': 'local', 'hash': sha(root / f"decisions/{accepted['id']}.yaml")}],
             'artifact_hashes': {'impact.yaml': {'before': impact_before, 'after': sha(root / 'impact.yaml')},
                                 'requirements.yaml': {'before': req_before, 'after': sha(root / 'requirements.yaml')}},
             'reason_code': 'AUTHORIZED_SCOPE_RECONCILIATION', 'affected_bindings': [binding], 'plan_refs': auth['plan_refs']}
    reseal(root, [event])
    return event


@pytest.mark.parametrize('operation', ['RETIRE', 'REBIND'])
@pytest.mark.parametrize('plan_state', ['absent', 'unrelated'])
def test_fast_scope_replay_captures_plan_guard_without_enabling_execution(harness, operation, plan_state):
    """Break caught: selected scope replay probes Plan outside captured source authority."""
    from harness.context.freshness import capture
    from harness.context.integrity import _load_stable

    retirement(harness, operation=operation)
    test_context_builder._write_matching_seal(harness, alignment.load_alignment(harness))
    if plan_state == 'unrelated':
        write_yaml(harness / 'plan.yaml', {'version': 1, 'items': [{'id': 'P-999', 'intent': 'Not linked'}]})
    # FAST must not open/parse this unrelated execution payload.
    (harness / 'plan-execution.yaml').write_text('invalid execution: [')
    assert scope_codes(harness) == set()  # Grant/Plan fixture valid before testing scoped read.
    before = tree_bytes(harness)
    versions = capture(harness)
    source = _load_stable(harness, versions)
    assert not {blocker.code for blocker in source.gate.blockers if blocker.code.startswith('TEST_SCOPE_')}
    assert source.plan is None and source.plan_execution is None
    assert versions['plan_hash'] is None and versions['plan_execution_hash'] is None
    assert 'plan-execution.yaml' not in versions['files']
    assert versions['declared_files']['.harness/plan.yaml'] == (None if plan_state == 'absent' else sha(harness / 'plan.yaml'))
    assert tree_bytes(harness) == before
    requirement = yaml.safe_load((harness / 'requirements.yaml').read_text())['requirements'][0]
    assert requirement['status'] == 'pending' and not requirement.get('evidence')


@pytest.mark.parametrize('operation', ['RETIRE', 'REBIND'])
@pytest.mark.parametrize(('attack', 'expected'), [('authorized', set()),
    ('unapproved_link', {'TEST_SCOPE_RETIREMENT_UNAUTHORIZED'}), ('malformed', {'TEST_SCOPE_AUDIT_INVALID'})])
def test_fast_captured_plan_guard_still_enforces_selected_references(harness, operation, attack, expected):
    from harness import quality_gate
    from harness.context.freshness import capture
    from harness.context.read_scope import context_read_scope

    retirement(harness, operation=operation, plan=attack == 'authorized')
    if attack == 'unapproved_link':
        write_yaml(harness / 'plan.yaml', {'version': 1, 'items': [{
            'id': 'P-999', 'intent': 'Unapproved link', 'requirement_refs': ['REQ-001'],
        }]})
    elif attack == 'malformed':
        (harness / 'plan.yaml').write_text('items: [')
    before = tree_bytes(harness)
    versions = capture(harness)
    with context_read_scope(harness, versions):
        assessment = quality_gate.assess_gate(harness, allow_preflight=True)
    assert {blocker.code for blocker in assessment.blockers if blocker.code.startswith('TEST_SCOPE_')} == expected
    assert tree_bytes(harness) == before


@pytest.mark.parametrize('attack', ['unselected', 'missing_selected', 'proposed', 'superseded', 'superseded_pointer', 'foreign',
                                  'foreign_body_current_index', 'no_grant'])
def test_inactive_or_foreign_scope_options_do_not_enroll_plan_guard(harness, attack):
    from harness.context.freshness import capture

    event = retirement(harness)
    path = harness / f"decisions/{event['decision_refs'][0]['id']}.yaml"
    record = yaml.safe_load(path.read_text())
    if attack == 'unselected':
        record['selected'] = {'option': 'redis', 'source': 'user_override', 'decided_by': 'user'}
    elif attack == 'missing_selected':
        record['selected'] = None
    elif attack == 'proposed':
        record.update(status='PROPOSED', selected=None, accepted_at=None)
    elif attack == 'superseded':
        record.update(status='SUPERSEDED', superseded_by='DEC-999')
    elif attack == 'superseded_pointer':
        record['superseded_by'] = 'DEC-999'
    elif attack in {'foreign', 'foreign_body_current_index'}:
        record['task_id'] = 'TASK-999'
    elif attack == 'no_grant':
        record['options'][0].pop('test_scope_authorization')
    write_yaml(path, record)
    decision.reindex(harness)
    if attack == 'foreign_body_current_index':
        index = yaml.safe_load((harness / 'decisions/index.yaml').read_text())
        index['decisions'][0]['task_id'] = 'TASK-028'
        write_yaml(harness / 'decisions/index.yaml', index)
    (harness / 'plan.yaml').write_text('unrelated malformed Plan: [')
    before = capture(harness)
    (harness / 'plan.yaml').write_text('other malformed Plan: [')
    assert capture(harness) == before
    assert '.harness/plan.yaml' not in before['declared_files'] and 'plan.yaml' not in before['files']


def test_migration_only_selection_does_not_enroll_fast_plan_guard(harness):
    from test_scope_migration import preparation

    from harness.context.freshness import capture

    preparation(harness)
    versions = capture(harness)
    assert '.harness/plan.yaml' not in versions['declared_files'] and 'plan.yaml' not in versions['files']


@pytest.mark.parametrize('initial', ['absent', 'present'])
def test_captured_scope_plan_change_rejects_stale_source_load(harness, initial):
    from harness.context.freshness import capture
    from harness.context.integrity import _load_stable
    from harness.context.model import ContextBuildError

    retirement(harness)
    test_context_builder._write_matching_seal(harness, alignment.load_alignment(harness))
    path = harness / 'plan.yaml'
    if initial == 'present':
        write_yaml(path, {'version': 1, 'items': [{'id': 'P-999', 'intent': 'Before'}]})
    before = capture(harness)
    write_yaml(path, {'version': 1, 'items': [{'id': 'P-999', 'intent': 'After'}]})
    with pytest.raises(ContextBuildError, match='CONTEXT_STALE'):
        _load_stable(harness, before)


def test_fast_first_retirement_keeps_guard_source_through_real_context_publication(harness):
    from test_scope_migration import retirement_after_reconstruction

    from harness.context.freshness import capture
    from harness.context.integrity import validate_context
    from harness.context.store import generate_context
    from harness.test_scope import apply_reconciliation

    request, _expected, _current = retirement_after_reconstruction(harness)
    task_before = (harness / 'current-task.yaml').read_bytes()
    before = capture(harness)
    assert before['declared_files']['.harness/plan.yaml'] is None
    apply_reconciliation(harness, request)
    assert (harness / 'current-task.yaml').read_bytes() == task_before
    assert capture(harness)['declared_files']['.harness/plan.yaml'] is None
    document = generate_context(harness)
    assert validate_context(harness, document) == {
        'completeness': True, 'accuracy': True, 'freshness': True, 'traceability': True,
    }
    assert scope_codes(harness) == set()
    expected_task = yaml.safe_load(task_before)
    actual_task = yaml.safe_load((harness / 'current-task.yaml').read_text())
    # Real automatic Context may legitimately consume expansion budget; no authority/state promotion.
    assert actual_task['budget'].pop('context_expansions', 0) >= expected_task['budget'].pop('context_expansions', 0)
    assert actual_task == expected_task
    requirement = yaml.safe_load((harness / 'requirements.yaml').read_text())['requirements'][0]
    assert requirement['status'] == 'pending' and not requirement.get('evidence')


@pytest.mark.parametrize(('operation', 'plan'), [('RETIRE', False), ('REBIND', False), ('RETIRE', True)])
def test_selected_scope_authority_replays_without_verifying_obligation(harness, operation, plan):
    retirement(harness, operation=operation, plan=plan)
    before = tree_bytes(harness)
    assert scope_codes(harness) == set()
    assert tree_bytes(harness) == before
    req = yaml.safe_load((harness / 'requirements.yaml').read_text())['requirements'][0]
    assert req['status'] == 'pending' and not req.get('evidence')


@pytest.mark.parametrize('attack', ['inactive', 'unknown_constraint', 'wrong_option', 'changed_decision', 'missing_binding',
                                  'wrong_after', 'missing_artifact', 'out_of_scope', 'missing_replacement', 'unmapped_case',
                                  'empty_must', 'plan_omitted', 'stale_impact_grant', 'implicit_extra'])
def test_resealed_audit_cannot_override_selected_authority_or_obligations(harness, attack):
    event = retirement(harness, selected='redis' if attack == 'inactive' else 'local',
                       empty=attack == 'empty_must', plan=attack == 'plan_omitted')
    decision_path = harness / f"decisions/{event['decision_refs'][0]['id']}.yaml"
    if attack in {'unknown_constraint', 'out_of_scope', 'changed_decision', 'stale_impact_grant'}:
        record = yaml.safe_load(decision_path.read_text())
        if attack == 'unknown_constraint':
            record['constraints'] = ['unrecognized broad prose']
        elif attack == 'out_of_scope':
            record['scope'].remove('.harness/requirements.yaml')
        elif attack == 'stale_impact_grant':
            record['options'][0]['test_scope_authorization']['expected_impact_hash'] = 'sha256:' + '0' * 64
        else:
            record['options'][0]['description'] = 'changed accepted decision'
        write_yaml(decision_path, record)
        decision.reindex(harness)
        if attack != 'changed_decision':
            event['decision_refs'][0]['hash'] = sha(decision_path)
    elif attack == 'wrong_option':
        event['decision_refs'][0]['option'] = 'redis'
    elif attack == 'missing_binding':
        event['affected_bindings'] = []
    elif attack == 'wrong_after':
        event['affected_bindings'][0]['after'] = ['test_old.py']
    elif attack == 'missing_artifact':
        event['artifact_hashes'].pop('requirements.yaml')
    elif attack == 'missing_replacement':
        (harness.parent / 'test_new.py').unlink()
    elif attack == 'unmapped_case':
        value = yaml.safe_load((harness / 'requirements.yaml').read_text())
        other = copy.deepcopy(value['requirements'][0]['test_plan']['cases'][0])
        other.update(id='TC-002', tests=['test_old.py'])
        value['requirements'][0]['test_plan']['cases'].append(other)
        write_yaml(harness / 'requirements.yaml', value)
    elif attack == 'plan_omitted':
        event['plan_refs'] = []
    elif attack == 'implicit_extra':
        event['after_tests'].append('test_unapproved.py')
    reseal(harness, [event])
    assert scope_codes(harness) == {'TEST_SCOPE_RETIREMENT_UNAUTHORIZED'}


@pytest.mark.parametrize('attack', ['must_without_plan', 'critical_without_cases', 'rebind_impact_changed', 'unchanged_binding_artifact'])
def test_authorized_event_cannot_hide_unmapped_obligation_or_fake_mutation(harness, attack):
    event = retirement(harness, operation='REBIND' if attack == 'rebind_impact_changed' else 'RETIRE')
    if attack == 'must_without_plan':
        path = harness / 'requirements.yaml'
        value = yaml.safe_load(path.read_text())
        value['requirements'].append({'id': 'REQ-002', 'statement': 'Still required', 'priority': 'must', 'status': 'pending'})
        write_yaml(path, value)
    elif attack == 'critical_without_cases':
        path = harness / 'invariants.yaml'
        value = yaml.safe_load(path.read_text())
        value['invariants'].append({'id': 'INV-002', 'statement': 'Still protected', 'category': 'correctness', 'severity': 'critical', 'status': 'pending'})
        write_yaml(path, value)
    elif attack == 'rebind_impact_changed':
        event['artifact_hashes']['impact.yaml']['after'] = 'sha256:' + '0' * 64
    else:
        event['artifact_hashes']['requirements.yaml']['after'] = event['artifact_hashes']['requirements.yaml']['before']
    reseal(harness, [event])
    assert scope_codes(harness) == {'TEST_SCOPE_RETIREMENT_UNAUTHORIZED'}


def test_valid_rebind_sequence_compares_final_not_intermediate_mapping(harness):
    first = retirement(harness, operation='REBIND')
    # Rebind back through second explicitly selected grant; first event remains immutable.
    path = harness / 'requirements.yaml'
    before_req = sha(path)
    before_impact = sha(harness / 'impact.yaml')
    binding = {'owner': 'REQ-001', 'case': 'TC-001', 'before': ['test_new.py'], 'after': ['test_old.py']}
    value = proposal(recommendation='local')
    value['options'][0]['test_scope_authorization'] = {
        'version': 1, 'task_id': 'TASK-028', 'operation': 'REBIND', 'expected_impact_hash': before_impact,
        'contract_hash': alignment.contract_hash(alignment.load_alignment(harness)), 'original_source': None,
        'retirements': [], 'bindings': [binding], 'plan_refs': []}
    value['scope'] = ['.harness/impact.yaml', '.harness/test-scope-audit.yaml', '.harness/test-scope-seal.yaml', '.harness/requirements.yaml']
    value['constraints'] = ['PRESERVE_OBLIGATIONS', 'NO_EXECUTION', 'NO_RELEASE']
    created = decision.propose(harness, value)
    accepted = decision.accept(harness, created['id'], option='local', source='accepted_recommendation')
    requirements = yaml.safe_load(path.read_text())
    requirements['requirements'][0]['test_plan']['cases'][0]['tests'] = ['test_old.py']
    write_yaml(path, requirements)
    second = {**copy.deepcopy(first), 'affected_bindings': [binding],
              'decision_refs': [{'id': accepted['id'], 'option': 'local', 'hash': sha(harness / f"decisions/{accepted['id']}.yaml")}],
              'artifact_hashes': {'impact.yaml': {'before': before_impact, 'after': before_impact},
                                  'requirements.yaml': {'before': before_req, 'after': sha(path)}}}
    reseal(harness, [first, second])
    assert scope_codes(harness) == set()
    # A selected grant with a false preceding mapping cannot splice into valid chain.
    second['affected_bindings'][0]['before'] = ['test_old.py']
    reseal(harness, [first, second])
    assert scope_codes(harness) == {'TEST_SCOPE_RETIREMENT_UNAUTHORIZED'}


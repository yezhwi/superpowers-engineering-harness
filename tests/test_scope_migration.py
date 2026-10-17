"""Explicit historical reconstruction never blesses current reduced subset."""

import hashlib
import importlib

import pytest
import test_context_builder
import yaml
from test_context_builder import enable_plan_reconciliation, write_yaml
from test_decision import proposal as decision_proposal
from test_test_scope import SCOPE_FILES, scope_codes, tree_bytes

from harness import alignment, decision
from harness.context.freshness import digest

harness = test_context_builder.harness


def module():
    result = importlib.import_module('harness.test_scope')
    assert hasattr(result, 'migrate_test_scope'), 'explicit original-set migration missing'
    return result


def preparation(root, *, selected='local', constraints=None, approved_subset=False,
                historical_sets=None, current_extras=(), level='Q1'):
    # Explicit legacy fixture: fresh v0.3.2 initialization now has genesis.
    for name in SCOPE_FILES:
        (root / name).unlink(missing_ok=True)
    enable_plan_reconciliation(root, level=level)
    original = [f'tests/test_{i:02}.py' for i in range(64)]
    write_yaml(root / 'impact.yaml', {'impact': {'changed': [], 'required_tests': [*original[:46], *current_extras]}})
    source = root / 'historical-impact.yaml'
    write_yaml(source, {'impact': {'changed': [], 'required_tests': original}})
    source_ref = '.harness/historical-impact.yaml'
    source_hash = 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest()
    impact_hash = 'sha256:' + hashlib.sha256((root / 'impact.yaml').read_bytes()).hexdigest()
    auth = {'version': 1, 'task_id': 'TASK-028', 'operation': 'MIGRATE',
            'expected_impact_hash': impact_hash,
            'contract_hash': alignment.contract_hash(alignment.load_alignment(root)),
            'original_source': {'path': source_ref, 'hash': source_hash, 'tests_hash': digest(original[:46] if approved_subset else original)},
            'retirements': [], 'bindings': [], 'plan_refs': []}
    history = []
    for i, tests in enumerate(historical_sets or []):
        path = root / f'historical-add-{i}.yaml'
        write_yaml(path, {'impact': {'changed': [], 'required_tests': tests}})
        history.append({'path': f'.harness/{path.name}',
                        'hash': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest(),
                        'tests_hash': digest(tests)})
    if history:
        auth['historical_sources'] = history
    value = decision_proposal(recommendation='local')
    value['options'][0]['test_scope_authorization'] = auth
    value['scope'] = [source_ref, *(item['path'] for item in history), '.harness/impact.yaml', '.harness/gate.yaml',
                      *(f'.harness/{name}' for name in SCOPE_FILES)]
    value['constraints'] = constraints or []
    created = decision.propose(root, value)
    accepted = decision.accept(root, created['id'], option=selected, source='accepted_recommendation' if selected == 'local' else 'user_override')
    migration = {'version': 1, 'task_id': 'TASK-028', 'expected_impact_hash': impact_hash,
                 'decision_ref': accepted['id'], 'original_source': auth['original_source']}
    if history:
        migration['historical_sources'] = history
    return migration, original


def retirement_after_reconstruction(root, *, historical=False, level='Q1'):
    """Valid fixture grants separate MIGRATE then exact RETIRE; never real task authority."""
    request, original = historical_preparation(root, level=level) if historical else preparation(root, level=level)
    current = yaml.safe_load((root / 'impact.yaml').read_text())['impact']['required_tests']
    expected = [*original, *[test for test in current if test not in original]]
    for name in current:
        path = root.parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raise RuntimeError('declared targets must not import')\ndef test_ok():\n    pass\n")
    write_yaml(root / 'requirements.yaml', {'requirements': [{
        'id': 'REQ-001', 'statement': 'Keep original behavior', 'priority': 'must', 'status': 'pending',
        'test_plan': {'strategies': ['unit'], 'cases': [{
            'id': 'TC-001', 'type': 'happy_path', 'strategy': 'unit',
            'description': 'preserve declared obligation', 'tests': expected,
        }]},
    }]})
    result = module().migrate_test_scope(root, request)
    assert result['status'] == 'BLOCKED' and scope_codes(root) == {'TEST_SCOPE_RETIREMENT_UNAUDITED'}
    return select_retirement(root, expected, current, original[46:]), expected, current


def select_retirement(root, expected, current, removed):
    impact_hash = 'sha256:' + hashlib.sha256((root / 'impact.yaml').read_bytes()).hexdigest()
    retirements = [{'test': test, 'reason_code': 'REPLACED_DECLARED_COVERAGE', 'replacement_tests': [current[0]]}
                   for test in removed]
    value = decision_proposal(topic='explicit retired historical coverage', recommendation='local')
    value['constraints'] = ['PRESERVE_OBLIGATIONS', 'PRESERVE_RISK', 'NO_EXECUTION', 'NO_RELEASE']
    value['scope'] = [f'.harness/{name}' for name in ('impact.yaml', 'requirements.yaml', SCOPE_FILES[1], SCOPE_FILES[2])]
    value['options'][0]['test_scope_authorization'] = {
        'version': 1, 'task_id': 'TASK-028', 'operation': 'RETIRE', 'expected_impact_hash': impact_hash,
        'contract_hash': alignment.contract_hash(alignment.load_alignment(root)), 'original_source': None,
        'retirements': retirements,
        'bindings': [{'owner': 'REQ-001', 'case': 'TC-001', 'before': expected, 'after': current}], 'plan_refs': [],
    }
    created = decision.propose(root, value)
    accepted = decision.accept(root, created['id'], option='local', source='accepted_recommendation')
    return {'version': 1, 'task_id': 'TASK-028', 'expected_impact_hash': impact_hash,
            'retirements': [{**item, 'decision_ref': accepted['id']} for item in retirements],
            'bindings': [{'owner': 'REQ-001', 'case': 'TC-001', 'tests': current}]}


@pytest.mark.parametrize('historical', [False, True])
@pytest.mark.parametrize('entry', ['domain', 'cli', 'dry_run'])
def test_selected_retirement_continues_reconstructed_missing_scope(harness, historical, entry):
    """Break caught: strict current mismatch must not make valid selected repair unreachable."""
    from test_scope_joint import cli

    request, expected, current = retirement_after_reconstruction(harness, historical=historical)
    before = tree_bytes(harness)
    audit_before = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
    if entry == 'dry_run':
        report = module().plan_reconciliation(harness, request)
        assert report['status'] == 'VALIDATED', report['diagnostics']
        assert report['execution_counts'] == {'tests': 0, 'business': 0, 'environment': 0}
        assert tree_bytes(harness) == before
        assert scope_codes(harness) == {'TEST_SCOPE_RETIREMENT_UNAUDITED'}
        return
    if entry == 'cli':
        path = harness.parent / 'retirement.yaml'
        write_yaml(path, request)
        result = cli(harness, 'impact', 'reconcile', '--file', str(path))
        assert result.returncode == 0, result.stderr
    else:
        module().apply_reconciliation(harness, request)
    assert scope_codes(harness) == set()
    assert (harness / SCOPE_FILES[0]).read_bytes() == before[SCOPE_FILES[0]]
    assert (harness / 'current-task.yaml').read_bytes() == before['current-task.yaml']
    audit = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
    assert audit['entries'][:-1] == audit_before['entries']
    event = audit['entries'][-1]
    assert event['operation'] == 'RETIRE' and event['before_tests'] == sorted(expected) and event['after_tests'] == sorted(current)
    assert yaml.safe_load((harness / 'impact.yaml').read_text())['impact']['required_tests'] == current
    requirement = yaml.safe_load((harness / 'requirements.yaml').read_text())['requirements'][0]
    assert (requirement['statement'], requirement['priority'], requirement['status']) == ('Keep original behavior', 'must', 'pending')
    assert requirement['test_plan']['cases'][0]['tests'] == current and not requirement.get('evidence')
    for name, data in before.items():
        if name not in {'impact.yaml', 'requirements.yaml', SCOPE_FILES[1], SCOPE_FILES[2]}:
            assert (harness / name).read_bytes() == data


def test_missing_scope_repair_preserves_prior_retirement_mapping_continuity(harness):
    # STANDARD intentionally declares Plan facts. FAST replay issue tracked separately as FND023.
    request, _expected, current = retirement_after_reconstruction(harness, historical=True, level='Q2')
    module().apply_reconciliation(harness, request)
    retired = current[1]
    remaining = [test for test in current if test != retired]
    impact = yaml.safe_load((harness / 'impact.yaml').read_text())
    impact['impact']['required_tests'] = remaining
    write_yaml(harness / 'impact.yaml', impact)
    (harness.parent / retired).unlink()  # Temporary fixture target, never production file.
    request = select_retirement(harness, current, remaining, [retired])
    baseline = (harness / SCOPE_FILES[0]).read_bytes()
    audit = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
    report = module().plan_reconciliation(harness, request)
    assert report['status'] == 'VALIDATED', report['diagnostics']
    module().apply_reconciliation(harness, request)
    assert scope_codes(harness) == set() and (harness / SCOPE_FILES[0]).read_bytes() == baseline
    after = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
    assert after['entries'][:-1] == audit['entries']
    assert after['entries'][-1]['before_tests'] == sorted(current)
    assert after['entries'][-1]['after_tests'] == sorted(remaining)


@pytest.mark.parametrize('entry', ['domain', 'dry_run'])
@pytest.mark.parametrize('attack', ['inactive', 'partial_authority', 'unapproved_extra', 'stale', 'origin', 'seal',
                                  'foreign_task', 'contract', 'unmapped', 'empty_must', 'no_op', 'rebind',
                                  'scope', 'other_guard', 'grant_union', 'unrelated_must'])
def test_reconstructed_scope_repair_rejects_incomplete_authority_without_writes(harness, monkeypatch, entry, attack):
    request, expected, _current = retirement_after_reconstruction(harness)
    decision_id = request['retirements'][0]['decision_ref']
    path = harness / f'decisions/{decision_id}.yaml'
    record = yaml.safe_load(path.read_text())
    grant = record['options'][0]['test_scope_authorization']
    if attack == 'inactive':
        record['selected']['option'] = 'redis'
        record['selected']['source'] = 'user_override'
    elif attack == 'partial_authority':
        grant['retirements'] = grant['retirements'][:-1]
        request['retirements'] = request['retirements'][:-1]
    elif attack == 'unapproved_extra':
        impact = yaml.safe_load((harness / 'impact.yaml').read_text())
        impact['impact']['required_tests'].append('tests/operator.py')
        write_yaml(harness / 'impact.yaml', impact)
        (harness.parent / 'tests/operator.py').write_text('def test_operator():\n    pass\n')
        new_hash = 'sha256:' + hashlib.sha256((harness / 'impact.yaml').read_bytes()).hexdigest()
        request['expected_impact_hash'] = grant['expected_impact_hash'] = new_hash
    elif attack == 'stale':
        request['expected_impact_hash'] = 'sha256:' + '0' * 64
    elif attack == 'origin':
        historical = harness / 'historical-impact.yaml'
        historical.write_bytes(historical.read_bytes() + b'\n')
    elif attack == 'seal':
        value = yaml.safe_load((harness / SCOPE_FILES[2]).read_text())
        value['audit_hash'] = 'sha256:' + '0' * 64
        write_yaml(harness / SCOPE_FILES[2], value)
    elif attack == 'foreign_task':
        grant['task_id'] = 'TASK-999'
    elif attack == 'contract':
        value = yaml.safe_load((harness / 'alignment.yaml').read_text())
        value['goal'] = 'unapproved goal change'
        write_yaml(harness / 'alignment.yaml', value)
    elif attack == 'unmapped':
        request['bindings'] = []
    elif attack == 'empty_must':
        grant['bindings'][0]['after'] = request['bindings'][0]['tests'] = []
    elif attack == 'no_op':
        request['retirements'] = request['bindings'] = []
    elif attack == 'rebind':
        grant['operation'] = 'REBIND'
        grant['retirements'] = request['retirements'] = []
    elif attack == 'scope':
        record['scope'].remove('.harness/requirements.yaml')
    elif attack == 'other_guard':
        value = yaml.safe_load((harness / 'alignment-freeze.yaml').read_text())
        value['contract_hash'] = 'sha256:' + '0' * 64
        write_yaml(harness / 'alignment-freeze.yaml', value)
    elif attack == 'grant_union':
        request['retirements'][0]['decision_ref'] = 'DEC-001'
    elif attack == 'unrelated_must':
        document = yaml.safe_load((harness / 'requirements.yaml').read_text())
        case = dict(document['requirements'][0]['test_plan']['cases'][0])
        case.update(id='TC-002', tests=[expected[-1]])
        document['requirements'][0]['test_plan']['cases'].append(case)
        write_yaml(harness / 'requirements.yaml', document)
    write_yaml(path, record)
    decision.reindex(harness)
    before = tree_bytes(harness)

    def unexpected_stage(*args, **kwargs):
        pytest.fail('rejected candidate reached staging')

    monkeypatch.setattr(importlib.import_module('harness.transaction'), 'stage', unexpected_stage)
    if entry == 'dry_run':
        try:
            report = module().plan_reconciliation(harness, request)
        except ValueError:
            pass
        else:
            assert report['status'] == 'BLOCKED'
    else:
        with pytest.raises(ValueError):
            module().apply_reconciliation(harness, request)
    assert tree_bytes(harness) == before


@pytest.mark.parametrize('drift', ['binding_continuity', 'retired_reference'])
def test_missing_scope_repair_cannot_erase_prior_binding_or_retirement(harness, monkeypatch, drift):
    request, expected, current = retirement_after_reconstruction(harness, historical=True, level='Q2')
    module().apply_reconciliation(harness, request)
    removed = current[1]
    remaining = [test for test in current if test != removed]
    impact = yaml.safe_load((harness / 'impact.yaml').read_text())
    impact['impact']['required_tests'] = remaining
    write_yaml(harness / 'impact.yaml', impact)
    document = yaml.safe_load((harness / 'requirements.yaml').read_text())
    cases = document['requirements'][0]['test_plan']['cases']
    old_binding = current
    if drift == 'binding_continuity':
        old_binding = [test for test in current if test != current[2]]
        cases[0]['tests'] = old_binding
    else:
        cases.append({**cases[0], 'id': 'TC-002', 'strategy': 'manual', 'tests': [expected[50]]})
    write_yaml(harness / 'requirements.yaml', document)
    request = select_retirement(harness, old_binding, remaining, [removed])
    before = tree_bytes(harness)

    def unexpected_stage(*args, **kwargs):
        pytest.fail('historical mapping drift reached staging')

    monkeypatch.setattr(importlib.import_module('harness.transaction'), 'stage', unexpected_stage)
    with pytest.raises(ValueError):
        module().apply_reconciliation(harness, request)
    report = module().plan_reconciliation(harness, request)
    assert report['status'] == 'BLOCKED' and tree_bytes(harness) == before


def test_authorized_reconstruction_restores_original64_not_current46(harness):
    target = module()
    request, original = preparation(harness)
    before = tree_bytes(harness)
    result = target.migrate_test_scope(harness, request)
    baseline = yaml.safe_load((harness / SCOPE_FILES[0]).read_text())
    assert baseline['required_tests'] == original
    assert baseline['origin']['kind'] == 'authorized_reconstruction'
    assert 'TEST_SCOPE_RETIREMENT_UNAUDITED' in scope_codes(harness)
    assert result['status'] == 'BLOCKED'
    # Reconstruction grants no retirements, state/status/evidence or contract edits.
    for name, data in before.items():
        if name != 'gate.yaml':
            assert (harness / name).read_bytes() == data


@pytest.mark.parametrize('attack', ['inactive_option', 'subset', 'unsupported_constraint', 'source_changed', 'impact_changed'])
def test_reconstruction_authority_failures_write_zero_origin(harness, attack):
    target = module()
    request, _ = preparation(harness, selected='redis' if attack == 'inactive_option' else 'local',
                             constraints=['arbitrary prose cannot grant permission'] if attack == 'unsupported_constraint' else None,
                             approved_subset=attack == 'subset')
    if attack == 'source_changed':
        (harness / 'historical-impact.yaml').write_text('impact: {required_tests: []}\n')
    elif attack == 'impact_changed':
        (harness / 'impact.yaml').write_text('impact: {changed: [], required_tests: []}\n')
    before = tree_bytes(harness)
    with pytest.raises(ValueError):
        target.migrate_test_scope(harness, request)
    assert tree_bytes(harness) == before
    assert not any((harness / name).exists() for name in SCOPE_FILES)


def test_origin_decision_content_change_revokes_scope_trust(harness):
    target = module()
    request, _ = preparation(harness)
    target.migrate_test_scope(harness, request)
    path = harness / f"decisions/{request['decision_ref']}.yaml"
    document = yaml.safe_load(path.read_text())
    document['options'][0]['description'] = 'operator changed accepted grant'
    write_yaml(path, document)
    decision.reindex(harness)
    assert 'TEST_SCOPE_RETIREMENT_UNAUTHORIZED' in scope_codes(harness)


def historical_preparation(root, *, level='Q1'):
    original = [f'tests/test_{i:02}.py' for i in range(64)]
    sets = [[*original, 'tests/history_a.py'], [*original, 'tests/history_a.py', 'tests/history_b.py']]
    return preparation(root, historical_sets=sets, current_extras=('tests/history_a.py', 'tests/history_b.py'), level=level)


def test_historical_additions_replay_without_blessing_original_retirements(harness):
    request, original = historical_preparation(harness)
    impact_bytes = (harness / 'impact.yaml').read_bytes()
    result = module().migrate_test_scope(harness, request)
    baseline = yaml.safe_load((harness / SCOPE_FILES[0]).read_text())
    audit = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
    assert baseline['required_tests'] == original  # Original 64 not reduced 46 or union 66.
    assert [(len(event['before_tests']), len(event['after_tests'])) for event in audit['entries']] == [(64, 65), (65, 66)]
    assert all(event['operation'] == 'HISTORICAL_ADD' for event in audit['entries'])
    assert result['diagnostics'] == [{'code': 'TEST_SCOPE_RETIREMENT_UNAUDITED'}]
    assert (harness / 'impact.yaml').read_bytes() == impact_bytes
    write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': [*original, 'tests/history_a.py', 'tests/history_b.py']}})
    assert scope_codes(harness) == set()
    write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': [*original, 'tests/history_b.py']}})
    assert scope_codes(harness) == {'TEST_SCOPE_RETIREMENT_UNAUDITED'}


@pytest.mark.parametrize('attack', ['unapproved', 'subset_scope', 'changed_source', 'shrinking_history', 'duplicate_source',
                                  'live_source', 'unproven_extra'])
def test_historical_additions_require_exact_selected_sources_without_partial_write(harness, attack):
    request, original = historical_preparation(harness)
    if attack == 'unapproved':
        request['historical_sources'] = request['historical_sources'][:1]
    elif attack == 'changed_source':
        (harness / 'historical-add-0.yaml').write_bytes(b'impact: {required_tests: []}\n')
    elif attack == 'unproven_extra':
        value = yaml.safe_load((harness / 'impact.yaml').read_text())
        value['impact']['required_tests'].append('tests/unproven.py')
        write_yaml(harness / 'impact.yaml', value)
        request['expected_impact_hash'] = 'sha256:' + hashlib.sha256((harness / 'impact.yaml').read_bytes()).hexdigest()
        path = harness / f"decisions/{request['decision_ref']}.yaml"
        approved = yaml.safe_load(path.read_text())
        approved['options'][0]['test_scope_authorization']['expected_impact_hash'] = request['expected_impact_hash']
        write_yaml(path, approved)
        decision.reindex(harness)
    else:
        path = harness / f"decisions/{request['decision_ref']}.yaml"
        value = yaml.safe_load(path.read_text())
        if attack == 'subset_scope':
            value['scope'].remove(request['historical_sources'][0]['path'])
        elif attack == 'duplicate_source':
            request['historical_sources'].append(request['historical_sources'][0])
            value['options'][0]['test_scope_authorization']['historical_sources'] = request['historical_sources']
        elif attack == 'live_source':
            # Current scope cannot double as supposedly immutable history source.
            write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': [*original, 'tests/history_a.py', 'tests/history_b.py']}})
            raw = 'sha256:' + hashlib.sha256((harness / 'impact.yaml').read_bytes()).hexdigest()
            request['expected_impact_hash'] = raw
            request['historical_sources'] = [{'path': '.harness/impact.yaml', 'hash': raw,
                                              'tests_hash': digest([*original, 'tests/history_a.py', 'tests/history_b.py'])}]
            grant = value['options'][0]['test_scope_authorization']
            grant['expected_impact_hash'] = raw
            grant['historical_sources'] = request['historical_sources']
        else:
            write_yaml(harness / 'historical-add-1.yaml', {'impact': {'required_tests': original[1:]}})
            descriptor = request['historical_sources'][1]
            descriptor['hash'] = 'sha256:' + hashlib.sha256((harness / 'historical-add-1.yaml').read_bytes()).hexdigest()
            descriptor['tests_hash'] = digest(original[1:])
            value['options'][0]['test_scope_authorization']['historical_sources'] = request['historical_sources']
        write_yaml(path, value)
        decision.reindex(harness)
    before = tree_bytes(harness)
    with pytest.raises(ValueError, match='TEST_SCOPE_'):
        module().migrate_test_scope(harness, request)
    assert tree_bytes(harness) == before


def test_historical_migration_publication_failure_restores_all_canonical_bytes(harness, monkeypatch):
    from test_reconcile_apply import assert_restored_with_retained_inputs

    from harness import transaction

    request, _ = historical_preparation(harness)
    before = tree_bytes(harness)
    publish = transaction.publish

    def fail_after_replacements(*args, **kwargs):
        def fail():
            raise OSError('history publication fault')
        kwargs['after_publish'] = fail
        return publish(*args, **kwargs)

    monkeypatch.setattr(transaction, 'publish', fail_after_replacements)
    with pytest.raises(OSError, match='history publication fault'):
        module().migrate_test_scope(harness, request)
    assert_restored_with_retained_inputs(harness, before)
    assert not any((harness / name).exists() for name in SCOPE_FILES)


def test_historical_chain_cannot_be_erased_even_with_resealed_empty_audit(harness):
    request, _ = historical_preparation(harness)
    module().migrate_test_scope(harness, request)
    write_yaml(harness / SCOPE_FILES[1], {'version': 1, 'task_id': 'TASK-028', 'entries': []})
    seal = yaml.safe_load((harness / SCOPE_FILES[2]).read_text())
    seal['audit_hash'] = 'sha256:' + hashlib.sha256((harness / SCOPE_FILES[1]).read_bytes()).hexdigest()
    seal['audit_head'] = seal['baseline_hash']
    write_yaml(harness / SCOPE_FILES[2], seal)
    assert scope_codes(harness) == {'TEST_SCOPE_AUDIT_INVALID'}


def test_formal_add_after_history_retains_both_kinds_of_obligation(harness):
    request, original = historical_preparation(harness)
    module().migrate_test_scope(harness, request)
    tests = [*original, 'tests/history_a.py', 'tests/history_b.py']
    write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': tests}})
    path = harness.parent / 'tests/new_feature.py'
    path.parent.mkdir(exist_ok=True)
    path.write_text('def test_ok():\n    pass\n')
    module().add_required_test(harness, 'tests/new_feature.py')
    assert scope_codes(harness) == set()
    audit = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
    assert [event['operation'] for event in audit['entries']] == ['HISTORICAL_ADD', 'HISTORICAL_ADD', 'ADD']
    assert 'tests/new_feature.py' in audit['entries'][-1]['after_tests']
    write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': tests}})
    assert scope_codes(harness) == {'TEST_SCOPE_RETIREMENT_UNAUDITED'}


def test_history_sources_enrolled_in_authoritative_capture(harness):
    from harness.context.freshness import capture

    request, _ = historical_preparation(harness)
    before = capture(harness)
    assert '.harness/historical-add-0.yaml' in before['declared_files']
    (harness / 'historical-add-0.yaml').write_bytes((harness / 'historical-add-0.yaml').read_bytes() + b'\n')
    assert capture(harness) != before
    with pytest.raises(ValueError, match='TEST_SCOPE_'):
        module().migrate_test_scope(harness, request)


def test_historical_source_change_revokes_published_origin(harness):
    request, _ = historical_preparation(harness)
    module().migrate_test_scope(harness, request)
    (harness / 'historical-add-0.yaml').write_bytes(b'impact: {required_tests: []}\n')
    assert scope_codes(harness) == {'TEST_SCOPE_RETIREMENT_UNAUTHORIZED'}


def prepare_refreeze(harness, historical=False):
    from pathlib import Path

    from harness.cli import main
    from harness.repository import find_git_root

    request, original = historical_preparation(harness, level='Q3') if historical else preparation(harness, level='Q3')
    write_yaml(harness / 'requirements.yaml', {'requirements': [{
        'id': 'REQ-001', 'statement': 'Keep original behavior', 'priority': 'must',
        'status': 'pending', 'source': 'spec', 'evidence': [],
    }]})
    module().migrate_test_scope(harness, request)
    expected = [*original, *(['tests/history_a.py', 'tests/history_b.py'] if historical else [])]
    # Restore the immutable original projection, not a newly authorized subset.
    impact = yaml.safe_load((harness / 'impact.yaml').read_text())
    impact['impact']['required_tests'] = expected
    write_yaml(harness / 'impact.yaml', impact)
    assert scope_codes(harness) == set()
    intent_hash = alignment.contract_hash(alignment.load_alignment(harness))
    immutable = {name: (harness / name).read_bytes() for name in SCOPE_FILES}
    immutable.update({str(path.relative_to(harness)): path.read_bytes()
                      for path in (harness / 'decisions').glob('*.yaml')})
    immutable['historical-impact.yaml'] = (harness / 'historical-impact.yaml').read_bytes()
    for descriptor in request.get('historical_sources', []):
        path = harness.parent / descriptor['path']
        immutable[str(path.relative_to(harness))] = path.read_bytes()

    def cli(*args):
        assert Path.cwd().resolve() == harness.parent.resolve()
        assert (harness.parent / '.git').is_dir()
        assert find_git_root(Path.cwd()).resolve() == harness.parent.resolve()
        return main(['align', *args])

    return cli, intent_hash, immutable


@pytest.mark.parametrize('historical', [False, True])
def test_migrated_scope_refreezes_unchanged_intent(harness, historical, capsys):
    """Break caught: refreeze replays authority against unfrozen canonical intent."""
    cli, intent_hash, immutable = prepare_refreeze(harness, historical)
    assert cli('check') == 0, capsys.readouterr()
    assert cli('revise', '--reason', 'unchanged-intent migrated-scope regression') == 0
    assert alignment.contract_hash(alignment.load_alignment(harness)) == intent_hash
    assert not alignment.load_alignment(harness)['freeze']['frozen']
    assert cli('freeze') == 0, capsys.readouterr()
    assert cli('check') == 0
    assert scope_codes(harness) == set()
    assert alignment.load_alignment(harness)['freeze']['contract_hash'] == intent_hash
    assert all((harness / name).read_bytes() == data for name, data in immutable.items())


def refreeze_canonical(root):
    paths = [*root.glob('*.yaml'), *(root / 'decisions').glob('*.yaml')]
    return {str(path.relative_to(root)): path.read_bytes() for path in paths}


@pytest.mark.parametrize('attack', ['intent', 'grant', 'source', 'audit', 'baseline_missing', 'seal_missing', 'seal_invalid', 'seal_yaml', 'seal_empty'])
def test_refreeze_refuses_invalid_authority_without_partial_freeze(harness, attack):
    cli, _, _ = prepare_refreeze(harness, historical=True)
    assert cli('check') == 0
    assert cli('revise', '--reason', 'negative authority control') == 0
    if attack == 'intent':
        document = alignment.load_alignment(harness)
        document['scope']['in'].append('unapproved new intent')
        write_yaml(harness / 'alignment.yaml', document)
    elif attack == 'grant':
        path = next((harness / 'decisions').glob('DEC-*.yaml'))
        document = yaml.safe_load(path.read_text())
        document['options'][0]['description'] += ' unauthorized edit'
        write_yaml(path, document)
    elif attack == 'source':
        (harness / 'historical-add-0.yaml').write_bytes(b'impact: {required_tests: []}\n')
    elif attack == 'audit':
        document = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
        document['entries'] = []
        write_yaml(harness / SCOPE_FILES[1], document)
    elif attack == 'baseline_missing':
        (harness / SCOPE_FILES[0]).unlink()
    elif attack == 'seal_missing':
        (harness / SCOPE_FILES[2]).unlink()
    elif attack == 'seal_yaml':
        (harness / SCOPE_FILES[2]).write_text('private_secret: [FND033-SENSITIVE')
    elif attack == 'seal_empty':
        (harness / SCOPE_FILES[2]).write_text('')
    else:
        (harness / SCOPE_FILES[2]).write_text('version: 0\n')
    before = refreeze_canonical(harness)
    assert cli('freeze') == 2
    assert refreeze_canonical(harness) == before
    assert not (harness / 'alignment-freeze.yaml').exists()
    assert not alignment.load_alignment(harness)['freeze']['frozen']


@pytest.mark.parametrize('window', ['stage', 'applied'])
def test_refreeze_refuses_plan_membership_drift(harness, monkeypatch, window, capsys):
    from harness import publication_journal, transaction

    cli, _, _ = prepare_refreeze(harness)
    assert cli('revise', '--reason', 'source drift control') == 0
    before = refreeze_canonical(harness)
    path = harness / 'plan.yaml'
    assert not path.exists()
    if window == 'stage':
        original = transaction.stage

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            write_yaml(path, {'version': 1, 'items': []})
            return result

        monkeypatch.setattr(transaction, 'stage', changed)
    else:
        original = publication_journal.Operation.apply

        def changed(operation):
            original(operation)
            write_yaml(path, {'version': 1, 'items': []})

        monkeypatch.setattr(publication_journal.Operation, 'apply', changed)
    assert cli('freeze') == 2
    assert 'CONTEXT_STALE' in capsys.readouterr().err
    assert refreeze_canonical(harness) == {**before, 'plan.yaml': path.read_bytes()}
    assert not (harness / 'alignment-freeze.yaml').exists()


def test_refreeze_pins_unrelated_decision_body(harness, monkeypatch, capsys):
    from harness import publication_journal

    cli, _, _ = prepare_refreeze(harness)
    value = decision_proposal(topic='unrelated current-task fact', recommendation='local')
    created = decision.propose(harness, value)
    accepted = decision.accept(harness, created['id'], option='local', source='accepted_recommendation')
    assert cli('check') == 0
    assert cli('revise', '--reason', 'raw decision drift control') == 0
    before = refreeze_canonical(harness)
    path = harness / f"decisions/{accepted['id']}.yaml"
    original = publication_journal.Operation.apply

    def changed(operation):
        original(operation)
        document = yaml.safe_load(path.read_text())
        document['options'][0]['description'] += ' external edit'
        write_yaml(path, document)

    monkeypatch.setattr(publication_journal.Operation, 'apply', changed)
    assert cli('freeze') == 2
    assert 'CONTEXT_STALE' in capsys.readouterr().err
    assert refreeze_canonical(harness) == {**before, str(path.relative_to(harness)): path.read_bytes()}
    assert not (harness / 'alignment-freeze.yaml').exists()


@pytest.mark.parametrize('fault', ['raise', 'mismatch'])
def test_refreeze_validates_frozen_candidate_under_owner_and_compensates(harness, monkeypatch, capsys, fault):
    from test_publication_admission import assert_review_owner

    from harness import _scope_replay

    cli, _, _ = prepare_refreeze(harness)
    assert cli('revise', '--reason', 'candidate validator fault control') == 0
    before = refreeze_canonical(harness)
    observed = []

    def failed(root):
        assert_review_owner(root)
        observed.append(alignment.load_alignment(root)['freeze']['frozen'])
        if fault == 'raise':
            raise ValueError('candidate scope validation fault')

    monkeypatch.setattr(_scope_replay, 'freeze_scope_facts', failed)
    assert cli('freeze') == 2
    assert observed == [True]
    expected_error = 'candidate scope validation fault' if fault == 'raise' else 'ALIGNMENT_FREEZE_INVALID'
    assert expected_error in capsys.readouterr().err
    assert refreeze_canonical(harness) == before
    assert not (harness / 'alignment-freeze.yaml').exists()


@pytest.mark.parametrize('fault', ['semantic', 'malformed'])
def test_refreeze_refuses_input_changed_after_initial_read(harness, monkeypatch, capsys, fault):
    from harness.context import freshness

    cli, _, _ = prepare_refreeze(harness)
    assert cli('revise', '--reason', 'early input drift control') == 0
    before = refreeze_canonical(harness)
    original = freshness.capture

    def changed(root):
        result = original(root)
        if fault == 'malformed':
            (harness / 'alignment.yaml').write_text('private_secret: [FND033-SENSITIVE')
        else:
            document = alignment.load_alignment(harness)
            document['goal']['summary'] += ' external edit'
            write_yaml(harness / 'alignment.yaml', document)
        return result

    monkeypatch.setattr(freshness, 'capture', changed)
    assert cli('freeze') == 2
    error = capsys.readouterr().err
    assert ('CONTEXT_STALE' if fault == 'semantic' else 'ALIGNMENT_FREEZE_INVALID') in error
    assert 'FND033-SENSITIVE' not in error
    assert refreeze_canonical(harness) == {**before, 'alignment.yaml': (harness / 'alignment.yaml').read_bytes()}
    assert not (harness / 'alignment-freeze.yaml').exists()


def test_refreeze_legacy_absent_origin_does_not_invent_scope(harness):
    cli, _, _ = prepare_refreeze(harness)
    assert cli('revise', '--reason', 'legacy missing origin') == 0
    for name in SCOPE_FILES:
        (harness / name).unlink()
    assert cli('freeze') == 0
    assert yaml.safe_load((harness / 'alignment-freeze.yaml').read_text())['version'] == 2
    assert not any((harness / name).exists() for name in SCOPE_FILES)
    assert scope_codes(harness) == {'TEST_SCOPE_AUDIT_INVALID'}

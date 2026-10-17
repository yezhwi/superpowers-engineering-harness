"""Authorized scope publication preserves obligations and immutable evidence."""

import hashlib
import importlib

import pytest
import test_context_builder
import yaml
from test_context_builder import _frozen_alignment, write_yaml
from test_decision import proposal
from test_evidence_plan import declarations
from test_test_scope import initialize_test_origin, scope_codes, tree_bytes

from harness import alignment, decision, transaction

harness = test_context_builder.harness


def target():
    module = importlib.import_module('harness.test_scope')
    assert hasattr(module, 'apply_reconciliation'), 'authorized atomic apply missing'
    return module


def prepare(root, *, selected='local'):
    initialize_test_origin(root, ['test_old.py', 'test_new.py'])
    declarations(root, ['test_old.py', 'test_new.py'])
    req = yaml.safe_load((root / 'requirements.yaml').read_text())
    req['requirements'][0]['test_plan']['cases'][0]['tests'] = ['test_old.py']
    write_yaml(root / 'requirements.yaml', req)
    document = _frozen_alignment('TASK-028')
    write_yaml(root / 'alignment.yaml', document)
    (root / 'alignment-freeze.yaml').unlink(missing_ok=True)
    test_context_builder._write_matching_seal(root, document)
    sha = 'sha256:' + hashlib.sha256((root / 'impact.yaml').read_bytes()).hexdigest()
    retirement = {'test': 'test_old.py', 'reason_code': 'REPLACED_DECLARED_COVERAGE', 'replacement_tests': ['test_new.py']}
    value = proposal(recommendation='local')
    value['constraints'] = ['PRESERVE_OBLIGATIONS', 'NO_EXECUTION', 'NO_RELEASE']
    value['scope'] = ['.harness/impact.yaml', '.harness/requirements.yaml', '.harness/test-scope-audit.yaml', '.harness/test-scope-seal.yaml']
    value['options'][0]['test_scope_authorization'] = {
        'version': 1, 'task_id': 'TASK-028', 'operation': 'RETIRE', 'expected_impact_hash': sha,
        'contract_hash': alignment.contract_hash(alignment.load_alignment(root)), 'original_source': None,
        'retirements': [retirement], 'bindings': [{'owner': 'REQ-001', 'case': 'TC-001', 'before': ['test_old.py'], 'after': ['test_new.py']}],
        'plan_refs': []}
    created = decision.propose(root, value)
    accepted = decision.accept(root, created['id'], option=selected,
                               source='accepted_recommendation' if selected == 'local' else 'user_override')
    return {'version': 1, 'task_id': 'TASK-028', 'expected_impact_hash': sha,
            'retirements': [{**retirement, 'decision_ref': accepted['id']}],
            'bindings': [{'owner': 'REQ-001', 'case': 'TC-001', 'tests': ['test_new.py']}]}


def test_atomic_apply_preserves_statement_status_and_unrelated_sources(harness):
    request = prepare(harness)
    before = tree_bytes(harness)
    result = target().apply_reconciliation(harness, request)
    assert result['context_regeneration_required'] is True
    assert result['task_id'] == 'TASK-028'
    assert scope_codes(harness) == set()
    assert yaml.safe_load((harness / 'impact.yaml').read_text())['impact']['required_tests'] == ['test_new.py']
    req = yaml.safe_load((harness / 'requirements.yaml').read_text())['requirements'][0]
    assert req['statement'] == 'Current behavior' and req['priority'] == 'must' and req['status'] == 'pending'
    assert not req.get('evidence')
    assert req['test_plan']['cases'][0]['tests'] == ['test_new.py']
    changed = {'impact.yaml', 'requirements.yaml', 'test-scope-audit.yaml', 'test-scope-seal.yaml'}
    for name, data in before.items():
        if name not in changed:
            assert (harness / name).read_bytes() == data


@pytest.mark.parametrize('attack', ['inactive', 'absent_replacement', 'empty_must', 'unknown_case', 'escape', 'stale', 'wrong_decision', 'unmapped'])
def test_apply_rejects_without_partial_publication(harness, attack):
    request = prepare(harness, selected='redis' if attack == 'inactive' else 'local')
    if attack == 'absent_replacement':
        (harness.parent / 'test_new.py').unlink()
    elif attack == 'empty_must':
        request['bindings'][0]['tests'] = []
    elif attack == 'unknown_case':
        request['bindings'][0]['case'] = 'TC-999'
    elif attack == 'escape':
        request['bindings'][0]['tests'] = ['../outside.py']
    elif attack == 'stale':
        request['expected_impact_hash'] = 'sha256:' + '0' * 64
    elif attack == 'wrong_decision':
        request['retirements'][0]['decision_ref'] = 'DEC-999'
    elif attack == 'unmapped':
        request['bindings'] = []
    before = tree_bytes(harness)
    with pytest.raises(ValueError):
        target().apply_reconciliation(harness, request)
    assert tree_bytes(harness) == before


def test_apply_rebind_only_uses_unique_selected_grant_and_preserves_impact_bytes(harness):
    request = prepare(harness)
    path = harness / 'decisions/DEC-001.yaml'
    value = yaml.safe_load(path.read_text())
    value['options'][0]['test_scope_authorization']['operation'] = 'REBIND'
    value['options'][0]['test_scope_authorization']['retirements'] = []
    write_yaml(path, value)
    decision.reindex(harness)
    request['retirements'] = []
    unrelated = decision.propose(harness, proposal(topic='unrelated cache', recommendation='local'))
    decision.accept(harness, unrelated['id'], option='local', source='accepted_recommendation')
    before = (harness / 'impact.yaml').read_bytes()
    target().apply_reconciliation(harness, request)
    assert (harness / 'impact.yaml').read_bytes() == before
    assert scope_codes(harness) == set()


def test_apply_updates_explicit_plan_surfaces_without_marking_complete(harness):
    request = prepare(harness)
    write_yaml(harness / 'plan.yaml', {'version': 1, 'items': [{'id': 'P-1', 'intent': 'Retain coverage',
               'requirement_refs': ['REQ-001'], 'test_case_refs': ['REQ-001/TC-001'], 'surfaces': ['test_old.py']}]})
    path = harness / 'decisions/DEC-001.yaml'
    value = yaml.safe_load(path.read_text())
    value['scope'].append('.harness/plan.yaml')
    value['options'][0]['test_scope_authorization']['plan_refs'] = ['P-1']
    write_yaml(path, value)
    decision.reindex(harness)
    target().apply_reconciliation(harness, request)
    plan = yaml.safe_load((harness / 'plan.yaml').read_text())
    assert plan['items'][0]['surfaces'] == ['test_new.py']
    assert plan['items'][0]['intent'] == 'Retain coverage'
    assert 'status' not in plan['items'][0]
    assert scope_codes(harness) == set()


def test_publication_entry_race_preserves_operator_bytes(harness, monkeypatch):
    request = prepare(harness)
    real = transaction.publish
    operator = b'impact: {changed: [], required_tests: [operator.py]}\n'
    before = tree_bytes(harness)
    def edit_before_publish(*args, **kwargs):
        (harness / 'impact.yaml').write_bytes(operator)
        return real(*args, **kwargs)
    monkeypatch.setattr(transaction, 'publish', edit_before_publish)
    with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED: expected source changed'):
        target().apply_reconciliation(harness, request)
    assert (harness / 'impact.yaml').read_bytes() == operator
    for name, data in before.items():
        if name != 'impact.yaml':
            assert (harness / name).read_bytes() == data


def test_authorized_dry_run_matches_apply_and_writes_zero_bytes(harness):
    request = prepare(harness)
    before = tree_bytes(harness)
    report = target().plan_reconciliation(harness, request)
    assert report['status'] == 'VALIDATED', report['diagnostics']
    assert report['execution_counts'] == {'tests': 0, 'business': 0, 'environment': 0}
    assert tree_bytes(harness) == before
    assert report['binding_changes'] == [{'owner': 'REQ-001', 'case': 'TC-001', 'before': ['test_old.py'], 'after': ['test_new.py']}]
    target().apply_reconciliation(harness, request)
    assert scope_codes(harness) == set()


@pytest.mark.parametrize('attack', ['constraint', 'contract', 'plan', 'seal'])
def test_dry_run_and_apply_reject_authority_drift_without_writes(harness, attack):
    request = prepare(harness)
    if attack == 'constraint':
        path = harness / 'decisions/DEC-001.yaml'
        value = yaml.safe_load(path.read_text())
        value['constraints'] = ['ambiguous permission']
        write_yaml(path, value)
        decision.reindex(harness)
    elif attack == 'contract':
        value = yaml.safe_load((harness / 'alignment.yaml').read_text())
        value['goal'] = 'Changed scope'
        write_yaml(harness / 'alignment.yaml', value)
    elif attack == 'plan':
        write_yaml(harness / 'plan.yaml', {'version': 1, 'items': [{'id': 'P-9', 'intent': 'Unapproved plan reference', 'requirement_refs': ['REQ-001']}]})
    else:
        value = yaml.safe_load((harness / 'alignment-freeze.yaml').read_text())
        value['contract_hash'] = 'sha256:' + '0' * 64
        write_yaml(harness / 'alignment-freeze.yaml', value)
    before = tree_bytes(harness)
    try:
        report = target().plan_reconciliation(harness, request)
    except ValueError:
        pass
    else:
        assert report['status'] == 'BLOCKED'
    with pytest.raises(ValueError):
        target().apply_reconciliation(harness, request)
    assert tree_bytes(harness) == before


def test_apply_death_recovers_bundle_after_disposable_staging_cleanup(harness):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from harness.telemetry_lock import telemetry_lock
    from harness.transaction_recovery import recover_pending_publications

    request = prepare(harness)
    before = tree_bytes(harness)
    script = '''
import json, os, yaml
from pathlib import Path
from harness import publication_fs
from harness.test_scope import apply_reconciliation
root = Path('.harness').absolute()
original = publication_fs.exchange
def die(*args):
    result = original(*args)
    if args[1] == 'requirements.yaml':
        held, named = os.fstat(args[0]), root.stat()
        if (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino):
            (root.parent / 'native-crash-marker.json').write_text(json.dumps({
                'native': True, 'pending': bool(list((root / '.transactions').glob('*.json'))),
            }))
            os._exit(87)
    return result
publication_fs.exchange = die
apply_reconciliation(root, yaml.safe_load(os.environ['PROPOSAL']))
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                                 'PROPOSAL': yaml.safe_dump(request)}, capture_output=True, text=True, check=False, timeout=40)
    assert result.returncode == 87, result.stderr
    import json

    assert json.loads((harness.parent / 'native-crash-marker.json').read_text()) == {'native': True, 'pending': True}
    transaction.cleanup_stale_staging(harness)
    with telemetry_lock(harness):
        recover_pending_publications(harness)
    assert_restored_with_retained_inputs(harness, before)
    assert scope_codes(harness) == set()


def test_cli_apply_uses_same_authority_and_reports_no_proof_status(harness):
    from test_scope_joint import cli

    request = prepare(harness)
    path = harness.parent / 'apply.yaml'
    path.write_text(yaml.safe_dump(request))
    result = cli(harness, 'impact', 'reconcile', '--file', str(path))
    assert result.returncode == 0, result.stderr
    report = yaml.safe_load(result.stdout)
    assert report['audit_refs'] and report['context_regeneration_required'] is True
    assert 'verified' not in report and 'evidence' not in report
    assert scope_codes(harness) == set()


def test_apply_publication_fault_restores_entire_bundle(harness, monkeypatch):
    request = prepare(harness)
    before = tree_bytes(harness)
    real = transaction.publish
    def fail(*args, **kwargs):
        def broken():
            raise OSError('apply fault')
        kwargs['after_publish'] = broken
        return real(*args, **kwargs)
    monkeypatch.setattr(transaction, 'publish', fail)
    with pytest.raises(OSError, match='apply fault'):
        target().apply_reconciliation(harness, request)
    assert_restored_with_retained_inputs(harness, before)


def assert_restored_with_retained_inputs(root, before):
    """Every prior byte remains; only private recovery/input additions allowed."""
    from pathlib import Path

    after = tree_bytes(root)
    assert all(after.get(name) == content for name, content in before.items())
    assert all(Path(name).parts[0] in {'.staging', '.transactions', '.publication-retained'}
               for name in after.keys() - before.keys())
    assert not list((root / '.transactions').glob('*.json'))

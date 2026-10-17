"""Reconcile begins read-only; neither dry-run nor DEC id alone grants retirement."""

import hashlib
import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml
from test_context_builder import write_yaml
from test_evidence_plan import declarations, tree_bytes

from harness.context.model import ContextBuildError

harness = test_context_builder.harness
REPO = Path(__file__).resolve().parents[1]


def reconciler():
    assert importlib.util.find_spec('harness.test_scope'), 'reconciliation planner missing'
    return importlib.import_module('harness.test_scope')


def proposal(root):
    return {'version': 1, 'task_id': 'TASK-028',
            'expected_impact_hash': 'sha256:' + hashlib.sha256((root / 'impact.yaml').read_bytes()).hexdigest(),
            'retirements': [], 'bindings': []}


def test_empty_dry_run_does_not_initialize_missing_task_scope(harness):
    task_path = harness / 'current-task.yaml'
    task = yaml.safe_load(task_path.read_text())
    task.pop('scope')
    write_yaml(task_path, task)
    before = tree_bytes(harness)
    report = reconciler().plan_reconciliation(harness, proposal(harness))
    assert report['dry_run'] is True and report['execution_authority'] is False
    assert report['execution_counts'] == {'tests': 0, 'business': 0, 'environment': 0}
    assert tree_bytes(harness) == before


@pytest.mark.parametrize('change', ['wrong_task', 'stale_hash', 'unknown_field', 'escape'])
def test_dry_run_invalid_inputs_fail_closed_without_changes(harness, change):
    value = proposal(harness)
    if change == 'wrong_task':
        value['task_id'] = 'TASK-999'
    elif change == 'stale_hash':
        value['expected_impact_hash'] = 'sha256:' + '0' * 64
    elif change == 'unknown_field':
        value['verified'] = True
    else:
        value['bindings'] = [{'owner': 'REQ-001', 'case': 'TC-001', 'tests': ['../outside.py']}]
    before = tree_bytes(harness)
    with pytest.raises(ContextBuildError):
        reconciler().plan_reconciliation(harness, value)
    assert tree_bytes(harness) == before


def test_dry_run_rebinding_is_advisory_and_preserves_status_and_evidence(harness):
    (harness.parent / 'test_old.py').write_text('def test_ok():\n    pass\n')
    (harness.parent / 'test_new.py').write_text('def test_ok():\n    pass\n')
    declarations(harness, ['test_old.py'])
    value = proposal(harness)
    value['bindings'] = [{'owner': 'REQ-001', 'case': 'TC-001', 'tests': ['test_new.py::test_ok']}]
    before = tree_bytes(harness)
    report = reconciler().plan_reconciliation(harness, value)
    assert {'owner': 'REQ-001', 'case': 'TC-001', 'before': ['test_old.py'], 'after': ['test_new.py::test_ok']} in report['binding_changes']
    assert tree_bytes(harness) == before
    requirement = yaml.safe_load((harness / 'requirements.yaml').read_text())['requirements'][0]
    assert requirement['status'] == 'pending'
    assert not requirement.get('evidence')


def test_must_case_cannot_be_emptied_by_dry_run(harness):
    (harness.parent / 'test_old.py').write_text('def test_ok():\n    pass\n')
    declarations(harness, ['test_old.py'])
    value = proposal(harness)
    value['bindings'] = [{'owner': 'REQ-001', 'case': 'TC-001', 'tests': []}]
    report = reconciler().plan_reconciliation(harness, value)
    assert any(d['code'] == 'TEST_SCOPE_RETIREMENT_UNAUTHORIZED' for d in report['diagnostics'])


def test_retirement_never_granted_by_decision_id_string(harness):
    from test_test_scope import initialize_test_origin

    initialize_test_origin(harness, ['test_old.py'])
    declarations(harness, ['test_old.py'])
    value = proposal(harness)
    value['retirements'] = [{'test': 'test_old.py', 'reason_code': 'ACCEPTED_SCOPE_RESET',
                             'decision_ref': 'DEC-001', 'replacement_tests': []}]
    before = tree_bytes(harness)
    report = reconciler().plan_reconciliation(harness, value)
    assert any(d['code'] == 'TEST_SCOPE_RETIREMENT_UNAUTHORIZED' for d in report['diagnostics'])
    assert tree_bytes(harness) == before


def test_reconcile_dry_run_cli_does_not_write_metadata(harness, tmp_path):
    value = proposal(harness)
    source = tmp_path.parent / f'{tmp_path.name}-proposal.yaml'
    source.write_text(yaml.safe_dump(value))
    before = tree_bytes(harness)
    result = subprocess.run([sys.executable, '-m', 'harness.cli', 'impact', 'reconcile', '--file', str(source), '--dry-run'],
                            cwd=harness.parent, env={**os.environ, 'PYTHONPATH': str(REPO / 'src')},
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    assert yaml.safe_load(result.stdout)['dry_run'] is True
    assert tree_bytes(harness) == before


def test_empty_apply_is_idempotent_after_scope_gate_joint_activation(harness, tmp_path):
    source = tmp_path.parent / f'{tmp_path.name}-apply.yaml'
    source.write_text(yaml.safe_dump(proposal(harness)))
    before = tree_bytes(harness)
    result = subprocess.run([sys.executable, '-m', 'harness.cli', 'impact', 'reconcile', '--file', str(source)],
                            cwd=harness.parent, env={**os.environ, 'PYTHONPATH': str(REPO / 'src')},
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    report = yaml.safe_load(result.stdout)
    assert report['updated_hashes'] == {} and report['audit_refs'] == []
    assert report['context_regeneration_required'] is False
    assert tree_bytes(harness) == before

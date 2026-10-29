"""EF-T09: diagnostics inspect declared targets, never execute verification."""

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
from evidence_factory import write_evidence
from test_context_builder import (
    enable_plan_reconciliation,
    write_plan_artifacts,
    write_yaml,
)

from harness import git_query
from harness.context.model import ContextBuildError

harness = test_context_builder.harness
REPO = Path(__file__).resolve().parents[1]


def planner():
    assert importlib.util.find_spec('harness.evidence_plan'), 'read-only evidence planner missing'
    return importlib.import_module('harness.evidence_plan')


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def declarations(root, tests):
    write_yaml(root / 'impact.yaml', {'impact': {'changed': [], 'required_tests': tests}})
    write_yaml(root / 'requirements.yaml', {'requirements': [{
        'id': 'REQ-001', 'statement': 'Current behavior', 'priority': 'must', 'status': 'pending',
        'test_plan': {'strategies': ['unit'], 'cases': [{
            'id': 'TC-001', 'type': 'happy_path', 'strategy': 'unit',
            'description': 'declared coverage', 'tests': tests,
        }]},
    }]})


def test_64_declared_targets_18_missing_link_owners_and_plan_without_execution(harness, monkeypatch):
    # Historical diagnostic fixture; never certify current declared set as origin.
    from test_test_scope import SCOPE_FILES

    for name in SCOPE_FILES:
        (harness / name).unlink()
    enable_plan_reconciliation(harness)
    targets = [f'tests/test_{i:02}.py' for i in range(64)]
    directory = harness.parent / 'tests'
    directory.mkdir()
    for target in targets[:46]:
        (harness.parent / target).write_text('def test_ok():\n    pass\n')
    declarations(harness, targets)
    plan, execution = write_plan_artifacts(harness)
    plan['items'][0].update(requirement_refs=['REQ-001'], test_case_refs=['REQ-001/TC-001'])
    from harness.plan_reconciliation import plan_fingerprint
    execution['plan']['fingerprint'] = plan_fingerprint(plan)
    write_yaml(harness / 'plan.yaml', plan)
    write_yaml(harness / 'plan-execution.yaml', execution)
    before = tree_bytes(harness)
    original_run = git_query.subprocess.run
    queries = []
    def read_only_git(command, *args, **kwargs):
        assert isinstance(command, list) and command[0] == 'git', 'diagnostic executed non-Git command'
        assert not kwargs.get('shell')
        queries.append(command)
        return original_run(command, *args, **kwargs)
    monkeypatch.setattr(git_query.subprocess, 'run', read_only_git)
    report = planner().plan_evidence(harness)
    missing = [d for d in report['diagnostics'] if d['code'] == 'MISSING_DECLARED_TEST']
    assert {d['test'] for d in missing} == set(targets[46:])
    assert len(missing) == 18
    assert all({'owner': 'REQ-001', 'case': 'TC-001', 'plan_items': ['P-1']} in d['references'] for d in missing)
    assert report['execution_plan']['tests'] == targets[:46]
    assert report['execution_counts'] == {'tests': 0, 'business': 0, 'environment': 0}
    assert queries
    assert report['advisory'] is True and report['execution_authority'] is False
    assert any(d['code'] == 'PLAN_ITEM_UNRECONCILED' and d['plan_item'] == 'P-1' for d in report['diagnostics'])
    assert tree_bytes(harness) == before


def test_missing_selector_and_unbound_case_are_not_imported_or_executed(harness):
    target = harness.parent / 'test_declared.py'
    target.write_text("raise RuntimeError('must not import')\ndef test_exists():\n    pass\n")
    declarations(harness, ['test_declared.py::test_absent'])
    document = __import__('yaml').safe_load((harness / 'requirements.yaml').read_text())
    document['requirements'][0]['test_plan']['cases'].append({
        'id': 'TC-002', 'type': 'negative', 'strategy': 'unit', 'description': 'unbound', 'tests': [],
    })
    write_yaml(harness / 'requirements.yaml', document)
    report = planner().plan_evidence(harness)
    assert any(d['code'] == 'MISSING_DECLARED_TEST' and d['test'] == 'test_declared.py::test_absent' for d in report['diagnostics'])
    assert any(d['code'] == 'UNBOUND_TEST_CASE' and d['case'] == 'TC-002' for d in report['diagnostics'])
    assert not report['execution_plan']['tests']
    assert report['environment']['prerequisites'] == 'NOT_VERIFIED'
    assert report['environment']['shared_resource_policy'] == 'SERIAL_UNLESS_DECLARED_ISOLATION'


def test_minimum_fresh_coverage_uses_real_covered_tests_and_command(harness):
    for name in ('test_a.py', 'test_b.py'):
        (harness.parent / name).write_text('def test_ok():\n    pass\n')
    declarations(harness, ['test_a.py', 'test_a.py::test_ok', 'test_b.py'])
    path = write_evidence(harness.parent, harness, 'unit_test')
    record = json.loads(path.read_text())
    from evidence_factory import synthetic_execution
    record.update(command='pytest test_a.py', scope='related', covered_tests=['test_a.py'],
                  test_execution=synthetic_execution(['test_a.py::test_ok']))
    path.write_text(json.dumps(record))
    report = planner().plan_evidence(harness)
    assert report['execution_plan']['tests'] == ['test_b.py']
    assert not any(d['code'] == 'NO_FRESH_COVERAGE' and d.get('test', '').startswith('test_a.py') for d in report['diagnostics'])


@pytest.mark.parametrize('change,code', [('head', 'EVIDENCE_HEAD_MISMATCH'), ('workspace', 'EVIDENCE_WORKSPACE_STALE')])
def test_stale_proof_reasons_remain_distinct(harness, change, code):
    (harness.parent / 'test_a.py').write_text('def test_ok():\n    pass\n')
    declarations(harness, ['test_a.py'])
    path = write_evidence(harness.parent, harness, 'unit_test')
    record = json.loads(path.read_text())
    record.update(command='pytest test_a.py', covered_tests=['test_a.py'])
    if change == 'head':
        record['commit'] = '0' * 40
    else:
        record['workspace_fingerprint_after'] = 'sha256:' + '0' * 64
    path.write_text(json.dumps(record))
    report = planner().plan_evidence(harness)
    assert any(d['code'] == code for d in report['diagnostics'])
    assert report['execution_plan']['tests'] == ['test_a.py']


@pytest.mark.parametrize('attack', ['schema', 'missing_index', 'symlink'])
def test_invalid_sources_fail_closed_without_writes(harness, attack, tmp_path):
    if attack == 'schema':
        (harness / 'requirements.yaml').write_text('requirements: broken\n')
    elif attack == 'missing_index':
        from test_context_integrity import add_core_records
        add_core_records(harness)
        (harness / 'decisions/index.yaml').unlink()
    else:
        path = harness / 'requirements.yaml'
        data = path.read_bytes()
        path.unlink()
        outside = tmp_path.parent / f'{tmp_path.name}-private.yaml'
        outside.write_bytes(data)
        path.symlink_to(outside)
    before = tree_bytes(harness)
    with pytest.raises(ContextBuildError):
        planner().plan_evidence(harness)
    assert tree_bytes(harness) == before


@pytest.mark.parametrize('selector', ['test_ok[param]', 'test_outer::test_inner'])
def test_dynamic_or_function_nested_selectors_remain_unverified(harness, selector):
    (harness.parent / 'test_a.py').write_text('def test_ok():\n    pass\ndef test_outer():\n    def test_inner():\n        pass\n')
    declarations(harness, [f'test_a.py::{selector}'])
    report = planner().plan_evidence(harness)
    assert any(d['code'] == 'SELECTOR_UNVERIFIED' for d in report['diagnostics'])
    assert not report['execution_plan']['tests']


def test_historical_red_is_retained_but_never_fresh_green_coverage(harness):
    (harness.parent / 'test_a.py').write_text('def test_ok():\n    pass\n')
    declarations(harness, ['test_a.py'])
    path = write_evidence(harness.parent, harness, 'unit_test')
    record = json.loads(path.read_text())
    record.update(command='pytest test_a.py', scope='related', covered_tests=['test_a.py'], exit_code=1, phase='red')
    path.write_text(json.dumps(record))
    before = tree_bytes(harness)
    report = planner().plan_evidence(harness)
    assert report['execution_plan']['tests'] == ['test_a.py']
    assert tree_bytes(harness) == before


def test_diagnostic_detects_target_drift_after_static_inspection(harness, monkeypatch):
    target = harness.parent / 'test_a.py'
    target.write_text('def test_ok():\n    pass\n')
    declarations(harness, ['test_a.py::test_ok'])
    module = planner()
    original = module.inspect_declared_test
    def inspect_then_change(*args):
        result = original(*args)
        target.write_text('def test_replaced():\n    pass\n')
        return result
    monkeypatch.setattr(module, 'inspect_declared_test', inspect_then_change)
    before = tree_bytes(harness)
    with pytest.raises(ContextBuildError, match='CONTEXT_STALE'):
        module.plan_evidence(harness)
    assert tree_bytes(harness) == before


@pytest.mark.parametrize('journal_state', ['pending', 'unknown_member', 'symlink', 'not_directory'])
def test_read_only_diagnostic_does_not_recover_or_read_partial_publication(harness, journal_state, tmp_path):
    directory = harness / '.transactions'
    directory.rmdir()  # Initialization/binding leaves empty durable journal storage.
    if journal_state == 'symlink':
        outside = tmp_path.parent / f'{tmp_path.name}-journals'
        outside.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
    elif journal_state == 'not_directory':
        directory.write_text('unmanaged private bytes')
    else:
        directory.mkdir()
        (directory / ('pending.json' if journal_state == 'pending' else 'unknown.txt')).write_text('unmanaged journal bytes')
    before = tree_bytes(harness)
    with pytest.raises(ContextBuildError, match='TRANSACTION_RECOVERY_'):
        planner().plan_evidence(harness)
    assert tree_bytes(harness) == before


def test_journal_appearing_during_diagnosis_stops_without_recovery(harness, monkeypatch):
    (harness.parent / 'test_a.py').write_text('def test_ok():\n    pass\n')
    declarations(harness, ['test_a.py'])
    module = planner()
    original = module.inspect_declared_test
    def inspect_then_journal(*args):
        result = original(*args)
        (harness / '.transactions').mkdir(exist_ok=True)
        (harness / '.transactions/pending.json').write_text('unmanaged pending bytes')
        return result
    monkeypatch.setattr(module, 'inspect_declared_test', inspect_then_journal)
    before = tree_bytes(harness)
    with pytest.raises(ContextBuildError, match='TRANSACTION_RECOVERY_REQUIRED'):
        module.plan_evidence(harness)
    assert tree_bytes(harness) == {**before, '.transactions/pending.json': b'unmanaged pending bytes'}


def test_empty_optional_decision_index_is_not_initialized(harness):
    (harness / 'decisions/index.yaml').unlink()
    before = tree_bytes(harness)
    assert planner().plan_evidence(harness)['advisory'] is True
    assert tree_bytes(harness) == before


def test_preflight_opt_in_reports_version_two(harness):
    result = subprocess.run(
        [sys.executable, '-m', 'harness.cli', 'evidence', 'plan', '--preflight', '--json'],
        cwd=harness.parent, env={**os.environ, 'PYTHONPATH': str(REPO / 'src')},
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert result.returncode in {0, 1}, result.stderr
    report = json.loads(result.stdout)
    assert report['version'] == 2
    assert report['execution_authority'] is False


def test_evidence_plan_cli_outputs_json_without_legacy_execution(harness):
    before = tree_bytes(harness)
    result = subprocess.run([sys.executable, '-m', 'harness.cli', 'evidence', 'plan', '--json'],
                            cwd=harness.parent, env={**os.environ, 'PYTHONPATH': str(REPO / 'src')},
                            capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['execution_authority'] is False
    assert 'DEPRECATED' not in result.stderr
    assert tree_bytes(harness) == before

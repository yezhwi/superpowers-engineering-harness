"""V2 closed state reduction and one existing stable-source lifecycle."""
import importlib
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_context_builder as fixtures

from harness import evidence_plan, quality_gate
from harness.blockers import GateBlocker
from harness.context.model import ContextBuildError
from harness.execution_capture import supported_command

harness = fixtures.harness
REPO = Path(__file__).resolve().parents[1]


def api(monkeypatch):
    module = importlib.import_module('harness.preflight')
    monkeypatch.setattr(module, 'begin_tool_identity', lambda package: None)
    monkeypatch.setattr(module, 'finish_tool_identity', lambda snapshot: {
        'cli_identity': {'status': 'VERIFIED', 'verified_version': '0.3.2'},
        'schema_identity': {'status': 'VERIFIED'},
        'skills_identity': {'status': 'NOT_PROVIDED'}, 'diagnostics': [], 'errors': [],
    })
    return module


def request(module, root, **kwargs):
    return module.PreflightRequest(probe_cwd=root.parent, **kwargs)


@pytest.mark.parametrize('command', [
    'pytest tests/a.py', 'cd backend && python -m pytest tests/a.py',
    "sh -lc 'pytest tests/a.py'", 'kubectl exec pod -- pytest tests/a.py',
    'pytest -n2 tests/a.py', 'false; pytest tests/a.py', 'unknown-runner tests/a.py',
    "pytest 'unclosed", 'pytest $TARGET', 'pytest `false`',
])
def test_classification_uses_exact_collector_boolean(monkeypatch, command):
    module = api(monkeypatch)
    report = module.classify_commands((command, command))
    assert len(report['commands']) == 1
    assert report['commands'][0]['command'] == command
    expected = 'NATIVE_PROFILE_SUPPORTED' if supported_command(command) else 'MEASUREMENT_ONLY'
    assert report['commands'][0]['status'] == expected


@pytest.mark.parametrize('command', ['', '  ', None, {}])
def test_unknown_is_only_invalid_internal_input(monkeypatch, command):
    report = api(monkeypatch).classify_commands((command,))
    assert report['status'] == 'INVALID_REQUEST'
    assert report['commands'][0]['status'] == 'UNKNOWN'


def test_no_commands_and_exact_first_occurrence_order(monkeypatch):
    module = api(monkeypatch)
    assert module.classify_commands(()) == {'status': 'NOT_REQUESTED', 'commands': []}
    report = module.classify_commands(('pytest a.py', 'pytest b.py', 'pytest a.py'))
    assert [item['command'] for item in report['commands']] == ['pytest a.py', 'pytest b.py']


@pytest.mark.parametrize('payload,expected', [
    (None,2), ((),2), (['SCOPE_DRIFT_API'],2), (('UNKNOWN',),2),
    (('SCOPE_DRIFT_API', None),2), (('SCOPE_DRIFT_API',),1),
    (('CONTRACT_CHANGED','SCOPE_DRIFT_API','SCOPE_DRIFT_PERMISSION','SCOPE_DRIFT_PERSISTENCE'),1),
])
def test_only_valid_payload_recovers_drift_not_exception_prose(harness, monkeypatch, payload, expected):
    module = api(monkeypatch)
    @contextmanager
    def failed(root):
        raise ContextBuildError('CONTEXT_SCHEMA_INVALID', 'alignment sealed mismatch: SCOPE_DRIFT_API', drift_codes=payload)
        yield
    monkeypatch.setattr(module, 'diagnostic_sources', failed)
    report = module.run_preflight(harness, request(module, harness))
    assert report['exit_code'] == expected
    assert report['integrity']['status'] == ('BLOCKED' if expected == 1 else 'INVALID')
    assert report['task_id'] is None
    assert report['product']['execution_plan'] is None
    if expected == 2:
        assert report['repair_requirements'] == []
    else:
        assert {item['operation'] for item in report['repair_requirements']} == {'ALIGN_REVISE'}


@pytest.mark.parametrize('code,expected', [('TRANSACTION_RECOVERY_REQUIRED',1),
 ('TRANSACTION_RECOVERY_BLOCKED',1), ('CONTEXT_STALE',1), ('CONTEXT_REFERENCE_BROKEN',2)])
def test_source_exception_mapping_is_not_gate_allowlist(harness, monkeypatch, code, expected):
    module = api(monkeypatch)
    @contextmanager
    def failed(root):
        raise ContextBuildError(code, 'detail')
        yield
    monkeypatch.setattr(module, 'diagnostic_sources', failed)
    report = module.run_preflight(harness, request(module, harness))
    assert report['exit_code'] == expected
    assert [d['code'] for d in report['integrity']['diagnostics']] == [code]


@pytest.mark.parametrize('code,integrity', [
 ('CONTRACT_CHANGED','BLOCKED'), ('SCOPE_DRIFT_API','BLOCKED'),
 ('SCOPE_DRIFT_PERMISSION','BLOCKED'), ('SCOPE_DRIFT_PERSISTENCE','BLOCKED'),
 ('TEST_SCOPE_AUDIT_INVALID','BLOCKED'), ('TEST_SCOPE_RETIREMENT_UNAUDITED','BLOCKED'),
 ('TEST_SCOPE_RETIREMENT_UNAUTHORIZED','BLOCKED'), ('EVIDENCE_WORKSPACE_STALE','VALID'),
 ('REQUIRED_VERIFICATION_MISSING','VALID'), ('COMPLEXITY_REVIEW_MISSING','VALID'),
])
def test_only_seven_gate_codes_invalidate_sources(harness, monkeypatch, code, integrity):
    module = api(monkeypatch)
    assessment = SimpleNamespace(status='BLOCKED', blockers=(GateBlocker(code, 'harness', code),),
                                 architecture_assessment=None)
    monkeypatch.setattr(quality_gate, 'assess_gate', lambda *a, **k: assessment)
    report = module.run_preflight(harness, request(module, harness))
    assert report['integrity']['status'] == integrity
    assert report['exit_code'] == 1
    if integrity == 'VALID':
        assert report['product']['status'] == 'GAPS'
        assert report['task_id'] == 'TASK-028'
    else:
        assert report['product']['status'] == 'NOT_EVALUATED'
        assert report['task_id'] is None


def test_pending_journal_skips_tests_but_not_explicit_probe(harness, monkeypatch):
    module = api(monkeypatch)
    (harness / '.transactions/pending.json').write_text('unresolved')
    monkeypatch.setattr(evidence_plan, 'inspect_declared_test', lambda *a: pytest.fail('traversed product'))
    calls = []
    monkeypatch.setattr(module, 'probe_launcher', lambda *a, **k: calls.append(k) or
                        {'status': 'SPAWN_ERROR', 'spawn_attempts': 1})
    report = module.run_preflight(harness, request(module, harness, probe_launcher=Path('/missing/harness')))
    assert len(calls) == 1
    assert report['exit_code'] == 1
    assert report['execution_counts'] == {'tests': 0, 'business': 0, 'environment': 1}
    assert report['product']['status'] == 'NOT_EVALUATED'


def test_final_freshness_discards_all_staged_unhashed_repairs(harness, monkeypatch):
    module = api(monkeypatch)
    assessment = SimpleNamespace(status='BLOCKED', blockers=(GateBlocker('TEST_SCOPE_AUDIT_INVALID', 'harness', 'audit'),),
                                 architecture_assessment=None)
    monkeypatch.setattr(quality_gate, 'assess_gate', lambda *a, **k: assessment)
    original = module.repair_requirements
    def hints(*args, **kwargs):
        result = original(*args, **kwargs)
        assert result and result[0]['operation'] == 'INSPECT_SCOPE_AUTHORITY'
        path = harness / 'impact.yaml'
        path.write_bytes(path.read_bytes() + b'\n')
        return result
    monkeypatch.setattr(module, 'repair_requirements', hints)
    report = module.run_preflight(harness, request(module, harness))
    assert report['exit_code'] == 1
    assert report['task_id'] is report['source_versions'] is None
    assert report['product'] == {'status': 'NOT_EVALUATED', 'diagnostics': [], 'execution_plan': None}
    assert report['repair_requirements'] == []
    assert [item['code'] for item in report['integrity']['diagnostics']] == ['CONTEXT_STALE']


def test_final_stale_code_cannot_be_overridden_by_drift_payload(harness, monkeypatch):
    module = api(monkeypatch)
    @contextmanager
    def failed(root):
        raise ContextBuildError('CONTEXT_STALE', 'stale', drift_codes=('SCOPE_DRIFT_API',))
        yield
    monkeypatch.setattr(module, 'diagnostic_sources', failed)
    report = module.run_preflight(harness, request(module, harness))
    assert report['repair_requirements'] == []
    assert [item['code'] for item in report['integrity']['diagnostics']] == ['CONTEXT_STALE']


def test_unexpected_tool_fault_is_json_error_without_exception_contents(harness, monkeypatch):
    module = api(monkeypatch)
    def broken(*args):
        raise RuntimeError('sensitive internal detail')
    monkeypatch.setattr(module, 'begin_tool_identity', broken)
    report = module.run_preflight(harness, request(module, harness))
    assert report['exit_code'] == 2
    assert report['tooling']['status'] == 'ERROR'
    assert 'sensitive internal detail' not in str(report)


def test_repair_outputs_are_closed_even_when_input_describes_operations(monkeypatch):
    module = api(monkeypatch)
    report = module.repair_requirements(('TEST_SCOPE_AUDIT_INVALID', 'RETIRE', 'REBIND', 'MIGRATE'),
                                       source=None, source_versions=None)
    assert len(report) == 1
    assert report[0]['operation'] == 'INSPECT_SCOPE_AUTHORITY'
    assert report[0]['authority'] == 'USER_INSPECTION_REQUIRED'
    assert report[0]['source_refs'] is report[0]['task_id'] is report[0]['scope'] is None
    assert report[0]['constraints'] == ['PRESERVE_OBLIGATIONS','PRESERVE_RISK','NO_EXECUTION','NO_RELEASE']


def test_planner_uses_callers_versions_dict_and_retains_v1(harness):
    target = harness.parent / 'test_declared.py'
    target.write_text('def test_ok():\n    pass\n')
    from test_evidence_plan import declarations
    declarations(harness, ['test_declared.py::test_ok'])
    with evidence_plan.diagnostic_sources(harness) as (source, before, versions):
        original_id = id(versions)
        report = evidence_plan._plan_from_sources(harness, source, before, versions)
        assert id(versions) == original_id
        assert versions['test_declared.py'].startswith('sha256:')
    assert report['version'] == 1
    assert report['execution_plan'] == {'scope': 'related', 'tests': ['test_declared.py::test_ok']}


def test_probe_preserves_source_failure_precedence_and_spawn_count(harness, monkeypatch):
    module = api(monkeypatch)
    (harness / 'requirements.yaml').write_text('broken: [' )
    monkeypatch.setattr(module, 'probe_launcher', lambda *a, **k: {'status':'SUCCEEDED','spawn_attempts':1})
    report = module.run_preflight(harness, request(module, harness, probe_launcher=Path('/explicit/harness')))
    assert report['exit_code'] == 2
    assert report['tooling']['launcher_probe']['status'] == 'SUCCEEDED'
    assert report['integrity']['status'] == 'INVALID'
    assert report['execution_counts']['environment'] == 1


def test_probe_source_mutation_invalidates_previously_trusted_product(harness, monkeypatch):
    module = api(monkeypatch)
    def probe(*args, **kwargs):
        path = harness / 'impact.yaml'
        path.write_bytes(path.read_bytes() + b'\n')
        return {'status': 'SUCCEEDED', 'spawn_attempts': 1}
    monkeypatch.setattr(module, 'probe_launcher', probe)
    report = module.run_preflight(harness, request(module, harness, probe_launcher=Path('/explicit/harness')))
    assert report['exit_code'] == 1
    assert report['integrity']['status'] == 'BLOCKED'
    assert [row['code'] for row in report['integrity']['diagnostics']] == ['CONTEXT_STALE']
    assert report['task_id'] is report['source_versions'] is None
    assert report['product'] == {'status': 'NOT_EVALUATED', 'diagnostics': [], 'execution_plan': None}
    assert report['repair_requirements'] == []
    assert report['tooling']['launcher_probe']['status'] == 'SUCCEEDED'


def test_schema_tool_failure_does_not_downgrade_product_source_error(harness, monkeypatch):
    module = api(monkeypatch)
    monkeypatch.setattr(module, 'finish_tool_identity', lambda snapshot: {
        'cli_identity': {'status': 'VERIFIED', 'verified_version': '0.3.2'},
        'schema_identity': {'status': 'INVALID'},
        'skills_identity': {'status': 'NOT_PROVIDED'}, 'diagnostics': [], 'errors': [],
    })
    (harness / 'requirements.yaml').write_text('requirements: malformed')
    report = module.run_preflight(harness, request(module, harness))
    assert report['exit_code'] == 2
    assert report['integrity']['status'] == 'INVALID'
    assert report['tooling']['status'] == 'BLOCKED'
    assert report['tooling']['schema_identity']['status'] == 'INVALID'


def test_standalone_reuses_existing_snapshot_and_gate_counts(harness, monkeypatch):
    from harness import workspace
    from harness.context import freshness
    module = api(monkeypatch)
    counts = {'snapshot': 0, 'gate': 0}
    original_snapshot, original_gate = workspace.snapshot, quality_gate.assess_gate
    def observed_snapshot(*args, **kwargs):
        counts['snapshot'] += 1
        return original_snapshot(*args, **kwargs)
    def observed_gate(*args, **kwargs):
        counts['gate'] += 1
        return original_gate(*args, **kwargs)
    monkeypatch.setattr(workspace, 'snapshot', observed_snapshot)
    monkeypatch.setattr(freshness, 'snapshot', observed_snapshot)
    monkeypatch.setattr(quality_gate, 'assess_gate', observed_gate)
    evidence_plan.plan_evidence(harness)
    baseline = counts.copy()
    counts.update(snapshot=0, gate=0)
    module.run_preflight(harness, request(module, harness))
    assert counts == baseline
    assert counts['gate'] == 1


def test_clear_report_keeps_optional_unknowns_nonblocking(harness, monkeypatch):
    module = api(monkeypatch)
    monkeypatch.setattr(quality_gate, 'assess_gate', lambda *a, **k:
                        SimpleNamespace(status='PASS', blockers=(), architecture_assessment=None))
    report = module.run_preflight(harness, request(module, harness))
    assert report['exit_code'] == 0
    assert report['outcome'] == 'CLEAR'
    assert report['tooling']['status'] == 'NOT_VERIFIED'
    assert report['product'] == {'status': 'NO_GAPS', 'diagnostics': [],
                                  'execution_plan': {'scope': 'related', 'tests': []}}
    assert report['execution_counts'] == {'tests': 0, 'business': 0, 'environment': 0}


def test_process_shared_lock_held_until_probe_and_final_freshness(harness, monkeypatch):
    module = api(monkeypatch)
    with tempfile.TemporaryDirectory(prefix='preflight-lock-') as external:
        attempted, acquired = Path(external)/'attempted', Path(external)/'acquired'
        children = []
        def probe(*args, **kwargs):
            code = ("from pathlib import Path; from harness.telemetry_lock import telemetry_lock; "
                    f"Path({str(attempted)!r}).touch()\n"
                    f"with telemetry_lock(Path({str(harness)!r})):\n Path({str(acquired)!r}).touch()\n")
            child = subprocess.Popen([sys.executable, '-c', code],
                        env={**os.environ, 'PYTHONPATH': str(REPO/'src')})
            children.append(child)
            until = time.monotonic()+5
            while not attempted.exists():
                assert child.poll() is None and time.monotonic()<until
                time.sleep(.01)
            time.sleep(.05)
            assert not acquired.exists()
            return {'status':'SUCCEEDED','spawn_attempts':1}
        monkeypatch.setattr(module, 'probe_launcher', probe)
        try:
            report = module.run_preflight(harness, request(module, harness, probe_launcher=Path('/explicit/harness')))
            assert report['integrity']['status'] == 'VALID'
            assert report['execution_counts']['environment'] == 1
            children[0].wait(timeout=5)
            assert acquired.exists()
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill(); child.wait(timeout=5)

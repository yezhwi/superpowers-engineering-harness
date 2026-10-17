"""Test-scope proposal planning. Publication requires audited Gate activation."""

from __future__ import annotations

from pathlib import Path

from jsonschema import ValidationError, validate

from ._scope_replay import (
    TestScopeError,
    _prepare_reconciliation,
    add_required_test,
    apply_reconciliation,
    assess_test_scope_retirements,
    bind_scope_identity,
    migrate_test_scope,
    new_scope_artifacts,
)
from .blockers import is_user_authority_blocker
from .context.model import ContextBuildError
from .evidence_plan import (
    case_records,
    diagnostic_sources,
    environment_report,
    inspect_declared_test,
    test_references,
)
from .schema_resources import read_schema

__all__ = ['add_required_test', 'apply_reconciliation', 'assess_test_scope_retirements', 'bind_scope_identity', 'migrate_test_scope', 'new_scope_artifacts', 'plan_reconciliation']


def validate_proposal(proposal: dict):
    try:
        validate(proposal, read_schema('impact-reconcile.schema.json'))
    except ValidationError as exc:
        raise ContextBuildError('CONTEXT_SCHEMA_INVALID', 'invalid impact reconciliation proposal') from exc


def plan_reconciliation(harness_dir: Path, proposal: dict) -> dict:
    validate_proposal(proposal)
    root = harness_dir.absolute()
    with diagnostic_sources(root) as (source, before, versions):
        if proposal['task_id'] != source.task['task']['id']:
            raise ContextBuildError('CONTEXT_POLICY_MISMATCH', 'proposal task mismatch')
        if proposal['expected_impact_hash'] != before['files'].get('impact.yaml'):
            raise ContextBuildError('CONTEXT_STALE', 'proposal impact source changed')
        diagnostics = []
        changes = []
        authorized_events = []
        seen = set()
        cases = {(owner['id'], case['id']): (owner, case) for _kind, owner, case in case_records(source)}
        for binding in proposal['bindings']:
            key = binding['owner'], binding['case']
            if key in seen or key not in cases:
                raise ContextBuildError('CONTEXT_SCHEMA_INVALID', 'duplicate or unknown binding owner/case')
            seen.add(key)
            owner, case = cases[key]
            for test in binding['tests']:
                problem = inspect_declared_test(root.parent, test, versions)
                if problem:
                    diagnostics.append({'code': 'MISSING_DECLARED_TEST', 'test': test, 'reason': problem})
            if (not binding['tests'] and case['strategy'] != 'manual'
                    and (owner.get('priority') == 'must' or owner.get('severity') in {'critical', 'major'})):
                diagnostics.append({'code': 'TEST_SCOPE_RETIREMENT_UNAUTHORIZED', 'owner': key[0], 'case': key[1],
                                    'reason': 'required obligation cannot lose its executable mapping'})
            changes.append({'owner': key[0], 'case': key[1], 'before': case.get('tests', []), 'after': binding['tests']})
        required = set((source.impact or {}).get('impact', {}).get('required_tests', []))
        refs = test_references(source)
        retired = set()
        for retirement in proposal['retirements']:
            test = retirement['test']
            # Containment is mandatory even for a target being retired/missing.
            inspect_declared_test(root.parent, test, versions)
            if test in retired:
                raise ContextBuildError('CONTEXT_SCHEMA_INVALID', 'duplicate retirement')
            retired.add(test)
            for replacement in retirement['replacement_tests']:
                problem = inspect_declared_test(root.parent, replacement, versions)
                if problem:
                    diagnostics.append({'code': 'MISSING_DECLARED_TEST', 'test': replacement, 'reason': problem})
        if proposal['bindings'] or proposal['retirements']:
            try:
                _payloads, targets, authorized_changes, authorized_events, _audit, _seal = _prepare_reconciliation(root, proposal)
                versions.update(targets)
                changes = authorized_changes
                if authorized_events:
                    required = set(authorized_events[0]['before_tests'])
            except TestScopeError as exc:
                diagnostics.append({'code': exc.code})
        for retirement in proposal['retirements']:
            if retirement['test'] not in required:
                diagnostics.append({'code': 'TEST_SCOPE_RETIREMENT_UNAUTHORIZED', 'test': retirement['test'],
                                    'references': refs.get(retirement['test'], []), 'reason': 'target is not in declared required scope'})
        for blocker in source.gate.blockers:
            if is_user_authority_blocker(blocker.code) and not (
                    blocker.code == 'TEST_SCOPE_RETIREMENT_UNAUDITED' and authorized_events
                    and authorized_events[0]['operation'] == 'RETIRE'):
                diagnostics.append({'code': blocker.code})
        report = {
            'version': 1, 'task_id': source.task['task']['id'], 'dry_run': True,
            'advisory': True, 'execution_authority': False,
            'status': 'BLOCKED' if diagnostics else 'VALIDATED',
            'source_versions': before, 'diagnostics': diagnostics, 'binding_changes': changes,
            'retirements': proposal['retirements'],
            'execution_counts': {'tests': 0, 'business': 0, 'environment': 0},
            'environment': environment_report(source),
            'apply_enabled': True,
        }
    return report

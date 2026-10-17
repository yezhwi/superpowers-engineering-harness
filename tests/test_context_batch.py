"""EF-T01–07/14: batch keeps semantics while full source work stays bounded."""

import copy
import json

import pytest
import test_context_builder
import yaml
from evidence_factory import write_evidence
from test_context_automatic import outside_finding
from test_context_builder import write_yaml

from harness import transaction
from harness.context import escalation
from harness.context.model import ContextBuildError
from harness.context.store import generate_context
from harness.context.telemetry import ContextTelemetry

harness = test_context_builder.harness


def findings(root, count):
    if not count:
        return
    outside_finding(root)
    template = yaml.safe_load((root / 'findings/FND-001.yaml').read_text())
    for index in range(2, count + 1):
        record = copy.deepcopy(template)
        record['id'] = f'FND-{index:03}'
        record['location']['file'] = f'src/outside-{index}.py'
        write_yaml(root / f'findings/FND-{index:03}.yaml', record)


@pytest.mark.parametrize('count', [0, 1, 10, 50, 100])
def test_batch_entry_bounds(harness, count):
    findings(harness, count)
    timer = ContextTelemetry()
    with timer.activate():
        document = generate_context(harness)
    report = timer.finish('SUCCESS', True)
    counters = report['counters']
    assert counters['full_context_builds'] <= 2
    assert counters['source_loads'] <= 3
    assert counters['gate_assessments'] <= 3
    assert counters['full_context_builds'] == (2 if count else 1)
    assert counters['source_loads'] == (3 if count else 2)
    assert counters['gate_assessments'] == (3 if count else 2)
    assert len(document['expansions']) == count
    assert counters['expansion_events_written'] == count
    if not count:
        assert not (harness / 'context/expansions.yaml').exists()


def reference_apply(root, context, **kwargs):
    from harness.context.integrity import build_context
    initial = escalation.automatic_candidates(context)
    for candidate in initial:
        fields = ('trigger', 'object_id', 'source_hash')
        if any(all(event.get(key) == candidate[key] for key in fields) for event in context['expansions']):
            continue
        escalation._record_expansion(root, candidate['trigger'], candidate['reason'], automatic=candidate, mode=context['mode'])
        context = build_context(root, mode=context['mode'])
    return context


def test_stable_reference_parity_and_source_hash_override(harness, monkeypatch):
    findings(harness, 3)
    original_task = (harness / 'current-task.yaml').read_bytes()
    reference = None
    with monkeypatch.context() as patch:
        patch.setattr(escalation, 'apply_automatic_expansions', reference_apply)
        reference = generate_context(harness)
    (harness / 'current-task.yaml').write_bytes(original_task)
    (harness / 'context/expansions.yaml').unlink()
    batch = generate_context(harness)
    for key in ('control', 'working', 'omitted', 'references', 'policy', 'expansions'):
        assert batch[key] == reference[key]
    assert batch['expansions'][0]['source_hash'] == escalation.automatic_candidates(reference)[0]['source_hash']
    assert [e['from'] for e in batch['expansions']] == ['LOCAL', 'BOUNDED', 'EXPANDED']
    assert [e['to'] for e in batch['expansions']] == ['BOUNDED', 'EXPANDED', 'EXPANDED']
    assert yaml.safe_load((harness / 'current-task.yaml').read_text())['budget']['context_expansions'] == 3
    assert generate_context(harness)['expansions'] == batch['expansions']


def test_batch_publication_entry_cas_preserves_operator_task_edit(harness, monkeypatch):
    findings(harness, 1)
    original = transaction.publish
    owned = []
    def edit_then_publish(root, staged, **kwargs):
        if not (staged / 'context/expansions.yaml').exists():
            return original(root, staged, **kwargs)
        task = yaml.safe_load((root / 'current-task.yaml').read_text())
        task['task']['title'] = 'operator owned task title'
        write_yaml(root / 'current-task.yaml', task)
        owned.append((root / 'current-task.yaml').read_bytes())
        return original(root, staged, **kwargs)
    monkeypatch.setattr(transaction, 'publish', edit_then_publish)
    with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        generate_context(harness)
    assert (harness / 'current-task.yaml').read_bytes() == owned[0]
    assert not (harness / 'context/expansions.yaml').exists()


def disappearing_candidates(root):
    findings(root, 1)
    path = root / 'current-task.yaml'
    task = yaml.safe_load(path.read_text())
    task['scope']['owned_paths'] = ['tests']
    write_yaml(path, task)
    from harness import decision
    decision_path = root / 'decisions/DEC-001.yaml'
    record = yaml.safe_load(decision_path.read_text())
    record['scope'] = ['tests']
    write_yaml(decision_path, record)
    decision.reindex(root)
    write_yaml(root / 'impact.yaml', {'impact': {'changed': [], 'required_tests': ['tests']}})
    write_yaml(root / 'requirements.yaml', {'requirements': [{
        'id': 'REQ-001', 'statement': 'Optional broad tests', 'priority': 'should', 'status': 'pending',
        'test_plan': {'strategies': ['unit'], 'cases': [{
            'id': 'TC-001', 'type': 'negative', 'strategy': 'unit', 'description': 'failure',
            'tests': ['tests'],
        }]},
    }]})
    for index in range(2):
        evidence = write_evidence(root.parent, root, 'unit_test', exit_code=1, name=f'historical-red-{index}.json')
        record = json.loads(evidence.read_text())
        record['covered_tests'] = ['tests']
        record['phase'] = 'red'
        evidence.write_text(json.dumps(record))


def test_candidate_loss_commits_prefix_and_stops(harness, monkeypatch):
    disappearing_candidates(harness)
    original_task = (harness / 'current-task.yaml').read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(escalation, 'apply_automatic_expansions', reference_apply)
        with pytest.raises(ContextBuildError, match='CONTEXT_STALE'):
            generate_context(harness)
    reference_prefix = yaml.safe_load((harness / 'context/expansions.yaml').read_text())['expansions']
    assert len(reference_prefix) == 1
    (harness / 'current-task.yaml').write_bytes(original_task)
    (harness / 'context/expansions.yaml').unlink()
    batch = generate_context(harness)
    assert batch['expansions'] == reference_prefix
    assert len(batch['control']['evidence']) == 2  # EF-T05: same-task historical RED retained
    assert all(e['exit_code'] == 1 for e in batch['control']['evidence'])
    assert all(e['trigger'] != 'FINDING_OUTSIDE_SCOPE' for e in batch['expansions'])
    retried = generate_context(harness)
    assert len(retried['expansions']) == 2
    assert retried['expansions'][0] == reference_prefix[0]
    assert retried['expansions'][1]['trigger'] == 'FINDING_OUTSIDE_SCOPE'


def test_prepublication_drift_writes_zero_new_events(harness, monkeypatch):
    findings(harness, 3)
    original = transaction.stage
    original_task = (harness / 'current-task.yaml').read_bytes()
    def stage_then_edit(*args, **kwargs):
        staged = original(*args, **kwargs)
        if any(a.relative_path == 'context/expansions.yaml' for a in args[1]):
            with (harness / 'requirements.yaml').open('a') as stream:
                stream.write('\n# user change\n')
        return staged
    monkeypatch.setattr(transaction, 'stage', stage_then_edit)
    with pytest.raises(ContextBuildError, match='CONTEXT_STALE'):
        generate_context(harness)
    assert (harness / 'current-task.yaml').read_bytes() == original_task
    assert not (harness / 'context/expansions.yaml').exists()
    assert '# user change' in (harness / 'requirements.yaml').read_text()


def test_publisher_rejects_bytes_not_matching_captured_versions(harness, monkeypatch):
    from harness import source_access
    from harness.context.integrity import build_context
    findings(harness, 1)
    context = build_context(harness, mode='compact')
    original = source_access.read_regular_bytes_beneath
    before = (harness / 'current-task.yaml').read_bytes()
    altered = yaml.safe_load(before)
    altered['scope']['owned_paths'] = ['src/false-snapshot.py']
    def transient_bytes(path, root):
        if path == harness / 'current-task.yaml':
            return yaml.safe_dump(altered, sort_keys=False).encode()
        return original(path, root)
    monkeypatch.setattr(source_access, 'read_regular_bytes_beneath', transient_bytes)
    candidate = escalation.automatic_candidates(context)[0]
    event = escalation._make_expansion_event(yaml.safe_load(before), context,
                                             candidate['trigger'], candidate['reason'], candidate)
    with pytest.raises(ContextBuildError, match='CONTEXT_STALE'):
        escalation._publish_expansion_events(harness, context['generated_from'], [event])
    assert (harness / 'current-task.yaml').read_bytes() == before
    assert not (harness / 'context/expansions.yaml').exists()


def test_planning_error_after_accepted_event_writes_zero_prefix(harness, monkeypatch):
    findings(harness, 3)
    original = escalation.automatic_candidates
    calls = [0]
    def broken(context):
        calls[0] += 1
        if calls[0] == 3:
            raise ContextBuildError('CONTEXT_SCHEMA_INVALID', 'invalid candidate')
        return original(context)
    monkeypatch.setattr(escalation, 'automatic_candidates', broken)
    before = (harness / 'current-task.yaml').read_bytes()
    with pytest.raises(ContextBuildError, match='CONTEXT_SCHEMA_INVALID'):
        generate_context(harness)
    assert (harness / 'current-task.yaml').read_bytes() == before
    assert not (harness / 'context/expansions.yaml').exists()

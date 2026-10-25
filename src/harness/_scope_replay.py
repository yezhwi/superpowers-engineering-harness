"""Canonical scope consistency mechanism. No initialization in assessment."""

from __future__ import annotations

import copy
import datetime
import hashlib
from pathlib import Path, PureWindowsPath

import yaml
from jsonschema import ValidationError, validate

from . import source_access, transaction
from .blockers import GateBlocker, is_user_authority_blocker
from .context.freshness import capture, contained_path, digest
from .context.integrity import _load_stable
from .context.model import ContextBuildError
from .evidence_plan import inspect_declared_test
from .schema_resources import read_schema
from .telemetry_lock import telemetry_lock

SCOPE_FILES = ('test-scope-baseline.yaml', 'test-scope-audit.yaml', 'test-scope-seal.yaml')
INVALID = 'TEST_SCOPE_AUDIT_INVALID'
UNAUDITED = 'TEST_SCOPE_RETIREMENT_UNAUDITED'
UNAUTHORIZED = 'TEST_SCOPE_RETIREMENT_UNAUTHORIZED'


class TestScopeError(ValueError):
    """Stable safe scope failure; never carries source contents."""

    def __init__(self, code=INVALID):
        self.code = code
        super().__init__(code)


def raw_hash(content: bytes) -> str:
    return 'sha256:' + hashlib.sha256(content).hexdigest()


def encode(document: dict) -> bytes:
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode()


def _read(root: Path, name: str, schema: str | None = None):
    data = source_access.read_regular_bytes_beneath(root / name, root.parent)
    document = yaml.safe_load(data)
    if schema:
        validate(document, read_schema(schema))
    if not isinstance(document, dict):
        raise TestScopeError()
    return document, data


def _tests(root: Path, tests: list[str]) -> set[str]:
    if not isinstance(tests, list) or any(not isinstance(test, str) or not test for test in tests):
        raise TestScopeError()
    if len(set(tests)) != len(tests):
        raise TestScopeError()
    for test in tests:
        filename, *nodes = test.split('::')
        if PureWindowsPath(filename).drive or '\\' in filename or any(c in filename for c in '*?[') or any(not node for node in nodes):
            raise TestScopeError()
        path = contained_path(root.parent, filename)
        for member in (path, *path.parents):
            if member == root.parent.parent:
                break
            if member.is_symlink():
                raise TestScopeError()
    return set(tests)


def _seal(task_id, baseline_bytes, audit_bytes, head, decisions=None):
    return {'version': 1, 'task_id': task_id, 'baseline_hash': raw_hash(baseline_bytes),
            'audit_hash': raw_hash(audit_bytes), 'audit_head': head, 'origin_decisions': decisions or {}}


def new_scope_artifacts(harness_dir: Path) -> list[transaction.StagedArtifact]:
    """Creation-only builder. Caller publishes with newly created task, never legacy repair."""
    root = harness_dir.absolute()
    try:
        if any(source_access.exists(root / name) for name in SCOPE_FILES):
            raise TestScopeError()
        task, task_bytes = _read(root, 'current-task.yaml', 'task.schema.json')
        impact, impact_bytes = _read(root, 'impact.yaml')
        gate, _ = _read(root, 'gate.yaml', 'gate.schema.json')
        if task['state'] != 'CREATED':
            raise TestScopeError()
        tests = impact['impact']['required_tests']
        _tests(root, tests)
        task_id = task['task']['id']
        baseline = {'version': 1, 'task_id': task_id, 'required_tests': tests,
                    'origin': {'kind': 'new_task', 'timestamp': datetime.datetime.now(datetime.UTC).isoformat(),
                               'task_created_at': task['timestamps']['created_at'], 'decision_ref': None,
                               'source_path': None, 'original_tests_hash': digest(tests)},
                    'source_hashes': {'impact.yaml': raw_hash(impact_bytes), 'current-task.yaml': raw_hash(task_bytes)}}
        audit = {'version': 1, 'task_id': task_id, 'entries': []}
        baseline_bytes, audit_bytes = encode(baseline), encode(audit)
        seal = _seal(task_id, baseline_bytes, audit_bytes, raw_hash(baseline_bytes))
        gate['gate']['test_scope'] = {'minimum_reader': '0.3.2'}
        documents = dict(zip(SCOPE_FILES, (baseline, audit, seal), strict=True))
        documents['gate.yaml'] = gate
        for name, document in documents.items():
            validate(document, read_schema(name.removesuffix('.yaml') + '.schema.json'))
        return [transaction.StagedArtifact(name, encode(document)) for name, document in documents.items()]
    except (OSError, KeyError, TypeError, yaml.YAMLError, ValidationError, ContextBuildError) as exc:
        raise TestScopeError() from exc


def load_scope(harness_dir: Path):
    """Require current scope and mappings to match complete authorized replay."""
    root = harness_dir.absolute()
    try:
        sources, expected, bindings, retired, targets = _replay_scope(root)
        actual = _tests(root, sources[1]['impact']['required_tests'])
        if expected - actual:
            raise TestScopeError(UNAUDITED)
        if actual - expected:
            raise TestScopeError()
        if bindings or retired:
            _verify_current_mappings(root, expected, bindings, retired - expected, targets & expected)
        return sources
    except (OSError, KeyError, TypeError, yaml.YAMLError, ValidationError, ContextBuildError) as exc:
        raise TestScopeError() from exc


def _replay_scope(harness_dir: Path):
    """Validate immutable origin and every event; candidate callers must validate current projection."""
    root = harness_dir.absolute()
    try:
        task, _ = _read(root, 'current-task.yaml', 'task.schema.json')
        impact, _ = _read(root, 'impact.yaml')
        gate, _ = _read(root, 'gate.yaml', 'gate.schema.json')
        baseline, baseline_bytes = _read(root, SCOPE_FILES[0], 'test-scope-baseline.schema.json')
        audit, audit_bytes = _read(root, SCOPE_FILES[1], 'test-scope-audit.schema.json')
        seal, _ = _read(root, SCOPE_FILES[2], 'test-scope-seal.schema.json')
        task_id = task['task']['id']
        if not task_id or any(doc['task_id'] != task_id for doc in (baseline, audit, seal)):
            raise TestScopeError()
        if gate['gate'].get('test_scope') != {'minimum_reader': '0.3.2'}:
            raise TestScopeError()
        expected = _tests(root, baseline['required_tests'])
        origin = baseline['origin']
        if origin['original_tests_hash'] != digest(baseline['required_tests']):
            raise TestScopeError()
        if origin['task_created_at'] != task['timestamps']['created_at']:
            raise TestScopeError()
        historical = []
        if origin['kind'] == 'new_task':
            if (origin['decision_ref'] is not None or origin['source_path'] is not None
                    or seal['origin_decisions'] or origin.get('historical_sources')):
                raise TestScopeError(UNAUTHORIZED)
        else:
            historical = _verify_reconstructed_origin(root, task, baseline, seal)
        head = raw_hash(baseline_bytes)
        if seal['baseline_hash'] != head or seal['audit_hash'] != raw_hash(audit_bytes):
            raise TestScopeError()
        bindings = {}
        retired = set()
        targets = set()
        for sequence, event in enumerate(audit['entries'], 1):
            unsigned = {key: value for key, value in event.items() if key != 'hash'}
            if event['sequence'] != sequence or event['previous_hash'] != head or event['hash'] != digest(unsigned):
                raise TestScopeError()
            before, after = _tests(root, event['before_tests']), _tests(root, event['after_tests'])
            if before != expected:
                raise TestScopeError()
            if sequence <= len(historical):
                if any(event[key] != value for key, value in historical[sequence - 1].items()):
                    raise TestScopeError(UNAUTHORIZED)
            elif event['operation'] in {'RETIRE', 'REBIND'}:
                removed, replacements = _verify_scope_change(root, task, event, bindings)
                retired.update(removed)
                targets.update(replacements)
            else:
                if event['operation'] != 'ADD':
                    raise TestScopeError(UNAUTHORIZED)
                if (before - after or len(after - before) != 1 or event['decision_refs'] or event['affected_bindings']
                        or event['plan_refs'] or set(event['artifact_hashes']) != {'impact.yaml'}
                        or event['reason_code'] != 'DECLARED_TEST_ADDED'):
                    raise TestScopeError()
            expected, head = after, event['hash']
        if len(audit['entries']) < len(historical):
            raise TestScopeError()
        if seal['audit_head'] != head:
            raise TestScopeError()
        _tests(root, impact['impact']['required_tests'])  # Validate shape/containment, never bless current subset.
        return (task, impact, baseline, audit, seal), expected, bindings, retired, targets
    except (OSError, KeyError, TypeError, yaml.YAMLError, ValidationError, ContextBuildError) as exc:
        raise TestScopeError() from exc


def freeze_scope_facts(harness_dir: Path) -> dict | None:
    """Immutable origin only. Missing legacy origin stays absent, never blessed."""
    root = harness_dir.absolute()
    if not any(source_access.exists(root / name) for name in SCOPE_FILES):
        return None
    _task, _impact, _baseline, _audit, seal = load_scope(root)
    return {'baseline_hash': seal['baseline_hash'], 'origin_decisions': copy.deepcopy(seal['origin_decisions'])}


def assess_test_scope_retirements(harness_dir: Path) -> list[GateBlocker]:
    try:
        load_scope(harness_dir)
    except TestScopeError as exc:
        return [GateBlocker(exc.code, 'harness', exc.code, source='test-scope-audit.yaml')]
    return []


def _snapshot(root):
    snapshot = capture(root)
    snapshot['scope_sources'] = {
        name: raw_hash(source_access.read_regular_bytes_beneath(root / name, root.parent)) if source_access.exists(root / name) else None
        for name in SCOPE_FILES
    }
    return snapshot


def _genesis_snapshot(root):
    names = ('current-task.yaml', 'impact.yaml', 'gate.yaml', *SCOPE_FILES)
    return {'genesis_sources': {name: raw_hash(source_access.read_regular_bytes_beneath(root / name, root.parent))
                                for name in names}}


def _current_snapshot(root, before):
    return _genesis_snapshot(root) if 'genesis_sources' in before else _snapshot(root)


def _check_after(root, before, payloads, target_versions, removed_declared=()):
    after = _current_snapshot(root, before)
    if 'genesis_sources' in before:
        expected = copy.deepcopy(before)
        for name, content in payloads.items():
            expected['genesis_sources'][name] = raw_hash(content)
        if after != expected:
            raise ContextBuildError('CONTEXT_STALE', 'genesis sources changed during publication')
        return
    expected = copy.deepcopy(before)
    for group in ('files', 'scope_sources'):
        for name in expected[group]:
            if name in payloads:
                expected[group][name] = raw_hash(payloads[name])
    for name, content in payloads.items():
        reference = f'{root.name}/{name}'
        if reference in expected['declared_files']:
            expected['declared_files'][reference] = raw_hash(content)
    for name, version in target_versions.items():
        expected['declared_files'][name] = version
    expected['control_plane_hash'] = digest(expected['files'])
    for key, filename in (('requirements', 'requirements.yaml'), ('invariants', 'invariants.yaml'), ('impact', 'impact.yaml')):
        expected[f'{key}_hash'] = digest({filename: expected['files'][filename]})
    expected['plan_hash'] = expected['files'].get('plan.yaml')
    for name in removed_declared:
        if name not in after['declared_files']:
            expected['declared_files'].pop(name, None)
    if after != expected:
        raise ContextBuildError('CONTEXT_STALE', 'scope sources changed during publication')


def add_required_test(harness_dir: Path, test: str) -> None:
    root = harness_dir.absolute()
    with telemetry_lock(root):
        from .transaction_recovery import recover_pending_publications

        recover_pending_publications(root)
        before = _snapshot(root)
        _task, impact, _baseline, audit, seal = load_scope(root)
        source = _load_stable(root, {key: value for key, value in before.items() if key != 'scope_sources'})
        for blocker in source.gate.blockers:
            if is_user_authority_blocker(blocker.code):
                raise TestScopeError(blocker.code)
        tests = impact['impact']['required_tests']
        if test in tests:
            if _snapshot(root) != before:
                raise ContextBuildError('CONTEXT_STALE', 'scope sources changed')
            return
        versions = {}
        if inspect_declared_test(root.parent, test, versions):
            raise TestScopeError(UNAUTHORIZED)
        _tests(root, [test])
        original_impact = source_access.read_regular_bytes_beneath(root / 'impact.yaml', root.parent)
        updated = copy.deepcopy(impact)
        updated['impact']['required_tests'].append(test)
        impact_bytes = encode(updated)
        event = {'sequence': len(audit['entries']) + 1, 'previous_hash': seal['audit_head'],
                 'timestamp': datetime.datetime.now(datetime.UTC).isoformat(), 'operation': 'ADD',
                 'before_tests': sorted(tests), 'after_tests': sorted(updated['impact']['required_tests']),
                 'decision_refs': [], 'artifact_hashes': {'impact.yaml': {'before': raw_hash(original_impact), 'after': raw_hash(impact_bytes)}},
                 'reason_code': 'DECLARED_TEST_ADDED', 'affected_bindings': [], 'plan_refs': []}
        event['hash'] = digest(event)
        audit = copy.deepcopy(audit)
        audit['entries'].append(event)
        audit_bytes = encode(audit)
        seal = {**seal, 'audit_hash': raw_hash(audit_bytes), 'audit_head': event['hash']}
        payloads = {'impact.yaml': impact_bytes, SCOPE_FILES[1]: audit_bytes, SCOPE_FILES[2]: encode(seal)}
        _publish_payloads(root, before, payloads, versions)


def _publish_payloads(root, before, payloads, versions, *, removed_declared=(), validate_after=None):
    previous = {name: source_access.read_regular_bytes_beneath(root / name, root.parent)
                if source_access.exists(root / name) else None for name in payloads}
    artifacts = tuple(transaction.StagedArtifact(name, content) for name, content in payloads.items())
    staged = transaction.stage(root, artifacts)
    if _current_snapshot(root, before) != before:
        raise ContextBuildError('CONTEXT_STALE', 'scope sources changed before publication')

    def finalize():
        for _ in range(2):
            _check_after(root, before, payloads, versions, removed_declared)
            if validate_after is not None:
                validate_after()

    transaction.publish(root, staged, replace_paths=frozenset(payloads), durable=True,
                        expected_sources=previous, expected_artifacts=artifacts, after_publish=finalize)


def bind_scope_identity(harness_dir: Path, task_id: str) -> None:
    """Bind unassigned genesis once; never recreate scope from current subset."""
    import re

    if not re.fullmatch(r'TASK-[0-9]+', task_id):
        raise TestScopeError()
    root = harness_dir.absolute()
    with telemetry_lock(root):
        from .transaction_recovery import recover_pending_publications

        recover_pending_publications(root)
        before = _genesis_snapshot(root)
        try:
            task, task_bytes = _read(root, 'current-task.yaml', 'task.schema.json')
            from .task_identity import require_available

            require_available(root, task_id, task, migration=True)
            impact, impact_bytes = _read(root, 'impact.yaml')
            baseline, baseline_bytes = _read(root, SCOPE_FILES[0], 'test-scope-baseline.schema.json')
            audit, audit_bytes = _read(root, SCOPE_FILES[1], 'test-scope-audit.schema.json')
            seal, _ = _read(root, SCOPE_FILES[2], 'test-scope-seal.schema.json')
            gate, _ = _read(root, 'gate.yaml', 'gate.schema.json')
            if (task['state'] != 'CREATED' or task['task']['id'] is not None
                    or any(doc['task_id'] is not None for doc in (baseline, audit, seal))
                    or audit['entries'] or baseline['origin']['kind'] != 'new_task'
                    or baseline['origin']['decision_ref'] is not None or baseline['origin']['source_path'] is not None
                    or baseline['source_hashes']['current-task.yaml'] != raw_hash(task_bytes)
                    or baseline['source_hashes']['impact.yaml'] != raw_hash(impact_bytes)
                    or baseline['required_tests'] != impact['impact']['required_tests']
                    or baseline['origin']['original_tests_hash'] != digest(baseline['required_tests'])
                    or gate['gate'].get('test_scope') != {'minimum_reader': '0.3.2'}
                    or seal != _seal(None, baseline_bytes, audit_bytes, raw_hash(baseline_bytes))):
                raise TestScopeError()
            _tests(root, baseline['required_tests'])
            task['task']['id'] = task_id
            task_bytes = encode(task)
            baseline['task_id'] = task_id
            baseline['source_hashes']['genesis-task.yaml'] = baseline['source_hashes']['current-task.yaml']
            baseline['source_hashes']['current-task.yaml'] = raw_hash(task_bytes)
            audit['task_id'] = task_id
            baseline_bytes, audit_bytes = encode(baseline), encode(audit)
            seal = _seal(task_id, baseline_bytes, audit_bytes, raw_hash(baseline_bytes))
            payloads = dict(zip(SCOPE_FILES, (baseline_bytes, audit_bytes, encode(seal)), strict=True))
            payloads['current-task.yaml'] = task_bytes
            _publish_payloads(root, before, payloads, {})
        except (OSError, KeyError, TypeError, ValidationError, yaml.YAMLError) as exc:
            if isinstance(exc, OSError):
                raise  # Publication/recovery errors retain their safe transaction semantics.
            raise TestScopeError() from exc


def _selected_grant(root, task, decision_id):
    from . import alignment, decision

    try:
        records = decision.load_decision_index(root)
        record, data = _read(root, f'decisions/{decision_id}.yaml', 'decision.schema.json')
        indexed = next(item for item in records if item['id'] == decision_id)
        if (record['task_id'] != task['task']['id'] or record['status'] != 'ACCEPTED'
                or not record['accepted_at'] or record['superseded_by'] is not None
                or indexed['sha256'] != raw_hash(data)
                or any(indexed[key] != record[key] for key in ('task_id', 'status', 'supersedes', 'superseded_by'))):
            raise TestScopeError(UNAUTHORIZED)
        selected = record['selected']
        if not selected or selected['decided_by'] != 'user':
            raise TestScopeError(UNAUTHORIZED)
        option = next(item for item in record['options'] if item['id'] == selected['option'])
        grant = option.get('test_scope_authorization')
        contract = alignment.load_alignment(root)
        alignment.validate_freeze(contract)
        supported = {'PRESERVE_OBLIGATIONS', 'PRESERVE_RISK', 'NO_EXECUTION', 'NO_RELEASE'}
        if (not grant or grant['task_id'] != task['task']['id']
                or grant['contract_hash'] != alignment.contract_hash(contract)
                or not set(record['constraints']).issubset(supported)):
            raise TestScopeError(UNAUTHORIZED)
        return record, grant, raw_hash(data)
    except (OSError, KeyError, TypeError, StopIteration, ValidationError, yaml.YAMLError,
            decision.DecisionError, alignment.AlignmentError) as exc:
        raise TestScopeError(UNAUTHORIZED) from exc


def _scope_cases(root, documents=None):
    cases = {}
    for name, schema, key in (('requirements.yaml', 'requirement.schema.json', 'requirements'),
                              ('invariants.yaml', 'invariant.schema.json', 'invariants')):
        document = documents[name] if documents is not None else _read(root, name, schema)[0]
        for owner in document[key]:
            owner_cases = owner.get('test_plan', {}).get('cases', [])
            if (owner.get('priority') == 'must' or owner.get('severity') in {'critical', 'major'}) and not owner_cases:
                raise TestScopeError(UNAUTHORIZED)
            for case in owner_cases:
                identity = owner['id'], case['id']
                if identity in cases:
                    raise TestScopeError(UNAUTHORIZED)
                cases[identity] = (owner, case, name)
    return cases


def _scope_plan(root):
    if not source_access.exists(root / 'plan.yaml'):
        return []
    document, _ = _read(root, 'plan.yaml', 'plan.schema.json')
    if len({item['id'] for item in document['items']}) != len(document['items']):
        raise TestScopeError(UNAUTHORIZED)
    return document['items']


def _verify_scope_change(root, task, event, bindings):
    """Replay one exact selected grant; no execution or scope publication here."""
    if len(event['decision_refs']) != 1 or event['reason_code'] != 'AUTHORIZED_SCOPE_RECONCILIATION':
        raise TestScopeError(UNAUTHORIZED)
    reference = event['decision_refs'][0]
    record, grant, decision_hash = _selected_grant(root, task, reference['id'])
    if (reference['hash'] != decision_hash or reference['option'] != record['selected']['option']
            or grant['operation'] != event['operation'] or grant['original_source'] is not None
            or grant.get('historical_sources') or grant['expected_impact_hash'] != event['artifact_hashes']['impact.yaml']['before']
            or grant['bindings'] != event['affected_bindings'] or grant['plan_refs'] != event['plan_refs']):
        raise TestScopeError(UNAUTHORIZED)
    before, after = _tests(root, event['before_tests']), _tests(root, event['after_tests'])
    retirements = grant['retirements']
    removed = {item['test'] for item in retirements}
    replacements = {test for item in retirements for test in item['replacement_tests']}
    _tests(root, list(removed | replacements))
    if event['operation'] == 'RETIRE':
        if (not removed or len(removed) != len(retirements) or not removed <= before
                or removed & replacements or after != (before - removed) | replacements):
            raise TestScopeError(UNAUTHORIZED)
    elif (retirements or before != after or not event['affected_bindings']
          or event['artifact_hashes']['impact.yaml']['before'] != event['artifact_hashes']['impact.yaml']['after']):
        raise TestScopeError(UNAUTHORIZED)
    cases = _scope_cases(root)
    surfaces = {'impact.yaml', SCOPE_FILES[1], SCOPE_FILES[2]}
    required_artifacts = {'impact.yaml'}
    seen = set()
    plan = _scope_plan(root)
    plan_ids = {item['id'] for item in plan}
    if not set(event['plan_refs']) <= plan_ids:
        raise TestScopeError(UNAUTHORIZED)
    for binding in event['affected_bindings']:
        identity = binding['owner'], binding['case']
        if identity not in cases or identity in seen:
            raise TestScopeError(UNAUTHORIZED)
        seen.add(identity)
        owner, _case, filename = cases[identity]
        old, new = _tests(root, binding['before']), _tests(root, binding['after'])
        if (old == new or not old <= before or not new <= after or identity in bindings and bindings[identity] != old
                or not new and (owner.get('priority') == 'must' or owner.get('severity') in {'critical', 'major'})):
            raise TestScopeError(UNAUTHORIZED)
        bindings[identity] = new
        surfaces.add(filename)
        required_artifacts.add(filename)
        artifact = event['artifact_hashes'].get(filename)
        if not artifact or artifact['before'] == artifact['after']:
            raise TestScopeError(UNAUTHORIZED)
        linked = {item['id'] for item in plan if binding['owner'] in item.get('requirement_refs', [])
                  or binding['owner'] in item.get('invariant_refs', [])
                  or f"{binding['owner']}/{binding['case']}" in item.get('test_case_refs', [])}
        if not linked <= set(event['plan_refs']):
            raise TestScopeError(UNAUTHORIZED)
        replacements.update(new)
    if event['plan_refs']:
        surfaces.add('plan.yaml')
    if (not required_artifacts <= set(event['artifact_hashes'])
            or not set(event['artifact_hashes']) <= {'impact.yaml', 'requirements.yaml', 'invariants.yaml', 'plan.yaml'}
            or not {f'{root.name}/{name}' for name in surfaces | set(event['artifact_hashes'])} <= set(record['scope'])):
        raise TestScopeError(UNAUTHORIZED)
    return removed, replacements


def _verify_current_mappings(root, expected, bindings, retired, targets, *, cases=None, plan=None):
    cases = _scope_cases(root) if cases is None else cases
    for identity, tests in bindings.items():
        if identity not in cases or _tests(root, cases[identity][1].get('tests', [])) != tests:
            raise TestScopeError(UNAUTHORIZED)
    for owner, case, _filename in cases.values():
        tests = _tests(root, case.get('tests', []))
        if any(test == old or test.startswith(old + '::') for test in tests for old in retired):
            raise TestScopeError(UNAUTHORIZED)
        if (owner.get('priority') == 'must' or owner.get('severity') in {'critical', 'major'}) and case['strategy'] != 'manual':
            if not tests or not tests <= expected:
                raise TestScopeError(UNAUTHORIZED)
            targets.update(tests)
    for item in (_scope_plan(root) if plan is None else plan):
        if any(test == old or test.startswith(old + '::') for test in item.get('surfaces', []) for old in retired):
            raise TestScopeError(UNAUTHORIZED)
    for test in targets:
        if inspect_declared_test(root.parent, test, {}):
            raise TestScopeError(UNAUTHORIZED)  # Static existence/selector only; never evidence or business equivalence.


def _original_manifest(root, descriptor):
    try:
        path = contained_path(root.parent, descriptor['path'])
        data = source_access.read_regular_bytes_beneath(path, root.parent)
        document = yaml.safe_load(data)
        tests = document['impact']['required_tests']
        _tests(root, tests)
        if raw_hash(data) != descriptor['hash'] or digest(tests) != descriptor['tests_hash']:
            raise TestScopeError(UNAUTHORIZED)
        return tests
    except (OSError, KeyError, TypeError, yaml.YAMLError, ContextBuildError) as exc:
        raise TestScopeError(UNAUTHORIZED) from exc


def _migration_grant(root, task, decision_id, descriptor, impact_hash, historical_sources=()):
    record, grant, decision_hash = _selected_grant(root, task, decision_id)
    surfaces = ({f'.harness/{name}' for name in (*SCOPE_FILES, 'gate.yaml', 'impact.yaml')}
                | {descriptor['path']} | {item['path'] for item in historical_sources})
    if (grant['operation'] != 'MIGRATE' or grant['original_source'] != descriptor
            or grant.get('historical_sources', []) != list(historical_sources)
            or grant['expected_impact_hash'] != impact_hash or grant['retirements'] or grant['bindings']
            or grant['plan_refs'] or not surfaces.issubset(set(record['scope']))):
        raise TestScopeError(UNAUTHORIZED)
    return record, decision_hash


def _historical_steps(root, original_source, descriptors, record, decision_hash, impact_hash):
    """Selected MIGRATE grants approve exact immutable, strictly increasing snapshots."""
    tests = _original_manifest(root, original_source)
    seen = {contained_path(root.parent, original_source['path'])}
    live = {root / name for name in (*SCOPE_FILES, 'impact.yaml', 'gate.yaml', 'current-task.yaml')}
    if seen & live:
        raise TestScopeError(UNAUTHORIZED)
    steps = []
    for descriptor in descriptors:
        path = contained_path(root.parent, descriptor['path'])
        if path in seen or path in live:
            raise TestScopeError(UNAUTHORIZED)
        seen.add(path)
        after = _original_manifest(root, descriptor)
        if not set(tests) < set(after):
            raise TestScopeError(UNAUTHORIZED)  # No retirement, duplicate snapshot or reordering grant.
        steps.append({'operation': 'HISTORICAL_ADD', 'before_tests': sorted(tests), 'after_tests': sorted(after),
                      'decision_refs': [{'id': record['id'], 'option': record['selected']['option'], 'hash': decision_hash}],
                      'artifact_hashes': {'impact.yaml': {'before': impact_hash, 'after': impact_hash},
                                          descriptor['path']: {'before': descriptor['hash'], 'after': descriptor['hash']}},
                      'reason_code': 'AUTHORIZED_PREFEATURE_ADDITIONS', 'affected_bindings': [], 'plan_refs': []})
        tests = after
    return steps


def _verify_reconstructed_origin(root, task, baseline, seal):
    origin = baseline['origin']
    descriptor = {'path': origin['source_path'], 'hash': baseline['source_hashes'][origin['source_path']],
                  'tests_hash': origin['original_tests_hash']}
    history = origin.get('historical_sources', [])
    record, decision_hash = _migration_grant(root, task, origin['decision_ref'], descriptor,
                                           baseline['source_hashes']['impact.yaml'], history)
    if (seal['origin_decisions'] != {origin['decision_ref']: decision_hash}
            or _original_manifest(root, descriptor) != baseline['required_tests']
            or any(baseline['source_hashes'].get(item['path']) != item['hash'] for item in history)):
        raise TestScopeError(UNAUTHORIZED)
    return _historical_steps(root, descriptor, history, record, decision_hash, baseline['source_hashes']['impact.yaml'])


def _prepare_reconciliation(root, proposal):
    """Prepare exact selected scope grant and projected mappings without writes."""
    try:
        validate(proposal, read_schema('impact-reconcile.schema.json'))
    except ValidationError as exc:
        raise TestScopeError(UNAUTHORIZED) from exc
    sources, expected, prior_bindings, prior_retired, prior_targets = _replay_scope(root)
    task, impact, _baseline, audit, seal = sources
    impact_raw = source_access.read_regular_bytes_beneath(root / 'impact.yaml', root.parent)
    if task['task']['id'] != proposal['task_id'] or raw_hash(impact_raw) != proposal['expected_impact_hash']:
        raise TestScopeError(UNAUTHORIZED)
    if not proposal['bindings'] and not proposal['retirements']:
        load_scope(root)  # An empty proposal cannot acknowledge any discrepancy.
        return {}, {}, [], [], audit, seal
    refs = {item['decision_ref'] for item in proposal['retirements']}
    if len(refs) > 1:
        raise TestScopeError(UNAUTHORIZED)  # No implicit union of grants.
    if not refs:
        from .decision import load_decision_index
        matches = []
        for meta in load_decision_index(root):
            if meta['task_id'] != task['task']['id'] or meta['status'] != 'ACCEPTED':
                continue
            candidate, _data = _read(root, f"decisions/{meta['id']}.yaml", 'decision.schema.json')
            selected = candidate.get('selected') or {}
            option = next((option for option in candidate['options'] if option['id'] == selected.get('option')), {})
            if option.get('test_scope_authorization', {}).get('operation') != 'REBIND':
                continue  # Unrelated accepted selections confer no scope authority.
            record, grant, _hash = _selected_grant(root, task, meta['id'])
            if grant['operation'] == 'REBIND' and grant['expected_impact_hash'] == proposal['expected_impact_hash']:
                matches.append(record['id'])
        if len(matches) != 1:
            raise TestScopeError(UNAUTHORIZED)
        refs = set(matches)
    record, grant, decision_hash = _selected_grant(root, task, next(iter(refs)))
    retirements = [{key: value for key, value in item.items() if key != 'decision_ref'} for item in proposal['retirements']]
    if grant['retirements'] != retirements:
        raise TestScopeError(UNAUTHORIZED)
    removed = {item['test'] for item in retirements}
    replacements = {test for item in retirements for test in item['replacement_tests']}
    if len(removed) != len(retirements):
        raise TestScopeError(UNAUTHORIZED)
    current = impact['impact']['required_tests']
    updated = copy.deepcopy(impact)
    updated['impact']['required_tests'] = [test for test in current if test not in removed]
    for test in sorted(replacements):
        if test not in updated['impact']['required_tests']:
            updated['impact']['required_tests'].append(test)
    documents = {name: _read(root, name, schema)[0] for name, schema in
                 (('requirements.yaml', 'requirement.schema.json'), ('invariants.yaml', 'invariant.schema.json'))}
    cases = _scope_cases(root, documents)
    changes, changed_names, seen = [], set(), set()
    for binding in proposal['bindings']:
        identity = binding['owner'], binding['case']
        if identity not in cases or identity in seen:
            raise TestScopeError(UNAUTHORIZED)
        seen.add(identity)
        _owner, case, filename = cases[identity]
        changes.append({'owner': identity[0], 'case': identity[1], 'before': list(case.get('tests', [])), 'after': binding['tests']})
        case['tests'] = list(binding['tests'])
        changed_names.add(filename)
    payloads = {name: encode(documents[name]) for name in changed_names}
    payloads['impact.yaml'] = encode(updated) if removed else impact_raw
    plan = _scope_plan(root)
    changed_plan = set()
    for item in plan:
        surfaces = item.get('surfaces', [])
        if removed & set(surfaces):
            rewritten = []
            for surface in surfaces:
                values = next((entry['replacement_tests'] for entry in retirements if entry['test'] == surface), [surface])
                for value in values:
                    if value not in rewritten:
                        rewritten.append(value)
            item['surfaces'] = rewritten
            changed_plan.add(item['id'])
    if not changed_plan <= set(grant['plan_refs']):
        raise TestScopeError(UNAUTHORIZED)
    if changed_plan:
        payloads['plan.yaml'] = encode({'version': 1, 'items': plan})
    event = {'sequence': len(audit['entries']) + 1, 'previous_hash': seal['audit_head'],
             'timestamp': datetime.datetime.now(datetime.UTC).isoformat(), 'operation': 'RETIRE' if removed else 'REBIND',
             'before_tests': sorted(expected), 'after_tests': sorted(updated['impact']['required_tests']),
             'decision_refs': [{'id': record['id'], 'option': record['selected']['option'], 'hash': decision_hash}],
             'artifact_hashes': {name: {'before': raw_hash(source_access.read_regular_bytes_beneath(root / name, root.parent)),
                                      'after': raw_hash(content)} for name, content in payloads.items()},
             'reason_code': 'AUTHORIZED_SCOPE_RECONCILIATION', 'affected_bindings': changes, 'plan_refs': grant['plan_refs']}
    binding_map = copy.deepcopy(prior_bindings)
    removed, new_targets = _verify_scope_change(root, task, event, binding_map)
    projected = set(event['after_tests'])
    targets = (prior_targets | new_targets) & projected
    _verify_current_mappings(root, projected, binding_map, (prior_retired | removed) - projected, targets,
                             cases=cases, plan=plan)
    versions = {}
    for test in targets:
        if inspect_declared_test(root.parent, test, versions):
            raise TestScopeError(UNAUTHORIZED)
    event['hash'] = digest(event)
    audit = copy.deepcopy(audit)
    audit['entries'].append(event)
    audit_bytes = encode(audit)
    payloads[SCOPE_FILES[1]] = audit_bytes
    payloads[SCOPE_FILES[2]] = encode({**seal, 'audit_hash': raw_hash(audit_bytes), 'audit_head': event['hash']})
    return payloads, versions, changes, [event], audit, seal


def apply_reconciliation(harness_dir: Path, proposal: dict) -> dict:
    root = harness_dir.absolute()
    with telemetry_lock(root):
        from .transaction_recovery import recover_pending_publications
        recover_pending_publications(root)
        before = _snapshot(root)
        payloads, versions, _changes, events, _audit, _seal_doc = _prepare_reconciliation(root, proposal)
        source = _load_stable(root, {key: value for key, value in before.items() if key != 'scope_sources'})
        for blocker in source.gate.blockers:
            if is_user_authority_blocker(blocker.code) and not (
                    blocker.code == UNAUDITED and events and events[0]['operation'] == 'RETIRE'):
                raise TestScopeError(blocker.code)
        removed = {item['test'].split('::', 1)[0] for item in proposal['retirements']}
        if payloads:
            _publish_payloads(root, before, payloads, versions, removed_declared=removed, validate_after=lambda: load_scope(root))
        elif _snapshot(root) != before:
            raise ContextBuildError('CONTEXT_STALE', 'reconciliation sources changed')
        return {'task_id': proposal['task_id'], 'updated_hashes': {name: raw_hash(data) for name, data in payloads.items()},
                'audit_refs': [event['hash'] for event in events], 'context_regeneration_required': bool(payloads)}


def migrate_test_scope(harness_dir: Path, proposal: dict) -> dict:
    """Explicit selected original-set approval. Never retires reduced paths."""
    try:
        validate(proposal, read_schema('test-scope-migration.schema.json'))
    except ValidationError as exc:
        raise TestScopeError(UNAUTHORIZED) from exc
    root = harness_dir.absolute()
    with telemetry_lock(root):
        from .transaction_recovery import recover_pending_publications

        recover_pending_publications(root)
        before = _snapshot(root)
        task, task_bytes = _read(root, 'current-task.yaml', 'task.schema.json')
        impact, impact_bytes = _read(root, 'impact.yaml')
        if task['task']['id'] != proposal['task_id'] or raw_hash(impact_bytes) != proposal['expected_impact_hash']:
            raise TestScopeError(UNAUTHORIZED)
        if any(source_access.exists(root / name) for name in SCOPE_FILES):
            raise TestScopeError()  # No erase/rewrite of existing provenance chain.
        original = _original_manifest(root, proposal['original_source'])
        _tests(root, impact['impact']['required_tests'])
        history = proposal.get('historical_sources', [])
        record, decision_hash = _migration_grant(root, task, proposal['decision_ref'], proposal['original_source'],
                                               raw_hash(impact_bytes), history)
        historical = _historical_steps(root, proposal['original_source'], history, record, decision_hash, raw_hash(impact_bytes))
        proven = historical[-1]['after_tests'] if historical else original
        if set(impact['impact']['required_tests']) - set(proven):
            raise TestScopeError(UNAUTHORIZED)  # Current extras cannot self-certify historical provenance.
        source = _load_stable(root, {key: value for key, value in before.items() if key != 'scope_sources'})
        for blocker in source.gate.blockers:
            if is_user_authority_blocker(blocker.code) and blocker.code != INVALID:
                raise TestScopeError(blocker.code)
        baseline = {'version': 1, 'task_id': task['task']['id'], 'required_tests': original,
                    'origin': {'kind': 'authorized_reconstruction', 'timestamp': datetime.datetime.now(datetime.UTC).isoformat(),
                               'task_created_at': task['timestamps']['created_at'], 'decision_ref': proposal['decision_ref'],
                               'source_path': proposal['original_source']['path'], 'original_tests_hash': digest(original)},
                    'source_hashes': {'impact.yaml': raw_hash(impact_bytes), 'current-task.yaml': raw_hash(task_bytes),
                                      proposal['original_source']['path']: proposal['original_source']['hash']}}
        if history:
            baseline['origin']['historical_sources'] = copy.deepcopy(history)
            baseline['source_hashes'].update({item['path']: item['hash'] for item in history})
        baseline_bytes = encode(baseline)
        audit = {'version': 1, 'task_id': task['task']['id'], 'entries': []}
        head = raw_hash(baseline_bytes)
        for sequence, step in enumerate(historical, 1):
            event = {**step, 'sequence': sequence, 'previous_hash': head,
                     'timestamp': datetime.datetime.now(datetime.UTC).isoformat()}
            event['hash'] = digest(event)
            audit['entries'].append(event)
            head = event['hash']
        audit_bytes = encode(audit)
        seal = _seal(task['task']['id'], baseline_bytes, audit_bytes, head, {proposal['decision_ref']: decision_hash})
        gate, _ = _read(root, 'gate.yaml', 'gate.schema.json')
        gate['gate']['test_scope'] = {'minimum_reader': '0.3.2'}
        payloads = dict(zip(SCOPE_FILES, (baseline_bytes, audit_bytes, encode(seal)), strict=True))
        payloads['gate.yaml'] = encode(gate)
        _publish_payloads(root, before, payloads, {})
        blockers = assess_test_scope_retirements(root)
        return {'task_id': task['task']['id'], 'status': 'BLOCKED' if blockers else 'VALIDATED',
                'diagnostics': [{'code': item.code} for item in blockers], 'context_regeneration_required': True}

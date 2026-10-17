"""Scope mechanism proofs. Joint Gate/add activation follows mechanism acceptance."""

import hashlib
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder
import yaml
from test_context_builder import enable_plan_reconciliation, set_profile, write_yaml

from harness import publication_fs, quality_gate, transaction
from harness.context.builder import build_control_core
from harness.context.source import FileContextSource
from harness.telemetry_lock import telemetry_lock

harness = test_context_builder.harness
SCOPE_FILES = ('test-scope-baseline.yaml', 'test-scope-audit.yaml', 'test-scope-seal.yaml')


def scope_module():
    module = importlib.import_module('harness.test_scope')
    assert hasattr(module, 'assess_test_scope_retirements'), 'scope replay assessor missing'
    return module


def scope_codes(root):
    return {item.code for item in scope_module().assess_test_scope_retirements(root)}


def tree_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def file_identities(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_dev, p.stat().st_ino)
            for p in root.rglob('*') if p.is_file()}


def canonical_exchange_member(root, args):
    identity = root.stat()
    for fd, name in ((args[0], args[1]), (args[2], args[3])):
        held = os.fstat(fd)
        if (held.st_dev, held.st_ino) == (identity.st_dev, identity.st_ino):
            return name
    return None


def assert_restored_with_retention(root, before, identities):
    after = tree_bytes(root)
    assert {name: after.get(name) for name in before} == before
    after_identities = file_identities(root)
    assert {name: after_identities[name] for name in identities} == identities
    added = after.keys() - before.keys()
    assert added, 'abort/recovery must retain private publication objects'
    assert all(Path(name).parts[0] in {'.staging', '.publication-retained'} for name in added)
    assert not list((root / '.transactions').glob('*.json'))


def initialize_test_origin(root, tests, *, impact_document=None):
    """Explicit test-only creation, never production legacy self-initialization."""
    for test in tests:
        path = root.parent / test.split('::', 1)[0]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('def test_ok():\n    pass\n')
    write_yaml(root / 'impact.yaml', impact_document if impact_document is not None else
               {'impact': {'changed': [], 'required_tests': tests}})
    task = yaml.safe_load((root / 'current-task.yaml').read_text())
    created = {**task, 'state': 'CREATED'}
    write_yaml(root / 'current-task.yaml', created)
    for name in SCOPE_FILES:
        (root / name).unlink(missing_ok=True)
    artifacts = scope_module().new_scope_artifacts(root)
    staged = transaction.stage(root, artifacts)
    with telemetry_lock(root):
        transaction.publish(root, staged, replace_paths=frozenset(item.relative_path for item in artifacts), durable=True)
    write_yaml(root / 'current-task.yaml', task)


@pytest.mark.parametrize('level', ['Q1', 'Q2', 'Q3'])
def test_missing_origin_blocks_every_public_gate_profile_without_initialization(harness, level):
    if level == 'Q1':
        set_profile(harness, level)
    else:
        enable_plan_reconciliation(harness, level=level)
    for name in SCOPE_FILES:
        (harness / name).unlink(missing_ok=True)
    before = tree_bytes(harness)
    assessment = quality_gate.assess_gate(harness, allow_preflight=True)
    assert 'TEST_SCOPE_AUDIT_INVALID' in {item.code for item in assessment.blockers}
    assert tree_bytes(harness) == before


def test_missing_origin_projects_typed_control_core_blocker(harness):
    for name in SCOPE_FILES:
        (harness / name).unlink(missing_ok=True)
    source = FileContextSource(harness).load()
    core = build_control_core(source)
    assert 'TEST_SCOPE_AUDIT_INVALID' in {item['code'] for item in core['gate']['blocked_by']}


@pytest.mark.parametrize('tests', [[], ['test_a.py', 'test_b.py::test_ok']])
def test_creation_seals_actual_initial_required_tests(harness, tests):
    initialize_test_origin(harness, tests)
    baseline = yaml.safe_load((harness / SCOPE_FILES[0]).read_text())
    assert baseline['version'] == 1
    assert baseline['task_id'] == 'TASK-028'
    assert baseline['required_tests'] == tests
    assert baseline['origin']['kind'] == 'new_task'
    assert baseline['source_hashes']['impact.yaml'] == 'sha256:' + hashlib.sha256((harness / 'impact.yaml').read_bytes()).hexdigest()
    assert not scope_codes(harness)


def test_unaudited_hand_shrink_cannot_be_fresh_gate_fact(harness):
    initialize_test_origin(harness, ['test_a.py', 'test_b.py'])
    write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': ['test_a.py']}})
    before = tree_bytes(harness)
    assert 'TEST_SCOPE_RETIREMENT_UNAUDITED' in scope_codes(harness)
    assessment = quality_gate.assess_gate(harness, allow_preflight=True)
    assert 'TEST_SCOPE_RETIREMENT_UNAUDITED' in {item.code for item in assessment.blockers}
    assert tree_bytes(harness) == before


@pytest.mark.parametrize('attack', ['missing_audit', 'changed_baseline', 'invalid_audit', 'wrong_task'])
def test_scope_integrity_damage_fails_closed(harness, attack):
    initialize_test_origin(harness, ['test_a.py'])
    if attack == 'missing_audit':
        (harness / SCOPE_FILES[1]).unlink()
    elif attack == 'changed_baseline':
        baseline = yaml.safe_load((harness / SCOPE_FILES[0]).read_text())
        baseline['required_tests'] = []
        write_yaml(harness / SCOPE_FILES[0], baseline)
    elif attack == 'invalid_audit':
        (harness / SCOPE_FILES[1]).write_text('version: 1\nentries: broken\n')
    else:
        task = yaml.safe_load((harness / 'current-task.yaml').read_text())
        task['task']['id'] = 'TASK-999'
        write_yaml(harness / 'current-task.yaml', task)
    before = tree_bytes(harness)
    assert 'TEST_SCOPE_AUDIT_INVALID' in scope_codes(harness)
    assert tree_bytes(harness) == before


def test_add_then_hand_delete_cannot_use_historical_add_compatibility(harness):
    initialize_test_origin(harness, ['test_a.py'])
    (harness.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    scope_module().add_required_test(harness, 'test_b.py')
    audit = yaml.safe_load((harness / SCOPE_FILES[1]).read_text())
    assert len(audit['entries']) == 1
    assert audit['entries'][0]['operation'] == 'ADD'
    assert audit['entries'][0]['before_tests'] == ['test_a.py']
    assert audit['entries'][0]['after_tests'] == ['test_a.py', 'test_b.py']
    assert not scope_codes(harness)
    write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': ['test_a.py']}})
    assert 'TEST_SCOPE_RETIREMENT_UNAUDITED' in scope_codes(harness)


def test_duplicate_formal_add_is_byte_idempotent(harness):
    initialize_test_origin(harness, ['test_a.py'])
    (harness.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    scope_module().add_required_test(harness, 'test_b.py')
    before = tree_bytes(harness)
    scope_module().add_required_test(harness, 'test_b.py')
    assert tree_bytes(harness) == before


def test_failed_add_rolls_back_impact_audit_and_seal_as_one_unit(harness, monkeypatch):
    initialize_test_origin(harness, ['test_a.py'])
    (harness.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    before, identities = tree_bytes(harness), file_identities(harness)
    original = publication_fs.exchange
    partial, exchanged = [], []

    def fail_audit_once(*args):
        name = canonical_exchange_member(harness, args)
        if name == SCOPE_FILES[1] and not partial:
            partial.append({member: (harness / member).read_bytes()
                            for member in ('impact.yaml', *SCOPE_FILES)})
            raise OSError('injected audit publication failure')
        result = original(*args)
        if name is not None:
            exchanged.append(name)
        return result

    monkeypatch.setattr(publication_fs, 'exchange', fail_audit_once)
    with pytest.raises(OSError, match='injected audit publication failure'):
        scope_module().add_required_test(harness, 'test_b.py')
    assert len(partial) == 1
    assert yaml.safe_load(partial[0]['impact.yaml'])['impact']['required_tests'] == ['test_a.py', 'test_b.py']
    assert all(partial[0][name] == before[name] for name in SCOPE_FILES)
    assert exchanged == ['impact.yaml', 'impact.yaml'], 'real forward exchange and rollback required'
    assert_restored_with_retention(harness, before, identities)
    assert not scope_codes(harness)


def test_add_preserves_operator_impact_edit_at_publication_entry(harness, monkeypatch):
    initialize_test_origin(harness, ['test_a.py'])
    (harness.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    module = importlib.import_module('harness._scope_replay')
    original = transaction.publish
    owned = b'impact:\n  changed: []\n  required_tests: [test_a.py]\n  risks: [operator_owned]\n'
    def edit_then_publish(*args, **kwargs):
        (harness / 'impact.yaml').write_bytes(owned)
        return original(*args, **kwargs)
    monkeypatch.setattr(transaction, 'publish', edit_then_publish)
    audit_before = (harness / SCOPE_FILES[1]).read_bytes()
    with pytest.raises(OSError, match='TRANSACTION_RECOVERY_BLOCKED'):
        module.add_required_test(harness, 'test_b.py')
    assert (harness / 'impact.yaml').read_bytes() == owned
    assert (harness / SCOPE_FILES[1]).read_bytes() == audit_before


def test_prepublication_stale_check_does_not_rollback_matching_operator_bytes(harness, monkeypatch):
    initialize_test_origin(harness, ['test_a.py'])
    (harness.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    module = importlib.import_module('harness._scope_replay')
    original = module._snapshot
    count = 0
    owned = b'impact:\n  changed: []\n  required_tests:\n  - test_a.py\n  - test_b.py\n'
    def edit_at_prepublication(root):
        nonlocal count
        count += 1
        if count == 2:
            (harness / 'impact.yaml').write_bytes(owned)
        return original(root)
    monkeypatch.setattr(module, '_snapshot', edit_at_prepublication)
    from harness.context.model import ContextBuildError
    with pytest.raises(ContextBuildError, match='CONTEXT_STALE'):
        module.add_required_test(harness, 'test_b.py')
    assert (harness / 'impact.yaml').read_bytes() == owned


def test_process_death_during_add_recovers_after_staging_cleanup(harness):
    initialize_test_origin(harness, ['test_a.py'])
    (harness.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    before, identities = tree_bytes(harness), file_identities(harness)
    script = '''
import os
from pathlib import Path
from harness import publication_fs
from harness.test_scope import add_required_test
root = Path('.harness').stat()
original = publication_fs.exchange
def die_after_impact(*args):
    result = original(*args)
    for fd, name in ((args[0], args[1]), (args[2], args[3])):
        held = os.fstat(fd)
        if name == 'impact.yaml' and (held.st_dev, held.st_ino) == (root.st_dev, root.st_ino):
            os._exit(87)
    return result
publication_fs.exchange = die_after_impact
add_required_test(Path('.harness'), 'test_b.py')
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
                            capture_output=True, text=True, timeout=40, check=False)
    assert result.returncode == 87, result.stderr
    assert yaml.safe_load((harness / 'impact.yaml').read_bytes())['impact']['required_tests'] == ['test_a.py', 'test_b.py']
    assert all((harness / name).read_bytes() == before[name] for name in SCOPE_FILES)
    pending = {p: p.read_bytes() for p in (harness / '.transactions').glob('*.json')}
    assert len(pending) == 1
    staged = {(p.stat().st_dev, p.stat().st_ino): p.read_bytes()
              for p in (harness / '.staging').rglob('*') if p.is_file()}
    assert staged
    transaction.cleanup_stale_staging(harness)
    assert not list((harness / '.staging').iterdir())
    retained = {(p.stat().st_dev, p.stat().st_ino): p.read_bytes()
                for p in (harness / '.publication-retained').rglob('*') if p.is_file()}
    assert all(retained.get(identity) == content for identity, content in staged.items())
    assert {p: p.read_bytes() for p in (harness / '.transactions').glob('*.json')} == pending
    from harness.transaction_recovery import recover_pending_publications
    with telemetry_lock(harness):
        recover_pending_publications(harness)
    assert_restored_with_retention(harness, before, identities)
    assert not scope_codes(harness)
    recovered = tree_bytes(harness)
    with telemetry_lock(harness):
        recover_pending_publications(harness)
    assert tree_bytes(harness) == recovered


def test_scope_marker_is_rejected_by_legacy_gate_schema(harness):
    initialize_test_origin(harness, ['test_a.py'])
    from jsonschema import ValidationError, validate

    from harness.schema_resources import read_schema
    old_schema = read_schema('gate.schema.json')
    del old_schema['properties']['gate']['properties']['test_scope']
    gate = yaml.safe_load((harness / 'gate.yaml').read_text())
    with pytest.raises(ValidationError):
        validate(gate, old_schema)


def test_unknown_staged_member_cannot_become_owned_publication(harness, monkeypatch):
    initialize_test_origin(harness, ['test_a.py'])
    (harness.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    original, exchange, move = transaction.publish, publication_fs.exchange, publication_fs.move_noreplace
    unknown, steps = [], []
    before, identities = tree_bytes(harness), file_identities(harness)

    def record_exchange(*args):
        name = canonical_exchange_member(harness, args)
        if name is not None:
            steps.append(name)
        return exchange(*args)

    def record_move(*args):
        name = canonical_exchange_member(harness, args)
        if name is not None:
            steps.append(name)
        return move(*args)

    def inject_stage(root, stage, **kwargs):
        path = stage / 'operator_staged.txt'
        path.write_bytes(b'operator staging bytes')
        unknown.append(path)
        return original(root, stage, **kwargs)

    monkeypatch.setattr(publication_fs, 'exchange', record_exchange)
    monkeypatch.setattr(publication_fs, 'move_noreplace', record_move)
    monkeypatch.setattr(transaction, 'publish', inject_stage)
    with pytest.raises(OSError, match='^STAGED_ARTIFACTS_CHANGED$'):
        scope_module().add_required_test(harness, 'test_b.py')
    assert len(unknown) == 1 and unknown[0].read_bytes() == b'operator staging bytes'
    assert steps == []
    assert_restored_with_retention(harness, before, identities)
    assert not (harness / 'operator_staged.txt').exists()


def test_legacy_current_reduced_subset_cannot_self_initialize(harness):
    paths = [f'tests/test_{i:02}.py' for i in range(64)]
    write_yaml(harness / 'impact.yaml', {'impact': {'changed': [], 'required_tests': paths[:46]}})
    for name in SCOPE_FILES:
        (harness / name).unlink(missing_ok=True)
    before = tree_bytes(harness)
    assert 'TEST_SCOPE_AUDIT_INVALID' in scope_codes(harness)
    with pytest.raises(ValueError, match='TEST_SCOPE_'):
        scope_module().add_required_test(harness, 'tests/test_added.py')
    assert tree_bytes(harness) == before

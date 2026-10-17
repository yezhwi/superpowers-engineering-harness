"""Final Context must not adopt changed targets or compensate without journal."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import test_context_builder

from harness import publication_fs, publication_journal, transaction
from harness.context import store
from harness.telemetry_lock import telemetry_lock

harness = test_context_builder.harness


@pytest.mark.parametrize('mutation', ['target', 'extra_member'])
def test_final_context_rejects_publish_entry_mutation(harness, monkeypatch, mutation):
    store.generate_context(harness)
    real = transaction.publish
    injected = False
    target = harness / 'context/current.yaml'
    extra = harness / 'context/unexpected.yaml'

    def mutate(root, staged, **kwargs):
        nonlocal injected
        if (staged / 'context/current.yaml').exists():
            injected = True
            if mutation == 'target':
                target.write_bytes(b'unmanaged context bytes')
            else:
                (staged / 'context/unexpected.yaml').write_bytes(b'unexpected: true\n')
        return real(root, staged, **kwargs)

    monkeypatch.setattr(transaction, 'publish', mutate)
    error = None
    try:
        store.generate_context(harness)
    except (OSError, ValueError) as exc:
        error = exc
    assert injected
    assert error is not None, 'publication must reject mutation, not adopt source or stage members'
    if mutation == 'target':
        assert target.read_bytes() == b'unmanaged context bytes'
    assert not extra.exists()
    if mutation == 'extra_member':
        assert any(path.read_bytes() == b'unexpected: true\n'
                   for directory in (harness / '.staging', harness / '.publication-retained')
                   for path in directory.rglob('unexpected.yaml')), 'unknown staged bytes must survive refusal'


def test_crash_during_outer_context_compensation_has_recovery_authority(harness):
    store.generate_context(harness)
    before = {name: (harness / 'context' / name).read_bytes() for name in store.MEMBERS}
    # Different source facts make all relevant bundle projections change.
    test_context_builder.write_yaml(harness / 'requirements.yaml', {'requirements': [
        {'id': 'REQ-001', 'statement': 'New required context fact', 'priority': 'must', 'status': 'pending'}]})
    script = r'''
import os
from pathlib import Path
from harness import transaction
from harness.context import store
from harness.context.model import ContextBuildError
root = Path(os.environ['FIXTURE_ROOT'])
import json
from harness import publication_fs
real_publish = transaction.publish
real_fresh = store.require_fresh
real_write = transaction.atomic_write
real_exchange = publication_fs.exchange
returned = False
publishing = False
rejecting = False
checks = 0
def mark_and_die(boundary):
    (root / '.test-boundary.json').write_text(json.dumps({
        'boundary': boundary, 'checks': checks,
        'pending': bool(list((root / '.transactions').glob('*.json'))),
    }))
    os._exit(91)
def publish(*args, **kwargs):
    global returned, publishing
    publishing = True
    result = real_publish(*args, **kwargs)
    publishing = False
    returned = True
    return result
def final_check(*args, **kwargs):
    global checks, rejecting
    if publishing or returned:
        checks += 1
        if checks == 2:
            rejecting = True
            raise ContextBuildError('CONTEXT_STALE', 'injected second final freshness rejection')
    return real_fresh(*args, **kwargs)
def kill_after_restore(path, content):
    result = real_write(path, content)
    if returned and path.parent == root / 'context':
        mark_and_die('outer_atomic_write')
    return result
def kill_after_native_abort(*args):
    result = real_exchange(*args)
    if rejecting:
        mark_and_die('journaled_abort')
    return result
transaction.publish = publish
store.require_fresh = final_check
transaction.atomic_write = kill_after_restore
publication_fs.exchange = kill_after_native_abort
store.generate_context(root)
os._exit(92)
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                                 'FIXTURE_ROOT': str(harness)},
                            capture_output=True, text=True, check=False, timeout=40)
    assert result.returncode == 91, f'crash injection not reached: {result.returncode}: {result.stderr}'
    transaction.cleanup_stale_staging(harness)
    with telemetry_lock(harness):
        transaction.recover_pending_publications(harness)
    after = {name: (harness / 'context' / name).read_bytes() for name in store.MEMBERS}
    assert after == before, 'outer rollback died after journal retirement; canonical bundle remains mixed'
    marker = json.loads((harness / '.test-boundary.json').read_text())
    assert marker == {'boundary': 'journaled_abort', 'checks': 2, 'pending': True}


def prepare_caller(root, caller):
    from harness import _scope_replay
    from harness.context import escalation

    if caller == 'context':
        store.generate_context(root)
        test_context_builder.write_yaml(root / 'requirements.yaml', {'requirements': [
            {'id': 'REQ-001', 'statement': 'New bundle fact', 'priority': 'must', 'status': 'pending'}]})
        return (lambda: store.generate_context(root), store, 'require_fresh',
                tuple('context/' + name for name in store.MEMBERS))
    if caller == 'expansion':
        return (lambda: escalation.expand_context(root, 'INSUFFICIENT_CONTEXT', 'Need independent finalizer'),
                escalation, 'require_fresh', ('current-task.yaml', 'context/expansions.yaml'))
    from test_test_scope import initialize_test_origin

    initialize_test_origin(root, ['test_a.py'])
    (root.parent / 'test_b.py').write_text('def test_ok():\n    pass\n')
    return (lambda: _scope_replay.add_required_test(root, 'test_b.py'), _scope_replay, '_check_after',
            ('impact.yaml', 'test-scope-audit.yaml', 'test-scope-seal.yaml'))


def member_bytes(root, names):
    return {name: (root / name).read_bytes() if (root / name).exists() else None for name in names}


@pytest.mark.parametrize('caller', ['context', 'expansion', 'scope'])
@pytest.mark.parametrize('reject_second', [False, True])
def test_all_final_checks_run_before_commit(harness, monkeypatch, caller, reject_second):
    from harness.context.model import ContextBuildError

    run, module, check_name, names = prepare_caller(harness, caller)
    before = member_bytes(harness, names)
    real_check = getattr(module, check_name)
    real_publish, real_commit = transaction.publish, publication_journal.Operation.commit
    publishing = returned = False
    seen, committed = [], []

    def check(*args, **kwargs):
        result = real_check(*args, **kwargs)
        if publishing or returned:
            seen.append(bool(list((harness / '.transactions').glob('*.json'))))
            if reject_second and len(seen) == 2:
                raise ContextBuildError('CONTEXT_STALE', 'second independent final check rejected')
        return result

    def publish(*args, **kwargs):
        nonlocal publishing, returned
        publishing = True
        try:
            return real_publish(*args, **kwargs)
        finally:
            publishing, returned = False, True

    def commit(operation):
        committed.append(True)
        assert seen == [True, True], 'commit must follow both independent checks under active journal'
        return real_commit(operation)

    monkeypatch.setattr(module, check_name, check)
    monkeypatch.setattr(transaction, 'publish', publish)
    monkeypatch.setattr(publication_journal.Operation, 'commit', commit)
    if reject_second:
        with pytest.raises(ContextBuildError, match='second independent final check rejected'):
            run()
        assert not committed
        assert member_bytes(harness, names) == before
    else:
        run()
        assert committed == [True]
        assert all((harness / name).exists() for name in names)
    assert seen == [True, True]
    assert not list((harness / '.transactions').glob('*.json'))


@pytest.mark.parametrize('caller', ['context', 'expansion', 'scope'])
def test_exact_payload_drift_refuses_before_any_canonical_step(harness, monkeypatch, caller):
    run, _module, _check, names = prepare_caller(harness, caller)
    before = member_bytes(harness, names)
    real_publish = transaction.publish
    real_exchange, real_move = publication_fs.exchange, publication_fs.move_noreplace
    injected, steps = [], []
    suffix = b'\n# unmanaged staged bytes\n'

    def canonical_step(args):
        for fd, basename in ((args[0], args[1]), (args[2], args[3])):
            for name in names:
                parent = (harness / name).parent
                if basename == Path(name).name and parent.exists():
                    held, named = os.fstat(fd), parent.stat()
                    if (held.st_dev, held.st_ino) == (named.st_dev, named.st_ino):
                        steps.append(name)

    def exchange(*args):
        canonical_step(args)
        return real_exchange(*args)

    def move(*args):
        canonical_step(args)
        return real_move(*args)

    def publish(root, staged, **kwargs):
        target = staged / names[0]
        changed = target.read_bytes() + suffix
        target.write_bytes(changed)
        injected.append(changed)
        return real_publish(root, staged, **kwargs)

    monkeypatch.setattr(transaction, 'publish', publish)
    monkeypatch.setattr(publication_fs, 'exchange', exchange)
    monkeypatch.setattr(publication_fs, 'move_noreplace', move)
    with pytest.raises((OSError, ValueError)):
        run()
    assert len(injected) == 1
    assert steps == [], 'captured payload manifest must reject before any canonical event'
    assert member_bytes(harness, names) == before
    assert any(path.read_bytes() == injected[0]
               for directory in (harness / '.staging', harness / '.publication-retained')
               for path in directory.rglob(Path(names[0]).name)), 'refusal must retain unknown staged bytes'


def test_context_before_map_precedes_independent_validation(harness, monkeypatch):
    store.generate_context(harness)
    real = store.validate_context
    target = harness / 'context/current.yaml'
    injected = []

    def validate(*args, **kwargs):
        result = real(*args, **kwargs)
        target.write_bytes(b'operator changed target during independent validation')
        injected.append(True)
        return result

    monkeypatch.setattr(store, 'validate_context', validate)
    with pytest.raises(OSError, match='expected source changed'):
        store.generate_context(harness)
    assert injected == [True]
    assert target.read_bytes() == b'operator changed target during independent validation'
    assert not list((harness / '.transactions').glob('*.json'))


def test_reconciliation_replay_checks_twice_inside_active_journal(harness, monkeypatch):
    from test_reconcile_apply import prepare

    from harness import _scope_replay

    request = prepare(harness)
    real_load, real_publish = _scope_replay.load_scope, transaction.publish
    publishing = False
    observed = []

    def load(*args, **kwargs):
        result = real_load(*args, **kwargs)
        if publishing:
            observed.append(bool(list((harness / '.transactions').glob('*.json'))))
        return result

    def publish(*args, **kwargs):
        nonlocal publishing
        publishing = True
        try:
            return real_publish(*args, **kwargs)
        finally:
            publishing = False

    monkeypatch.setattr(_scope_replay, 'load_scope', load)
    monkeypatch.setattr(transaction, 'publish', publish)
    _scope_replay.apply_reconciliation(harness, request)
    assert observed == [True, True]
    assert yaml_required_tests(harness) == ['test_new.py']


def yaml_required_tests(root):
    import yaml

    return yaml.safe_load((root / 'impact.yaml').read_text())['impact']['required_tests']


@pytest.mark.parametrize('caller', ['expansion', 'scope'])
def test_death_in_second_final_check_recovers_without_staging(harness, caller):
    _run, _module, _check, names = prepare_caller(harness, caller)
    before = member_bytes(harness, names)
    script = r'''
import json
import os
from pathlib import Path
from harness import _scope_replay, transaction
from harness.context import escalation
root = Path(os.environ['FIXTURE_ROOT'])
caller = os.environ['CALLER']
module, check_name = ((_scope_replay, '_check_after') if caller == 'scope'
                      else (escalation, 'require_fresh'))
real_check, real_publish = getattr(module, check_name), transaction.publish
publishing = False
checks = 0
def publish(*args, **kwargs):
    global publishing
    publishing = True
    return real_publish(*args, **kwargs)
def check(*args, **kwargs):
    global checks
    result = real_check(*args, **kwargs)
    if publishing:
        checks += 1
        if checks == 2:
            (root / '.test-boundary.json').write_text(json.dumps({
                'checks': checks, 'pending': bool(list((root / '.transactions').glob('*.json'))),
            }))
            os._exit(91)
    return result
transaction.publish = publish
setattr(module, check_name, check)
if caller == 'scope':
    _scope_replay.add_required_test(root, 'test_b.py')
else:
    escalation.expand_context(root, 'INSUFFICIENT_CONTEXT', 'Need independent finalizer')
os._exit(92)
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                                 'FIXTURE_ROOT': str(harness), 'CALLER': caller},
                            capture_output=True, text=True, check=False, timeout=40)
    assert result.returncode == 91, f'crash injection not reached: {result.returncode}: {result.stderr}'
    assert json.loads((harness / '.test-boundary.json').read_text()) == {'checks': 2, 'pending': True}
    transaction.cleanup_stale_staging(harness)
    assert not list((harness / '.staging').iterdir())
    with telemetry_lock(harness):
        transaction.recover_pending_publications(harness)
    assert member_bytes(harness, names) == before
    assert not list((harness / '.transactions').glob('*.json'))

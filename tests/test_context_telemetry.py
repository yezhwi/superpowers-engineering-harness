"""EF-T08: telemetry never corrupts Context output or publication facts."""

import importlib
import importlib.util
import json
import signal
from pathlib import Path

import pytest
import test_context_builder
from test_context_cli import run_cli

from harness import controlplane, workspace
from harness.context.store import load_context

harness = test_context_builder.harness


def telemetry():
    assert importlib.util.find_spec('harness.context.telemetry'), 'opt-in telemetry missing'
    return importlib.import_module('harness.context.telemetry')


def test_exclusive_nested_phases_pause_parent():
    mod = telemetry()
    clock = [0.0]
    timer = mod.ContextTelemetry(clock=lambda: clock[0])
    with timer.activate():
        clock[0] = .001
        with timer.phase('source_load'):
            clock[0] = .003
            with timer.phase('gate_assess'):
                clock[0] = .007
            clock[0] = .010
        clock[0] = .012
    report = timer.finish('SUCCESS', False)
    assert report['total_ms'] == pytest.approx(12)
    assert report['phases_ms']['source_load'] == pytest.approx(5)
    assert report['phases_ms']['gate_assess'] == pytest.approx(4)
    assert report['phases_ms']['overhead'] == pytest.approx(3)
    assert sum(report['phases_ms'].values()) == pytest.approx(12)


def test_profile_counters_match_real_function_entries(harness, monkeypatch, tmp_path):
    from harness import quality_gate
    from harness.context import source, store

    output = tmp_path.parent / f'{tmp_path.name}-profile.json'
    calls = {'full_context_builds': 0, 'source_loads': 0, 'gate_assessments': 0}
    def spy(original, key):
        def wrapper(*args, **kwargs):
            calls[key] += 1
            return original(*args, **kwargs)
        return wrapper
    monkeypatch.setattr(store, 'build_context', spy(store.build_context, 'full_context_builds'))
    monkeypatch.setattr(source.FileContextSource, 'load', spy(source.FileContextSource.load, 'source_loads'))
    monkeypatch.setattr(quality_gate, 'assess_gate', spy(quality_gate.assess_gate, 'gate_assessments'))
    mod = telemetry()
    before = workspace.snapshot(harness.parent).fingerprint
    assert controlplane.cmd_context(None, 'compact', True, profile_json=output, progress=True) == 0
    report = json.loads(output.read_text())
    for key, value in calls.items():
        assert report['counters'][key] == value
    assert calls == {'full_context_builds': 1, 'source_loads': 2, 'gate_assessments': 2}
    assert report['context_published'] is True
    assert report['outcome'] == 'SUCCESS'
    assert abs(sum(report['phases_ms'].values()) - report['total_ms']) <= 1
    assert workspace.snapshot(harness.parent).fingerprint == before
    assert load_context(harness)[1]['freshness']
    assert report['timing_scope'] == 'context_operation_excludes_profile_output'
    assert report['phase_semantics'] == 'exclusive'
    from jsonschema import validate

    from harness.schema_resources import read_schema
    validate(report, read_schema('context-profile.schema.json'))
    assert mod.active() is None


def test_cli_opt_in_prints_context_only(harness, tmp_path):
    output = tmp_path.parent / f'{tmp_path.name}-cli-profile.json'
    result = run_cli(harness.parent, '--json', '--progress', '--profile-json', str(output))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['mode'] == 'compact'
    assert json.loads(output.read_text())['context_published'] is True
    assert 'phase=' in result.stderr
    assert 'src/local.py' not in result.stderr


@pytest.mark.parametrize('kind', ['inside', 'existing', 'symlink', 'symlink_parent', 'missing_parent'])
def test_profile_precheck_fails_before_publish(harness, tmp_path, kind):
    outside = tmp_path.parent / f'{tmp_path.name}-unsafe'
    if kind == 'inside':
        output = harness / 'profile.json'
    elif kind == 'existing':
        output = outside
        output.write_text('user bytes')
    elif kind == 'symlink':
        output = outside
        output.symlink_to(tmp_path / 'missing')
    elif kind == 'symlink_parent':
        outside.symlink_to(tmp_path.parent, target_is_directory=True)
        output = outside / 'escape-profile.json'
    else:
        output = outside / 'missing-profile.json'
    result = run_cli(harness.parent, '--profile-json', str(output))
    assert result.returncode == 2
    assert 'context_published=false' in result.stderr
    assert not result.stdout
    assert not (harness / 'context/current.yaml').exists()
    if kind == 'existing':
        assert output.read_text() == 'user bytes'


@pytest.mark.parametrize('when', ['after_generate', 'after_stdout'])
def test_sigterm_profile_failure_preserves_cancellation(harness, tmp_path, when):
    """Break caught: profile-only error3 must not replace real SIGTERM exit130."""
    import os
    import subprocess
    import sys

    output = tmp_path.parent / f'{tmp_path.name}-cancel-profile.json'
    observed = output.with_suffix('.observed.json')
    script = r'''
import builtins, json, os, signal
from pathlib import Path
from harness import controlplane
from harness.context import store, telemetry
from harness.telemetry_lock import _HELD
output = Path(os.environ['PROFILE_OUTPUT'])
when = os.environ['SIGNAL_WHEN']
previous = signal.getsignal(signal.SIGTERM)
real_generate, real_print = store.generate_context, builtins.print
real_publish, real_link = telemetry.ProfileDestination.publish, os.link
attempts, native_failures = [], []
def generated(*args, **kwargs):
    document = real_generate(*args, **kwargs)
    if when == 'after_generate':
        os.kill(os.getpid(), signal.SIGTERM)
    return document
def printed(*args, **kwargs):
    real_print(*args, **kwargs)
    if kwargs.get('end') == '' and when == 'after_stdout':
        os.kill(os.getpid(), signal.SIGTERM)
def failed_link(src, dst, *args, **kwargs):
    if str(src).startswith('.harness-profile-') and dst == output.name:
        native_failures.append(True)
        raise OSError('private-profile-path secret-url')
    return real_link(src, dst, *args, **kwargs)
def publishing(destination, report):
    assert not getattr(_HELD, 'paths', set()), 'terminal write must be lock-free'
    assert signal.getsignal(signal.SIGTERM) == previous
    assert telemetry.active() is None
    attempts.append(report)
    try:
        return real_publish(destination, report)
    finally:
        Path(os.environ['PROFILE_OBSERVED']).write_text(json.dumps({
            'report': report, 'attempts': len(attempts), 'native_failures': len(native_failures)}))
store.generate_context = generated
builtins.print = printed
telemetry.ProfileDestination.publish = publishing
os.link = failed_link
raise SystemExit(controlplane.cmd_context(None, 'compact', True, profile_json=output))
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                                 'PROFILE_OUTPUT': str(output), 'PROFILE_OBSERVED': str(observed), 'SIGNAL_WHEN': when},
                            capture_output=True, text=True, timeout=60, check=False)
    facts = json.loads(observed.read_text())
    assert facts['attempts'] == facts['native_failures'] == 1
    assert facts['report']['outcome'] == 'CANCELLED' and facts['report']['context_published'] is True
    assert json.loads(result.stdout)['context_hash']
    assert load_context(harness)[1]['freshness']
    assert not output.exists() and not list(output.parent.glob('.harness-profile-*'))
    assert 'secret-url' not in result.stderr and 'private-profile-path' not in result.stderr
    assert result.returncode == 130, result.stderr
    assert result.stderr.strip() == 'PROFILE_WRITE_FAILED context_published=true'


@pytest.mark.parametrize('state,code,published,outcome', [
    ('success', 3, True, 'SUCCESS'),
    ('generation_failure', 2, False, 'FAILED'),
    ('stdout_failure', 2, True, 'FAILED'),
    ('cancel_before_publish', 130, False, 'CANCELLED'),
])
def test_profile_native_failure_preserves_primary_outcome(harness, monkeypatch, tmp_path, capsys, state, code, published, outcome):
    import builtins

    from harness.context import store
    from harness.context.model import ContextBuildError
    from harness.telemetry_lock import _HELD

    mod = telemetry()
    output = tmp_path.parent / f'{tmp_path.name}-native-profile-failure.json'
    real_print, real_link, real_publish = builtins.print, mod.os.link, mod.ProfileDestination.publish
    attempts, native_failures = [], []
    previous = signal.getsignal(signal.SIGTERM)

    def failed_generation(*args, **kwargs):
        if state == 'cancel_before_publish':
            signal.raise_signal(signal.SIGTERM)
            raise KeyboardInterrupt
        raise ContextBuildError('CONTEXT_STALE', 'fixture source changed')

    def failed_stdout(*args, **kwargs):
        if kwargs.get('end') == '':
            raise BrokenPipeError('private stdout fault')
        return real_print(*args, **kwargs)

    def failed_link(src, dst, *args, **kwargs):
        if str(src).startswith('.harness-profile-') and dst == output.name:
            native_failures.append(True)
            raise OSError('private-profile-path secret-url')
        return real_link(src, dst, *args, **kwargs)

    def observe(destination, report):
        assert not getattr(_HELD, 'paths', set()) and mod.active() is None
        assert signal.getsignal(signal.SIGTERM) == previous
        attempts.append(report)
        return real_publish(destination, report)

    if state in {'generation_failure', 'cancel_before_publish'}:
        monkeypatch.setattr(store, 'generate_context', failed_generation)
    elif state == 'stdout_failure':
        monkeypatch.setattr(builtins, 'print', failed_stdout)
    monkeypatch.setattr(mod.os, 'link', failed_link)
    monkeypatch.setattr(mod.ProfileDestination, 'publish', observe)
    assert controlplane.cmd_context(None, 'compact', True, profile_json=output) == code
    stdout, stderr = capsys.readouterr()
    assert len(attempts) == len(native_failures) == 1
    assert attempts[0]['outcome'] == outcome and attempts[0]['context_published'] is published
    assert 'secret-url' not in stderr and 'private-profile-path' not in stderr
    assert ('PROFILE_WRITE_FAILED_CONTEXT_PUBLISHED' in stderr) is (state == 'success')
    if state == 'success':
        assert json.loads(stdout)['context_hash'] and load_context(harness)[1]['freshness']
    else:
        assert not stdout
    assert not output.exists() and not list(output.parent.glob('.harness-profile-*'))


def test_profile_postpublish_oserror_is_three_with_legal_stdout(harness, monkeypatch, tmp_path, capsys):
    mod = telemetry()
    output = tmp_path.parent / f'{tmp_path.name}-failed-profile.json'
    def fail(*args):
        raise OSError('private/path secret-url')
    monkeypatch.setattr(mod.ProfileDestination, 'publish', fail)
    assert controlplane.cmd_context(None, 'compact', True, profile_json=output) == 3
    stdout, stderr = capsys.readouterr()
    assert json.loads(stdout)['context_hash']
    assert stderr.strip() == 'PROFILE_WRITE_FAILED_CONTEXT_PUBLISHED context_published=true'
    assert 'secret-url' not in stderr
    assert load_context(harness)[1]['freshness']


def test_stdout_failure_is_not_profile_exit_three(harness, monkeypatch, tmp_path, capsys):
    mod = telemetry()
    import builtins
    real_print = builtins.print
    def fail_stdout(*args, **kwargs):
        if kwargs.get('end') == '':
            raise BrokenPipeError('pipe closed')
        return real_print(*args, **kwargs)
    monkeypatch.setattr(builtins, 'print', fail_stdout)
    output = tmp_path.parent / f'{tmp_path.name}-stdout-failure.json'
    assert controlplane.cmd_context(None, 'compact', True, profile_json=output) == 2
    _, stderr = capsys.readouterr()
    assert 'context_published=true' in stderr
    assert 'PROFILE_WRITE_FAILED_CONTEXT_PUBLISHED' not in stderr
    report = json.loads(output.read_text())
    assert report['outcome'] == 'FAILED'
    assert report['context_published'] is True
    assert mod.active() is None


def test_profile_atomic_publish_never_overwrites_competing_target(tmp_path):
    mod = telemetry()
    root = tmp_path / 'repo'
    root.mkdir()
    output = tmp_path / 'profile.json'
    destination = mod.ProfileDestination(output, root)
    output.write_text('competing user bytes')
    with pytest.raises(OSError):
        destination.publish({'version': 1})
    assert output.read_text() == 'competing user bytes'
    assert not list(tmp_path.glob('.harness-profile-*'))


def test_profile_parent_substitution_cannot_escape(tmp_path):
    mod = telemetry()
    root = tmp_path / 'repo'
    root.mkdir()
    parent = tmp_path / 'output'
    parent.mkdir()
    target = parent / 'profile.json'
    destination = mod.ProfileDestination(target, root)
    parent.rename(tmp_path / 'original')
    parent.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        destination.publish({'version': 1})
    assert not (root / 'profile.json').exists()
    assert not (tmp_path / 'original/profile.json').exists()


@pytest.mark.parametrize('after_publish', [False, True])
def test_cancelled_profile_written_once_after_lock_release(harness, monkeypatch, tmp_path, after_publish):
    from harness.context import store
    from harness.telemetry_lock import _HELD
    mod = telemetry()
    original_generate = store.generate_context
    original_publish = mod.ProfileDestination.publish
    writes = []
    previous_handler = signal.getsignal(signal.SIGTERM)
    def cancel(*args, **kwargs):
        if after_publish:
            document = original_generate(*args, **kwargs)
            signal.raise_signal(signal.SIGTERM)
            return document
        signal.raise_signal(signal.SIGTERM)
        raise KeyboardInterrupt
    def observe(destination, report):
        assert not getattr(_HELD, 'paths', set())
        writes.append(report)
        return original_publish(destination, report)
    monkeypatch.setattr(store, 'generate_context', cancel)
    monkeypatch.setattr(mod.ProfileDestination, 'publish', observe)
    output = tmp_path.parent / f'{tmp_path.name}-cancel.json'
    assert controlplane.cmd_context(None, 'compact', True, profile_json=output) == 130
    assert len(writes) == 1
    assert writes[0]['outcome'] == 'CANCELLED'
    assert writes[0]['context_published'] is after_publish
    assert signal.getsignal(signal.SIGTERM) == previous_handler


def test_disabled_profile_does_not_check_external_paths(harness, monkeypatch):
    mod = telemetry()
    def forbidden(*args):
        pytest.fail('disabled profile must not validate destination')
    monkeypatch.setattr(mod.ProfileDestination, '__init__', forbidden)
    assert controlplane.cmd_context(None, 'compact', True) == 0


@pytest.mark.parametrize('after_publish', [False, True])
def test_sigterm_subprocess_emits_single_terminal_profile(harness, tmp_path, after_publish):
    import os
    import subprocess
    import sys
    repo = Path(__file__).resolve().parents[1]
    output = tmp_path.parent / f'{tmp_path.name}-sigterm-subprocess.json'
    script = '''
import os, signal
from pathlib import Path
from harness import controlplane
from harness.context import store
original = store.generate_context
def cancelled(*args, **kwargs):
    if AFTER:
        result = original(*args, **kwargs)
        os.kill(os.getpid(), signal.SIGTERM)
        return result
    os.kill(os.getpid(), signal.SIGTERM)
    raise KeyboardInterrupt
store.generate_context = cancelled
raise SystemExit(controlplane.cmd_context(None, 'compact', True, profile_json=Path(OUTPUT)))
'''.replace('AFTER', repr(after_publish)).replace('OUTPUT', repr(str(output)))
    result = subprocess.run([sys.executable, '-c', script], cwd=harness.parent,
                            env={**os.environ, 'PYTHONPATH': str(repo / 'src')},
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 130, result.stderr
    report = json.loads(output.read_text())
    assert report['outcome'] == 'CANCELLED'
    assert report['context_published'] is after_publish
    assert not list(output.parent.glob('.harness-profile-*'))


def test_failed_generation_emits_safe_failed_profile(harness, monkeypatch, tmp_path, capsys):
    from harness.context import store
    from harness.context.model import ContextBuildError
    telemetry()
    def fail(*args, **kwargs):
        raise ContextBuildError('CONTEXT_STALE', 'source changed')
    monkeypatch.setattr(store, 'generate_context', fail)
    output = tmp_path.parent / f'{tmp_path.name}-failure.json'
    assert controlplane.cmd_context(None, 'compact', True, profile_json=output) == 2
    stdout, stderr = capsys.readouterr()
    assert not stdout
    assert 'context_published=false' in stderr
    report = json.loads(output.read_text())
    assert report['outcome'] == 'FAILED'
    assert report['context_published'] is False
    assert report['total_ms'] >= 0

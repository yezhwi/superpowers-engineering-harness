"""PF-12/13: real local children, bounded capture and process-group cleanup."""
import importlib
import json
import os
import sys
import time

import pytest


def probe_module():
    return importlib.import_module('harness.launcher_probe')


def launcher(tmp_path, body):
    path = tmp_path / 'launcher'
    path.write_text(f'#!{sys.executable}\n' + body)
    path.chmod(0o755)
    return path


def test_success_inherits_environment_and_original_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv('PREFLIGHT_FIXTURE', 'inherited')
    path = launcher(tmp_path, "import os,json; print(json.dumps([os.getcwd(),os.environ['PREFLIGHT_FIXTURE']]))\n")
    public = tmp_path / 'public'
    public.symlink_to(path)
    report = probe_module().probe_launcher(public, cwd=tmp_path)
    assert report['status'] == 'SUCCEEDED'
    assert report['spawn_attempts'] == 1
    assert report['environment_policy'] == 'INHERITED'
    assert json.loads(report['stdout']) == [str(tmp_path), 'inherited']
    assert 'cli_identity' not in report
    assert 'inherited' not in json.dumps({k: v for k, v in report.items() if k != 'stdout'})


@pytest.mark.parametrize('kind,status', [('missing','SPAWN_ERROR'), ('shebang','SPAWN_ERROR'),
                                         ('permissions','SPAWN_ERROR'), ('exit','NONZERO_EXIT'),
                                         ('signal','NONZERO_EXIT')])
def test_process_failures_are_not_success(tmp_path, kind, status):
    path = launcher(tmp_path, 'raise SystemExit(42)\n')
    if kind == 'missing':
        path.unlink()
    elif kind == 'shebang':
        path.write_text('#!/not/a/real/interpreter\n')
    elif kind == 'permissions':
        path.chmod(0o644)
    elif kind == 'signal':
        path.write_text(f'#!{sys.executable}\nimport os,signal; os.kill(os.getpid(),signal.SIGTERM)\n')
    report = probe_module().probe_launcher(path, cwd=tmp_path)
    assert report['status'] == status
    assert report['spawn_attempts'] == 1
    if kind == 'exit':
        assert report['exit_code'] == 42
    if status == 'SPAWN_ERROR':
        assert isinstance(report['errno'], int)


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
@pytest.mark.parametrize('size,status', [(65536,'SUCCEEDED'), (65537,'OUTPUT_LIMIT')])
def test_raw_stream_limits_are_inclusive(tmp_path, stream, size, status):
    fd = 1 if stream == 'stdout' else 2
    path = launcher(tmp_path, f'import os; os.write({fd}, b"x"*{size})\n')
    report = probe_module().probe_launcher(path, cwd=tmp_path)
    assert report['status'] == status, {key: value for key, value in report.items() if key not in {'stdout', 'stderr'}}
    assert len(report[stream].encode()) == 65536
    assert report[f'{stream}_truncated'] == (size > 65536)


def test_simultaneous_pipe_pressure_is_drained_without_deadlock(tmp_path):
    path = launcher(tmp_path, 'import os\nfor i in range(64):\n os.write(1,b"x"*1024); os.write(2,b"y"*1024)\n')
    report = probe_module().probe_launcher(path, cwd=tmp_path)
    assert report['status'] == 'SUCCEEDED'
    assert len(report['stdout']) == len(report['stderr']) == 65536


def test_output_limit_precedes_timeout_in_same_observation():
    assert probe_module()._termination_reason(timed_out=True, output_limit=True) == 'OUTPUT_LIMIT'
    assert probe_module()._termination_reason(timed_out=True, output_limit=False) == 'TIMED_OUT'


def test_real_deadline_kills_term_ignoring_group_and_reaps_root(tmp_path):
    pidfile = tmp_path / 'pid'
    path = launcher(tmp_path, f'import os,signal,time\nfrom pathlib import Path\nPath({str(pidfile)!r}).write_text(str(os.getpid()))\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n')
    started = time.monotonic()
    report = probe_module().probe_launcher(path, cwd=tmp_path)
    assert report['status'] == 'TIMED_OUT'
    assert 10 <= time.monotonic() - started < 15
    pid = int(pidfile.read_text())
    assert pid != os.getpgrp()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_descendant_holding_pipe_does_not_block_after_root_exit(tmp_path, monkeypatch):
    module = probe_module()
    monkeypatch.setattr(module, 'DEADLINE_SECONDS', 0.3)
    path = launcher(tmp_path, 'import os,time\nif os.fork()==0:\n time.sleep(60)\nelse:\n os._exit(0)\n')
    started = time.monotonic()
    report = module.probe_launcher(path, cwd=tmp_path)
    assert report['status'] == 'TIMED_OUT'
    assert time.monotonic() - started < 4


def test_binary_output_uses_raw_byte_budget_and_replacement_decode(tmp_path):
    path = launcher(tmp_path, 'import os; os.write(1,bytes([255])*65536)\n')
    report = probe_module().probe_launcher(path, cwd=tmp_path)
    assert report['status'] == 'SUCCEEDED'
    assert report['stdout'] == '\ufffd' * 65536
    assert report['stdout_truncated'] is False


def test_escaped_descendant_cannot_hold_probe_pipes_forever(tmp_path, monkeypatch):
    import signal

    module = probe_module()
    monkeypatch.setattr(module, 'DEADLINE_SECONDS', 3.0)
    pidfile = tmp_path / 'escaped'
    path = launcher(tmp_path, (
        'import os,time\nfrom pathlib import Path\n'
        'if os.fork()==0:\n'
        ' os.setsid()\n'
        f' Path({str(pidfile)!r}).write_text(str(os.getpid()))\n'
        ' time.sleep(60)\n'
        'else:\n os._exit(0)\n'
    ))
    try:
        started = time.monotonic()
        report = module.probe_launcher(path, cwd=tmp_path)
        assert report['status'] == 'TIMED_OUT'
        assert time.monotonic() - started < 7
        assert pidfile.is_file(), {key: value for key, value in report.items() if key != 'stdout'}
        assert report['spawn_attempts'] == 1
    finally:
        if pidfile.is_file():
            pid = int(pidfile.read_text())
            assert pid != os.getpgrp()
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_cleanup_failure_overrides_primary_and_is_not_hidden(tmp_path, monkeypatch):
    module = probe_module()
    original = module._stop_group
    def stop(process):
        original(process)  # Clean actual fixture process despite injected failure.
        return False
    monkeypatch.setattr(module, '_stop_group', stop)
    path = launcher(tmp_path, 'import os; os.write(1,b"x"*65537)\n')
    report = module.probe_launcher(path, cwd=tmp_path)
    assert report['status'] == 'CLEANUP_ERROR'
    assert report['primary_status'] == 'OUTPUT_LIMIT'


def test_monitor_failure_still_counts_spawn_and_cleans_real_child(tmp_path, monkeypatch):
    module = probe_module()
    def broken(*args, **kwargs):
        raise ValueError('injected monitor failure')
    monkeypatch.setattr(module.selectors, 'DefaultSelector', broken)
    path = launcher(tmp_path, 'import time; time.sleep(60)\n')
    report = module.probe_launcher(path, cwd=tmp_path)
    assert report['status'] == 'CLEANUP_ERROR'
    assert report['spawn_attempts'] == 1
    assert report['exit_code'] is not None


def test_non_posix_is_explicit_and_does_not_spawn(tmp_path, monkeypatch):
    module = probe_module()
    monkeypatch.setattr(module, '_posix', lambda: False)
    report = module.probe_launcher(tmp_path / 'unused', cwd=tmp_path)
    assert report['status'] == 'UNSUPPORTED_PLATFORM'
    assert report['spawn_attempts'] == 0

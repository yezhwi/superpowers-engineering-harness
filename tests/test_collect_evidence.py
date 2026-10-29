from pathlib import Path
from types import SimpleNamespace

import pytest

import harness.collect_evidence as evidence_module
from harness.collect_evidence import execution_environment, main


def test_public_module_has_no_shell_command_executor():
    """Break caught: external callers can invoke shell executor directly."""
    assert not hasattr(evidence_module, "collect")
    assert not hasattr(evidence_module, "TrustedLocalCommand")


def test_only_main_invokes_private_shell_executor():
    source = Path(evidence_module.__file__).read_text()
    assert source.count("_collect(") == 2  # definition plus main call


def test_readme_marks_shell_executor_as_unsupported_internal_api():
    readme = Path("README.md").read_text()
    assert "unsupported internal API" in readme


def test_kubectl_exec_records_namespace_workload_and_cwd():
    env = execution_environment(
        "kubectl -n coagents-dev exec deploy/frontend -- "
        "sh -lc 'cd /workspaces/coagents_service/agents-frontend && pytest'"
    )
    assert env == {
        "transport": "kubectl_exec",
        "namespace": "coagents-dev",
        "workload": "deploy/frontend",
        "cwd": "/workspaces/coagents_service/agents-frontend",
    }


def test_kubectl_exec_without_namespace_omits_namespace():
    env = execution_environment(
        "kubectl exec deploy/app -- sh -lc 'cd /workspace && pytest'"
    )
    assert env["transport"] == "kubectl_exec"
    assert env["workload"] == "deploy/app"
    assert env["cwd"] == "/workspace"
    assert "namespace" not in env
    assert "container" not in env


def test_kubectl_exec_without_container_flag_does_not_guess_container():
    env = execution_environment(
        "kubectl -n ns exec deploy/frontend -- sh -lc 'cd /app && true'"
    )
    assert "container" not in env
    assert env["namespace"] == "ns"


def test_kubectl_exec_records_container_when_flag_present():
    env = execution_environment(
        "kubectl -n ns exec deploy/frontend -c frontend -- sh -lc 'cd /app && true'"
    )
    assert env["container"] == "frontend"


def test_non_kubectl_command_has_no_execution_environment():
    assert execution_environment("pytest tests/test_x.py") is None
    assert execution_environment("sh -lc 'cd backend && pytest'") is None


def test_unparseable_kubectl_stores_unknown_transport():
    assert execution_environment("kubectl get pods") == {"transport": "unknown"}
    assert execution_environment("kubectl exec") == {"transport": "unknown"}


def test_main_records_kubectl_provenance_without_changing_result(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.collect_evidence.git_head", lambda: "a" * 40)
    monkeypatch.setattr(
        "harness.collect_evidence.snapshot", lambda: SimpleNamespace(head="a" * 40, fingerprint="workspace")
    )
    monkeypatch.setattr(
        "harness.execution_capture.run_command",
        lambda *args, **kwargs: type(
            "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )(),
    )
    command = (
        ".devkind/kubectl -n coagents-dev exec deploy/frontend -- "
        "sh -lc 'cd /workspaces/coagents_service/agents-frontend && true'"
    )
    assert (
        main(
            [
                "--type",
                "custom",
                "--command",
                command,
                "--harness-dir",
                str(tmp_path / ".harness"),
            ]
        )
        == 0
    )
    import json

    record = json.loads((tmp_path / ".harness/evidence/custom.json").read_text())
    assert record["exit_code"] == 0
    assert record["runtime"]["executable"]
    assert record["execution_environment"] == {
        "transport": "kubectl_exec",
        "namespace": "coagents-dev",
        "workload": "deploy/frontend",
        "cwd": "/workspaces/coagents_service/agents-frontend",
    }


def test_npm_run_build_is_not_test_runner_unresolved(tmp_path, monkeypatch):
    """Break caught: npm run build fails collection with TEST_RUNNER_UNRESOLVED."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "package.json").write_text('{"scripts": {"build": "tsc"}}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("harness.collect_evidence.git_head", lambda: "a" * 40)
    monkeypatch.setattr(
        "harness.collect_evidence.snapshot", lambda: SimpleNamespace(head="a" * 40, fingerprint="workspace")
    )
    monkeypatch.setattr(
        "harness.execution_capture.run_command",
        lambda *args, **kwargs: type(
            "R", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )(),
    )
    from harness.collect_evidence import bind_covered_tests

    assert bind_covered_tests((), "npm run build", tmp_path) == ()
    assert (
        main(
            [
                "--type",
                "build",
                "--command",
                "npm run build",
                "--harness-dir",
                str(tmp_path / ".harness"),
            ]
        )
        == 0
    )


def test_pytest_command_is_not_blocked_by_unrelated_npm_run(tmp_path):
    from harness.collect_evidence import bind_covered_tests

    spec = tmp_path / "tests" / "test_x.py"
    spec.parent.mkdir()
    spec.write_text("def test_x():\n    assert True\n")
    (tmp_path / "package.json").write_text('{"scripts": {"lint": "eslint ."}}')
    bound = bind_covered_tests(
        ("tests/test_x.py",),
        "pytest tests/test_x.py && npm run lint",
        tmp_path,
    )
    assert bound == ("tests/test_x.py",)


def test_main_marks_cli_command_as_trusted_local(tmp_path, monkeypatch):
    """Break caught: CLI passes raw command text past trust boundary."""
    monkeypatch.setattr("harness.collect_evidence.git_head", lambda: "a" * 40)
    monkeypatch.setattr(
        "harness.collect_evidence.snapshot", lambda: SimpleNamespace(head="a" * 40, fingerprint="workspace")
    )

    assert (
        main(
            [
                "--type",
                "custom",
                "--command",
                "printf ok",
                "--harness-dir",
                str(tmp_path / ".harness"),
            ]
        )
        == 0
    )


NATIVE_COLLECTOR_PENDING = '''
import os
from pathlib import Path
from harness import publication_fs
from harness.transaction import StagedArtifact,publish,stage
root=Path('.harness');identity=root.stat();original=publication_fs.exchange
artifacts=tuple(StagedArtifact(name,(root/name).read_bytes()) for name in ('gate.yaml','impact.yaml'))
def die_after_gate(*args):
    result=original(*args);held=os.fstat(args[0])
    if args[1]=='gate.yaml' and (held.st_dev,held.st_ino)==(identity.st_dev,identity.st_ino):
        os._exit(87)
    return result
publication_fs.exchange=die_after_gate
publish(root,stage(root,artifacts),replace_paths=frozenset(a.relative_path for a in artifacts),durable=True,
        expected_sources={a.relative_path:a.content for a in artifacts},expected_artifacts=artifacts)
'''


def collector_fixture(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    from harness._scope_replay import bind_scope_identity
    from harness.init import init_harness

    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.chdir(tmp_path)
    init_harness(tmp_path)
    root = tmp_path / '.harness'
    bind_scope_identity(root, 'TASK-777')
    subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '--allow-empty', '-qm', 'fixture baseline'], cwd=tmp_path, check=True,
                   capture_output=True)
    env = {**os.environ, 'PYTHONPATH': str(Path(evidence_module.__file__).resolve().parents[1])}

    def cli(*args):
        return subprocess.run([sys.executable, '-m', 'harness.cli', *args], cwd=tmp_path,
                              env=env, capture_output=True, text=True, timeout=35, check=False)

    return root, env, cli


def retained_collector_result(result):
    import json

    marker = 'EVIDENCE_RESULT_RETAINED: '
    assert marker in result.stderr, result.stdout + result.stderr
    path = Path(result.stderr.split(marker, 1)[1].splitlines()[0])
    document = json.loads(path.read_text())
    assert document['accepted'] is False
    assert document['evidence']['exit_code'] == 0
    assert (path.stat().st_mode & 0o777) == 0o600
    assert (path.parent.stat().st_mode & 0o777) == 0o700
    return path, document


@pytest.mark.parametrize('attack', [
    'budget', 'collision', 'pending-command', 'pending-reuse',
    'pending-persist', 'task-change', 'root-change',
])
def test_collector_split_ownership_preserves_current_facts(tmp_path, monkeypatch, attack):
    """Break caught: collector clobbers child state or consumes pending facts."""
    import hashlib
    import json
    import shlex
    import subprocess
    import sys

    import yaml
    from test_test_scope import file_identities, tree_bytes

    from harness.telemetry_lock import telemetry_lock
    from harness.transaction_recovery import recover_pending_publications

    root, env, cli = collector_fixture(tmp_path, monkeypatch)
    healthy = cli('evidence', 'run', '--type', 'lint', '--command', 'printf healthy')
    assert healthy.returncode == 0, healthy.stdout + healthy.stderr
    assert json.loads((root / 'evidence/lint.json').read_text())['exit_code'] == 0
    marker = tmp_path.parent / (tmp_path.name + '-child.json')
    command = shlex.join([sys.executable, '-c', f'from pathlib import Path; Path({str(marker)!r}).write_text("executed")'])
    kind, covered = 'build', []
    args = []
    if attack == 'budget':
        (tmp_path / 'tests').mkdir()
        test = tmp_path / 'tests/test_nested.py'
        test.write_text('''import subprocess,sys
from pathlib import Path
import yaml

def test_child():
    result=subprocess.run([sys.executable,'-m','harness.cli','evidence','run','--type','build','--command','printf child'],capture_output=True,text=True,timeout=15)
    assert result.returncode == 0, result.stdout+result.stderr
    task=yaml.safe_load(Path('.harness/current-task.yaml').read_text())
    task['iteration']=3
    Path('.harness/current-task.yaml').write_text(yaml.safe_dump(task))
''')
        kind, covered = 'unit_test', ['--covered-test', 'tests/test_nested.py']
        command = shlex.join([sys.executable, '-m', 'pytest', 'tests/test_nested.py', '-q'])
    elif attack == 'collision':
        program = f'''import subprocess,sys,hashlib
from pathlib import Path
result=subprocess.run([sys.executable,'-m','harness.cli','evidence','run','--type','build','--command','printf child'],capture_output=True,text=True,timeout=15)
assert result.returncode==0,result.stdout+result.stderr
Path({str(marker)!r}).write_text(hashlib.sha256(Path('.harness/evidence/build.json').read_bytes()).hexdigest())
'''
        command = shlex.join([sys.executable, '-c', program])
    elif attack in {'pending-command', 'pending-reuse'}:
        if attack == 'pending-reuse':
            command = 'printf reusable'
            assert cli('evidence', 'run', '--type', kind, '--command', command).returncode == 0
            args = ['--reuse-if-valid']
        before = tree_bytes(root)
        identities = file_identities(root)
        child = subprocess.run([sys.executable, '-c', NATIVE_COLLECTOR_PENDING], cwd=tmp_path,
                               env=env, capture_output=True, text=True, timeout=20, check=False)
        assert child.returncode == 87, child.stdout + child.stderr
        assert (root / 'gate.yaml').stat().st_ino != identities['gate.yaml'][1]
        partial = tree_bytes(root)
        try:
            result = cli('evidence', 'run', '--type', kind, '--command', command, *args)
            after = tree_bytes(root)
        finally:
            with telemetry_lock(root):
                recover_pending_publications(root)
        assert {n: tree_bytes(root)[n] for n in before} == before
        assert not marker.exists(), 'collector executed command while native publication pending'
        assert after == partial, 'collector changed canonical facts while native publication pending'
        assert result.returncode == 2 and 'TRANSACTION_RECOVERY_REQUIRED' in result.stderr, result.stdout + result.stderr
        return
    elif attack == 'pending-persist':
        program = f'''import subprocess,sys
result=subprocess.run([sys.executable,'-c',{NATIVE_COLLECTOR_PENDING!r}],capture_output=True,text=True,timeout=15)
assert result.returncode==87,result.stdout+result.stderr
print('measured result before pending refusal')
'''
        command = shlex.join([sys.executable, '-c', program])
    else:
        program = '''from pathlib import Path
import yaml
root=Path('.harness')
'''
        if attack == 'root-change':
            program += "import shutil\nshutil.copytree(root,'.replacement')\nroot.rename('.previous')\nPath('.replacement').rename(root)\n"
        else:
            program += "task=yaml.safe_load((root/'current-task.yaml').read_text())\ntask['task']['id']='TASK-888'\n(root/'current-task.yaml').write_text(yaml.safe_dump(task))\n"
        program += "print('measured result before identity refusal')\n"
        command = shlex.join([sys.executable, '-c', program])
    before_task = yaml.safe_load((root / 'current-task.yaml').read_text())
    result = cli('evidence', 'run', '--type', kind, '--command', command, *covered)
    if attack in {'budget', 'collision'}:
        assert result.returncode == 0, result.stdout + result.stderr
        receipts = [json.loads(p.read_text()) for p in (root / 'evidence').glob('*.json')]
        assert all(r['exit_code'] == 0 for r in receipts)
        task = yaml.safe_load((root / 'current-task.yaml').read_text())
        if attack == 'budget':
            assert task['iteration'] == 3, 'collector overwrote child current task fields'
            assert task['budget']['build_runs'] == task['budget']['test_runs'] == 1, 'collector lost child budget increment'
        else:
            assert hashlib.sha256((root / 'evidence/build.json').read_bytes()).hexdigest() == marker.read_text(), 'collector overwrote child receipt'
            assert len(list((root / 'evidence').glob('build*.json'))) == 2
            assert task['budget']['build_runs'] == 2
        return
    journals = list((root / '.transactions').glob('*.json'))
    if attack == 'pending-persist':
        assert len(journals) == 1 and json.loads(journals[0].read_text())['version'] == 2
        with telemetry_lock(root):
            recover_pending_publications(root)
    assert result.returncode == 2, 'collector accepted post-command pending/identity change: ' + result.stdout + result.stderr
    path, retained = retained_collector_result(result)
    assert not path.is_relative_to(root)
    assert not (root / 'evidence/build.json').exists()
    task = yaml.safe_load((root / 'current-task.yaml').read_text())
    assert task['budget'] == before_task['budget'], 'blocked collector wrote budget into changed task'
    assert task['task']['id'] == ('TASK-888' if attack == 'task-change' else 'TASK-777')
    assert 'measured result before' in retained['evidence']['stdout_tail']


@pytest.mark.parametrize('failure', ['nonzero', 'timeout', 'cancel', 'publish', 'cancel-publish'])
def test_collector_measured_failure_and_native_rollback(tmp_path, monkeypatch, capsys, failure):
    import json
    import shlex
    import sys
    from types import SimpleNamespace

    from test_test_scope import (
        assert_restored_with_retention,
        canonical_exchange_member,
        file_identities,
        tree_bytes,
    )

    from harness import publication_fs

    root, _, _ = collector_fixture(tmp_path, monkeypatch)
    before, identities = tree_bytes(root), file_identities(root)
    command = 'printf measured; exit 7' if failure == 'nonzero' else 'printf measured'
    if failure == 'timeout':
        original_collect = evidence_module._collect

        def short_timeout(*args, **kwargs):
            return original_collect(*args, **kwargs, timeout_seconds=.2)
        monkeypatch.setattr(evidence_module, '_collect', short_timeout)
        command = shlex.join([sys.executable, '-u', '-c', "import time; print('partial'); time.sleep(2)"])
    if failure.startswith('cancel'):
        def cancelled(*args, **kwargs):
            raise KeyboardInterrupt()
        monkeypatch.setattr(evidence_module.execution_capture, 'run_command', cancelled)
    observed = []
    if failure in {'publish', 'cancel-publish'}:
        original_exchange = publication_fs.exchange

        def fault(*args):
            result = original_exchange(*args)
            if canonical_exchange_member(root, args) == 'current-task.yaml' and not observed:
                observed.append('exchanged')
                assert (root / 'current-task.yaml').stat().st_ino != identities['current-task.yaml'][1]
                raise OSError('TEST_COLLECTOR_NATIVE_PUBLICATION_FAILURE')
            return result
        monkeypatch.setattr(publication_fs, 'exchange', fault)
    result = evidence_module.main(['--type', 'build', '--command', command])
    output = capsys.readouterr()
    expected = {'nonzero': 0, 'timeout': 0, 'cancel': 130, 'publish': 2, 'cancel-publish': 130}[failure]
    assert result == expected, output.out + output.err
    if observed:
        assert_restored_with_retention(root, before, identities)
        path, document = retained_collector_result(SimpleNamespace(stdout=output.out, stderr=output.err)) if failure == 'publish' else (None, None)
        if failure == 'cancel-publish':
            path = Path(output.err.split('EVIDENCE_RESULT_RETAINED: ', 1)[1].splitlines()[0])
            document = json.loads(path.read_text())
        assert document['accepted'] is False
        record = document['evidence']
    else:
        assert failure not in {'publish', 'cancel-publish'}, 'real native fault not reached'
        record = json.loads((root / 'evidence/build.json').read_text())
    assert record['exit_code'] == {'nonzero': 7, 'timeout': 124, 'cancel': 130, 'publish': 0, 'cancel-publish': 130}[failure]
    if failure == 'timeout':
        assert record['error'] == 'EVIDENCE_COMMAND_TIMEOUT' and 'partial' in record['stdout_tail']
    if failure.startswith('cancel'):
        assert record['error'] == 'EVIDENCE_COMMAND_CANCELLED'


@pytest.mark.parametrize('reuse', [False, True])
def test_collector_owner_segments_and_unlocked_child(tmp_path, monkeypatch, capsys, reuse):
    import builtins
    import subprocess
    import sys

    from test_publication_admission import assert_review_owner

    from harness import transaction

    root, _, cli = collector_fixture(tmp_path, monkeypatch)
    if reuse:
        assert cli('evidence', 'run', '--type', 'build', '--command', 'printf measured').returncode == 0
    original_run, original_task = subprocess.run, evidence_module._current_task
    original_command = evidence_module.execution_capture.run_command
    original_publish, original_print = transaction.publish, builtins.print
    observed = []

    def task(*args):
        assert_review_owner(root)
        observed.append('task')
        return original_task(*args)

    def run(*args, **kwargs):
        program = ('from pathlib import Path; from harness.telemetry_lock import telemetry_lock; '
                   f'\nwith telemetry_lock(Path({str(root)!r})): pass')
        probe = original_run([sys.executable, '-c', program],
                             env={**__import__('os').environ, 'PYTHONPATH': str(Path(evidence_module.__file__).resolve().parents[1])},
                             capture_output=True, text=True, timeout=5, check=False)
        assert probe.returncode == 0, probe.stdout + probe.stderr
        observed.append('child-unlocked')
        return original_command(*args, **kwargs)

    def publish(*args, **kwargs):
        assert_review_owner(root)
        observed.append('before-publish')
        value = original_publish(*args, **kwargs)
        assert_review_owner(root)
        observed.append('after-publish')
        return value

    def render(*args, **kwargs):
        if args and (str(args[0]).startswith('evidence written:') or str(args[0]).startswith('EVIDENCE_REUSED:')):
            assert_review_owner(root)
            observed.append('render')
        return original_print(*args, **kwargs)

    monkeypatch.setattr(evidence_module, '_current_task', task)
    monkeypatch.setattr(evidence_module.execution_capture, 'run_command', run)
    monkeypatch.setattr(transaction, 'publish', publish)
    monkeypatch.setattr(builtins, 'print', render)
    assert evidence_module.main(['--type', 'build', '--command', 'printf measured', *(['--reuse-if-valid'] if reuse else [])]) == 0
    assert 'render' in observed
    if reuse:
        assert 'child-unlocked' not in observed and 'before-publish' not in observed
    else:
        assert observed.count('task') == 2
        assert all(label in observed for label in ['child-unlocked', 'before-publish', 'after-publish'])
    capsys.readouterr()


@pytest.mark.parametrize('fault', ['unknown', 'task-symlink', 'evidence-symlink'])
def test_collector_invalid_preflight_never_executes(tmp_path, monkeypatch, capsys, fault):
    from test_test_scope import tree_bytes

    root, _, _ = collector_fixture(tmp_path, monkeypatch)
    if fault == 'unknown':
        (root / '.transactions').mkdir(exist_ok=True)
        (root / '.transactions/unknown-member').write_bytes(b'private bytes')
    else:
        name = 'current-task.yaml' if fault == 'task-symlink' else 'evidence'
        path = root / name
        destination = tmp_path.parent / (tmp_path.name + '-unmanaged')
        path.rename(destination)
        path.symlink_to(destination, target_is_directory=path.name == 'evidence')
    marker = tmp_path / 'must-not-execute'
    before = tree_bytes(root)
    assert evidence_module.main(['--type', 'build', '--command', f'touch {marker}']) == 2
    assert not marker.exists() and tree_bytes(root) == before
    assert capsys.readouterr().err


@pytest.mark.parametrize('phase', ['preflight', 'persist'])
def test_collector_owner_teardown_reports_real_commit_state(tmp_path, monkeypatch, capsys, phase):
    import fcntl
    import json

    from test_test_scope import tree_bytes

    root, _, _ = collector_fixture(tmp_path, monkeypatch)
    before = tree_bytes(root)
    original = fcntl.flock
    releases = []

    def teardown(fd, operation):
        result = original(fd, operation)
        if operation == fcntl.LOCK_UN:
            releases.append(fd)
            if len(releases) == (1 if phase == 'preflight' else 2):
                raise OSError('TEST_COLLECTOR_TEARDOWN_FAILURE')
        return result

    monkeypatch.setattr(fcntl, 'flock', teardown)
    assert evidence_module.main(['--type', 'build', '--command', 'printf once']) == 2
    output = capsys.readouterr()
    if phase == 'preflight':
        assert tree_bytes(root) == before
        assert 'evidence written:' not in output.out
    else:
        assert 'EVIDENCE_PERSISTENCE_UNCERTAIN' in output.err
        receipt = json.loads((root / 'evidence/build.json').read_text())
        assert receipt['exit_code'] == 0 and receipt['stdout_tail'] == 'once'
        path = Path(output.err.split('EVIDENCE_RESULT_RETAINED: ', 1)[1].splitlines()[0])
        assert json.loads(path.read_text())['evidence'] == receipt


@pytest.mark.parametrize('cancel,broken_warning,broken_retention', [
    (False, False, True), (False, True, False), (True, False, True), (True, True, False),
])
def test_collector_retention_warning_errors_preserve_refusal_or_cancel(tmp_path, monkeypatch, capsys, cancel, broken_warning, broken_retention):
    import builtins

    from test_test_scope import tree_bytes

    root, _, _ = collector_fixture(tmp_path, monkeypatch)
    before = tree_bytes(root)
    original_run, original_print = evidence_module.execution_capture.run_command, builtins.print

    def run(*args, **kwargs):
        if cancel:
            raise KeyboardInterrupt()
        return original_run(*args, **kwargs)

    def refused(*args, **kwargs):
        raise OSError('TRANSACTION_RECOVERY_REQUIRED: controlled post-command refusal')

    def warning(*args, **kwargs):
        if broken_warning and kwargs.get('file') is __import__('sys').stderr:
            raise OSError('TEST_WARNING_FAILURE')
        return original_print(*args, **kwargs)

    if broken_retention:
        def retain(*args):
            raise OSError('TEST_RETENTION_FAILURE')
        monkeypatch.setattr(evidence_module, '_retain_result', retain)
    monkeypatch.setattr(evidence_module, '_persist', refused)
    monkeypatch.setattr(evidence_module.execution_capture, 'run_command', run)
    monkeypatch.setattr(builtins, 'print', warning)
    assert evidence_module.main(['--type', 'build', '--command', 'printf measured']) == (130 if cancel else 2)
    assert tree_bytes(root) == before
    output = capsys.readouterr()
    if broken_retention:
        assert 'EVIDENCE_RESULT_RETENTION_FAILED' in output.err
        assert 'EVIDENCE_RESULT_RETAINED: ' not in output.err
    elif not broken_warning:
        assert 'EVIDENCE_RESULT_RETAINED: ' in output.err


@pytest.mark.parametrize('cancel', [False, True])
def test_collector_closed_warning_stream_keeps_primary_result(tmp_path, monkeypatch, cancel):
    import io
    import sys

    collector_fixture(tmp_path, monkeypatch)
    original = evidence_module.execution_capture.run_command

    def run(*args, **kwargs):
        if cancel:
            raise KeyboardInterrupt()
        return original(*args, **kwargs)

    def refused(*args):
        raise OSError('TRANSACTION_RECOVERY_REQUIRED: controlled refusal')

    closed = io.StringIO()
    closed.close()
    monkeypatch.setattr(evidence_module.execution_capture, 'run_command', run)
    monkeypatch.setattr(evidence_module, '_persist', refused)
    with monkeypatch.context() as stream:
        stream.setattr(sys, 'stderr', closed)
        assert evidence_module.main(['--type', 'build', '--command', 'printf measured']) == (130 if cancel else 2)


def test_collector_configured_tempdir_cannot_retain_inside_task(tmp_path, monkeypatch, capsys):
    import json
    import tempfile

    from test_test_scope import tree_bytes

    from harness.telemetry_lock import telemetry_lock

    root, _, _ = collector_fixture(tmp_path, monkeypatch)
    internal = root / '.configured-tempdir'
    internal.mkdir()

    def refused(*args):
        raise OSError('TRANSACTION_RECOVERY_REQUIRED: controlled refusal')

    monkeypatch.setattr(tempfile, 'tempdir', str(internal))
    # Existing owner locator also honors tempfile config; seed its empty lock.
    with telemetry_lock(root):
        pass
    before = tree_bytes(root)
    monkeypatch.setattr(evidence_module, '_persist', refused)
    assert evidence_module.main(['--type', 'build', '--command', 'printf measured']) == 2
    output = capsys.readouterr()
    path = Path(output.err.split('EVIDENCE_RESULT_RETAINED: ', 1)[1].splitlines()[0])
    assert not path.is_relative_to(root), 'configured TMPDIR stranded measured result inside task root'
    assert json.loads(path.read_text())['evidence']['stdout_tail'] == 'measured'
    assert tree_bytes(root) == before


@pytest.mark.parametrize('fault', ['no-external', 'unwritable', 'moved-inside'])
def test_collector_retention_location_errors_never_write_task(tmp_path, monkeypatch, fault):
    import tempfile

    root = tmp_path / '.harness'
    root.mkdir()
    if fault == 'no-external':
        root = Path('/')  # Every candidate lies inside root; refuse honestly.
    elif fault == 'unwritable':
        def blocked(*args, **kwargs):
            raise OSError('TEST_TEMPORARY_DIRECTORY_UNWRITABLE')
        monkeypatch.setattr(tempfile, 'mkdtemp', blocked)
    else:
        monkeypatch.setattr(tempfile, 'mkdtemp', lambda *args, **kwargs: str(root / 'moved'))
    with pytest.raises(OSError, match='EVIDENCE_RESULT_RETENTION_FAILED'):
        evidence_module._retain_result({'exit_code': 0}, 'controlled refusal', root)
    assert not list((tmp_path / '.harness').iterdir())


@pytest.mark.parametrize("broken_warning", [False, True])
@pytest.mark.parametrize("failure", ["stage", "cleanup"])
@pytest.mark.parametrize("cancel", [False, True])
def test_collector_postcommit_failure_preserves_measured_status_and_budget(
    tmp_path, monkeypatch, capsys, broken_warning, failure, cancel
):
    import errno
    import json
    import os

    import yaml

    from harness import publication_journal, transaction
    from harness.evidence_validator import ReuseRequest, can_reuse_evidence

    root, _, _ = collector_fixture(tmp_path, monkeypatch)
    command = "printf x >> .harness/command-runs"
    observed = []
    operations = []
    if broken_warning:
        import builtins

        real_print = builtins.print

        def print_without_warning(*args, **kwargs):
            if args and str(args[0]).startswith("EVIDENCE_PUBLICATION_COMMITTED"):
                raise OSError("TEST_WARNING_CLOSED")
            return real_print(*args, **kwargs)

        monkeypatch.setattr(builtins, "print", print_without_warning)
    if cancel:
        original_run = evidence_module.execution_capture.run_command

        def cancel_after_child(*args, **kwargs):
            result = original_run(*args, **kwargs)
            if args and args[0] == command:
                raise KeyboardInterrupt()
            return result

        monkeypatch.setattr(evidence_module.execution_capture, "run_command", cancel_after_child)

    def observe_committed():
        record = json.loads((root / "evidence/build.json").read_text())
        assert record["exit_code"] == (130 if cancel else 0)
        assert yaml.safe_load((root / "current-task.yaml").read_text())["budget"]["build_runs"] == 1
        assert not list((root / ".transactions").glob("*.json"))
        observed.append(failure)

    if failure == "stage":
        def fail_retention(*args, **kwargs):
            observe_committed()
            raise OSError(errno.ENOSPC, "TEST_STAGE_ARCHIVAL_NO_SPACE")

        monkeypatch.setattr(transaction, "_retain_stage", fail_retention)
    else:
        original_prepare, original_close = publication_journal.prepare, os.close

        def prepare(*args, **kwargs):
            operation = original_prepare(*args, **kwargs)
            assert operation.root == root.absolute()
            operations.append(operation)
            return operation

        def fail_cleanup(fd):
            operation = operations[-1] if operations else None
            inject = (
                operation is not None
                and fd == operation.fds.get("root")
                and operation.document["state"] == "COMMITTED"
                and not observed
            )
            original_close(fd)
            if inject:
                observe_committed()
                raise OSError(errno.EIO, "TEST_PUBLISHER_CLEANUP_FAILED")

        monkeypatch.setattr(publication_journal, "prepare", prepare)
        monkeypatch.setattr(os, "close", fail_cleanup)

    assert evidence_module.main(["--type", "build", "--command", command]) == (130 if cancel else 0)
    assert observed == [failure], "native postcommit fault was not reached exactly once"
    if failure == "cleanup":
        assert len(operations) == 1
        assert not operations[0].fds
    output = capsys.readouterr()
    assert ("EVIDENCE_PUBLICATION_COMMITTED" in output.err) is (not broken_warning)
    assert "EVIDENCE_PERSISTENCE_UNCERTAIN" not in output.err
    assert "PUBLICATION_FAILURE_CONTEXT" not in output.err
    assert "EVIDENCE_RESULT_RETAINED" not in output.err
    if cancel:
        record = json.loads((root / "evidence/build.json").read_text())
        assert record["error"] == "EVIDENCE_COMMAND_CANCELLED"
        current = evidence_module.snapshot(root.parent)
        request = ReuseRequest("build", command, "related", (), None, None, None)
        assert not can_reuse_evidence(
            record, request, current_head=current.head,
            current_workspace=current.fingerprint,
            current_runtime=evidence_module.runtime_metadata(),
        )
    else:
        assert evidence_module.main(["--type", "build", "--command", command, "--reuse-if-valid"]) == 0
        assert "EVIDENCE_REUSED" in capsys.readouterr().out
    assert (root / "command-runs").read_text() == "x"
    assert yaml.safe_load((root / "current-task.yaml").read_text())["budget"]["build_runs"] == 1
    assert list((root / "evidence").glob("build*.json")) == [root / "evidence/build.json"]


@pytest.mark.parametrize(
    "window", ["preflight", "before_fingerprint", "after_fingerprint"]
)
def test_collector_refuses_head_drift_in_identity_windows(
    tmp_path, monkeypatch, capsys, window
):
    import json
    import subprocess

    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True
        )

    git("init", "-q")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    product = tmp_path / "product.txt"
    product.write_text("tree A")
    git("add", "product.txt")
    git("commit", "-qm", "A")

    def advance():
        product.write_text("tree B")
        git("add", "product.txt")
        git("commit", "-qm", "B")

    if window == "preflight":
        original = evidence_module._preflight

        def preflight(*args):
            prepared = original(*args)
            advance()
            return prepared

        monkeypatch.setattr(evidence_module, "_preflight", preflight)
    else:
        original = evidence_module.snapshot
        calls = []

        def fingerprint():
            value = original()
            calls.append(value)
            if len(calls) == (1 if window == "before_fingerprint" else 2):
                advance()
            return value

        monkeypatch.setattr(evidence_module, "snapshot", fingerprint)

    result = main(["--type", "custom", "--command", "printf measured"])

    assert result == 2
    assert not list((tmp_path / ".harness/evidence").glob("*.json"))
    output = capsys.readouterr()
    assert "EVIDENCE_HEAD_MISMATCH" in output.err
    if window != "before_fingerprint":
        retained = Path(
            output.err.split("EVIDENCE_RESULT_RETAINED: ", 1)[1].splitlines()[0]
        )
        record = json.loads(retained.read_text())
        assert record["accepted"] is False
        assert record["evidence"]["stdout_tail"] == "measured"


def test_collector_rejects_snapshot_head_different_from_preflight(
    tmp_path, monkeypatch, capsys
):
    from types import SimpleNamespace

    monkeypatch.setattr(evidence_module, "git_head", lambda: "a" * 40)
    monkeypatch.setattr(
        evidence_module,
        "snapshot",
        lambda *_a: SimpleNamespace(head="b" * 40, fingerprint="sha256:" + "1" * 64),
    )
    result = main(
        [
            "--type",
            "custom",
            "--command",
            "printf measured",
            "--harness-dir",
            str(tmp_path / ".harness"),
        ]
    )
    assert result == 2
    assert "EVIDENCE_HEAD_MISMATCH" in capsys.readouterr().err
    assert not list((tmp_path / ".harness/evidence").glob("*.json"))

"""Storage diagnostics/plan output must not initialize or mutate runtime data."""
import json

import pytest
from test_context_builder import harness  # noqa: F401
from storage_factory import cli, identity, repository


def fixture_inputs(root, plan, maintenance):
    directory = root.parent.with_name(root.parent.name + '-storage-inputs')
    directory.mkdir(exist_ok=True)
    paths = directory / 'plan.json', directory / 'maintenance.json'
    for path, value in zip(paths, (plan, maintenance), strict=True):
        path.write_text(json.dumps(value))
    return paths


def test_cli_apply_requires_exact_fixture_grant_and_preserves_terminal_idempotence(harness):
    from harness.storage import StorageRequest, plan_operation
    from test_storage_activation import qualified_grant

    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision, maintenance = qualified_grant(harness, plan)
    paths = fixture_inputs(harness, plan, maintenance)
    args = ('storage', 'migrate', '--apply', '--file', str(paths[0]), '--decision', decision,
            '--maintenance-file', str(paths[1]), '--json')
    result = cli(harness.parent, *args, timeout=90)
    assert result.returncode == 0, result.stderr
    first = json.loads(result.stdout)
    assert first['status'] == 'COMMITTED'
    before = identity(harness.parent / '.harness-store')
    again = cli(harness.parent, *args, timeout=90)
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout) == first
    assert identity(harness.parent / '.harness-store') == before


def test_cli_partial_apply_reports_exact_coordinator_phase_without_auto_recovery(harness, monkeypatch, capsys):
    from harness.cli import main
    from harness.storage import StorageError, StorageRequest, plan_operation, recover_operation
    from harness.storage.journal import DirectoryOperation
    from test_storage_activation import qualified_grant
    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision, maintenance = qualified_grant(harness, plan)
    paths = fixture_inputs(harness, plan, maintenance)
    advance = DirectoryOperation.advance
    def fail_after_ack(operation, action):
        advance(operation, action)
        raise StorageError('STORE_PLAN_STALE')
    monkeypatch.chdir(harness.parent)
    with monkeypatch.context() as scoped:
        scoped.setattr(DirectoryOperation, 'advance', fail_after_ack)
        code = main(['storage', 'migrate', '--apply', '--file', str(paths[0]), '--decision', decision,
                     '--maintenance-file', str(paths[1])])
    assert code == 2
    error = capsys.readouterr().err
    reports = [json.loads(line) for line in error.splitlines() if line.startswith('{')]
    assert len(reports) == 1, error
    assert reports[0]['operation_id'] == plan['operation_id']
    assert reports[0]['phase'] == 'APPLYING'
    assert reports[0]['acknowledged_actions'] == 1
    assert reports[0]['coordinator'].startswith('.harness/.transactions/')
    assert (harness.parent / ('.harness-store-prepare-' + plan['operation_id'])).exists()
    assert recover_operation(harness.parent, plan['operation_id'])['status'] == 'ABORTED'


def test_cli_committed_apply_output_failure_reports_commit_without_rollback(harness, monkeypatch, capsys):
    import sys
    from harness.cli import main
    from harness.storage import StorageRequest, inspect_layout, plan_operation
    from test_storage_activation import qualified_grant

    plan = plan_operation(harness.parent, StorageRequest(kind='ACTIVATE'))
    decision, maintenance = qualified_grant(harness, plan)
    paths = fixture_inputs(harness, plan, maintenance)
    args = ['storage', 'migrate', '--apply', '--file', str(paths[0]), '--decision', decision,
            '--maintenance-file', str(paths[1]), '--json']
    class BrokenOutput:
        def write(self, value):
            raise OSError('fixture output unavailable')
        def flush(self):
            pass
    monkeypatch.chdir(harness.parent)
    with monkeypatch.context() as scoped:
        scoped.setattr(sys, 'stdout', BrokenOutput())
        code = main(args)
    assert code == 2
    error = capsys.readouterr().err
    assert 'COMMITTED' in error
    assert plan['operation_id'] in error
    assert inspect_layout(harness.parent).mode == 'bound'
    assert not list((harness.parent / '.harness-store/operations').iterdir())


@pytest.mark.parametrize('args', [('--apply',), ('--kind', 'ACTIVATE', '--apply', '--dry-run'),
                                 ('--kind', 'ACTIVATE', '--decision', 'DEC-001'),
                                 ('--kind', 'ACTIVATE', '--maintenance-file', 'missing.json')])
def test_cli_migration_modes_cannot_silently_change_dry_run_to_apply(tmp_path, args):
    repo = repository(tmp_path)
    before = tree(repo)
    result = cli(repo, 'storage', 'migrate', *args)
    assert result.returncode == 2
    assert tree(repo) == before
    assert not (repo / '.harness-store').exists()


def test_cli_apply_missing_or_symlink_input_is_safe_refusal(harness):
    inputs = harness.parent.with_name(harness.parent.name + '-bad-inputs')
    inputs.mkdir()
    private = inputs / 'PRIVATE_SOURCE'
    private.write_text('PRIVATE_PAYLOAD')
    link = inputs / 'plan.json'
    link.symlink_to(private)
    for path in [inputs / 'missing.json', link]:
        result = cli(harness.parent, 'storage', 'migrate', '--apply', '--file', str(path),
                     '--decision', 'DEC-001', '--maintenance-file', str(private))
        assert result.returncode == 2
        assert 'STORE_' in result.stderr
        assert 'PRIVATE' not in result.stdout + result.stderr
        assert not (harness.parent / '.harness-store').exists()


@pytest.mark.parametrize('payload', [b'{"kind":1,"kind":2}', b'{"value":NaN}', b'[]', b'PRIVATE_PAYLOAD', b'\xff'])
def test_cli_malformed_input_is_bounded_safe_refusal(harness, payload):
    directory = harness.parent.with_name(harness.parent.name + '-malformed')
    directory.mkdir()
    path = directory / 'input.json'
    path.write_bytes(payload)
    result = cli(harness.parent, 'storage', 'migrate', '--apply', '--file', str(path),
                 '--decision', 'DEC-001', '--maintenance-file', str(path))
    assert result.returncode == 2
    assert result.stderr.strip() == 'STORE_PLAN_STALE'
    assert 'PRIVATE' not in result.stdout + result.stderr
    assert not (harness.parent / '.harness-store').exists()


def test_cli_m2_request_file_previews_and_applies_only_explicit_selected_object(harness):
    from test_storage_migration import activate
    from test_storage_legacy_references import request
    from test_storage_lifecycle_integration import apply_cli

    activate(harness)
    old = harness / '.publication-retained/selected'
    old.mkdir(parents=True)
    (old / 'proof.json').write_bytes(b'original')
    spec = request(harness, old.relative_to(harness.parent).as_posix())
    directory = harness.parent.with_name(harness.parent.name + '-m2-input')
    directory.mkdir()
    file = directory / 'request.json'
    file.write_text(json.dumps({'sources': spec.sources}))
    preview = cli(harness.parent, 'storage', 'migrate', '--kind', 'M2', '--file', str(file), '--json')
    assert preview.returncode == 0, preview.stderr
    plan = json.loads(preview.stdout)
    assert plan['ready'] is True
    assert old.exists()
    before = identity(old)
    apply_cli(harness, plan)
    assert identity(harness.parent / plan['relocations'][0]['target']) == before


def tree(repo):
    return {str(p.relative_to(repo)): (p.stat().st_dev, p.stat().st_ino, p.read_bytes())
            for p in (repo / '.harness').rglob('*') if p.is_file()}


def test_storage_inspect_and_default_migrate_are_read_only(tmp_path):
    repo = repository(tmp_path)
    before = tree(repo)
    inspected = cli(repo, 'storage', 'inspect', '--json')
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)['mode'] == 'legacy'
    proposed = cli(repo, 'storage', 'migrate', '--kind', 'ACTIVATE', '--json')
    assert proposed.returncode == 0, proposed.stderr
    value = json.loads(proposed.stdout)
    assert value['kind'] == 'storage_plan'
    assert value['operation'] == 'ACTIVATE'
    assert value['ready'] is False  # Initialized, unclassified task cannot apply.
    assert tree(repo) == before
    assert not (repo / '.harness-store').exists()


def test_bounded_plan_preserves_fifo_and_reports_incomplete_without_writes(tmp_path):
    import os

    from harness.storage import StorageRequest, plan_operation

    repo = repository(tmp_path)
    history = repo / '.harness/history'
    history.mkdir(exist_ok=True)
    os.mkfifo(history / 'opaque-pipe')
    (history / 'too-large').write_bytes(b'x' * 128)
    before = (history / 'opaque-pipe').lstat().st_ino
    value = plan_operation(repo, StorageRequest(kind='ACTIVATE', max_bytes=64))
    assert value['ready'] is False
    assert value['qualification']['scan_complete'] is False
    scanned = plan_operation(repo, StorageRequest(kind='ACTIVATE', max_bytes=256))
    assert scanned['qualification']['unsafe_nodes'] is True
    assert scanned['qualification']['scan_complete'] is True
    assert (history / 'opaque-pipe').lstat().st_ino == before
    assert not (repo / '.harness-store').exists()


def test_wide_inventory_does_not_hold_one_fd_per_sibling(tmp_path):
    import os
    import subprocess
    import sys

    from storage_factory import ROOT

    repo = repository(tmp_path)
    history = repo / '.harness/history'
    history.mkdir(exist_ok=True)
    for number in range(150):
        (history / str(number)).mkdir()
    program = '''
import resource
from pathlib import Path
from harness.storage import StorageRequest,plan_operation
soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
resource.setrlimit(resource.RLIMIT_NOFILE,(min(96,soft),hard))
value=plan_operation(Path.cwd(),StorageRequest(kind='ACTIVATE'))
assert value['qualification']['scan_complete']
assert len(value['qualification']['entries']) >= 150
'''
    result = subprocess.run([sys.executable, '-B', '-c', program], cwd=repo,
                            env={**os.environ, 'PYTHONPATH': str(ROOT / 'src')},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert not (repo / '.harness-store').exists()


def test_plan_refuses_history_symlink_without_traceback_or_sensitive_payload(tmp_path):
    repo = repository(tmp_path)
    history = repo / '.harness/history'
    if history.exists():
        history.rename(history.with_name('preserved-history'))
    private = repo / 'PRIVATE_SOURCE'
    private.write_text('PRIVATE_PAYLOAD')
    history.symlink_to(private)
    before = history.lstat().st_ino
    result = cli(repo, 'storage', 'migrate', '--kind', 'ACTIVATE', '--dry-run', '--json')
    assert result.returncode == 2
    assert result.stderr.strip() == 'STORE_UNSAFE_NODE'
    assert 'PRIVATE' not in result.stdout + result.stderr
    assert history.lstat().st_ino == before
    assert private.read_text() == 'PRIVATE_PAYLOAD'


def test_explicit_storage_recover_restores_recorded_missing_root_without_init(tmp_path):
    from storage_factory import fixture_store, identity
    from storage_journal_factory import OP, turnover_plan
    from test_storage_kill_recovery import killed

    repo = repository(tmp_path)
    fixture_store(repo)
    before = identity(repo / '.harness')
    killed(repo, turnover_plan(repo), 'move')
    assert not (repo / '.harness').exists()
    result = cli(repo, 'storage', 'recover', OP)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'ABORTED'
    assert identity(repo / '.harness') == before


def test_storage_prune_apply_is_not_a_migration_mode(tmp_path):
    repo = repository(tmp_path)
    before = tree(repo)
    result = cli(repo, 'storage', 'migrate', '--kind', 'DELETE', '--apply')
    assert result.returncode == 2
    assert tree(repo) == before
    assert not (repo / '.harness-store').exists()

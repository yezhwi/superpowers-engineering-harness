"""A bound task route must never fall back to legacy history-copy turnover."""
import os
import yaml
import pytest
from test_context_builder import harness  # noqa: F401
from test_storage_migration import activate
from storage_factory import cli, fixture_store, identity, repository


def test_bound_new_and_recover_archive_once_without_history_copy(harness):
    from harness.storage import inspect_layout

    activate(harness)
    task_path = harness / 'current-task.yaml'
    old = yaml.safe_load(task_path.read_bytes())
    old['state'] = 'DONE'  # Test input, not a transition of implementation TASK-117.
    task_path.write_text(yaml.safe_dump(old))
    original_root = identity(harness)
    result = cli(harness.parent, 'task', 'new', 'TASK-029', '--title', 'bound new', timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert yaml.safe_load(task_path.read_bytes())['task']['id'] == 'TASK-029'
    store = harness.parent / '.harness-store'
    first = next((store / 'history/archives').iterdir())
    first_identity = identity(first)
    assert identity(next((store / 'retained/roots').glob('*/previous'))) == original_root
    assert not (harness / 'history').exists() or not list((harness / 'history').iterdir())
    recovered = cli(harness.parent, 'task', 'recover', 'TASK-030', '--reason', 'fixture recovery', timeout=90)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    assert len(list((store / 'history/archives').iterdir())) == 2
    assert identity(first) == first_identity
    assert inspect_layout(harness.parent).mode == 'bound'
    assert yaml.safe_load(task_path.read_bytes())['state'] == 'CREATED'
    baseline = yaml.safe_load((harness / 'test-scope-baseline.yaml').read_bytes())
    assert baseline['task_id'] == 'TASK-030'


def test_turnover_reader_pins_candidate_builder_and_genesis_sources():
    from harness.storage.migration import reader_identity

    assert {'storage/turnover.py', '_scope_replay.py', 'controlplane.py', 'init.py',
            'templates.py'} <= set(reader_identity()['modules'])


@pytest.mark.parametrize('missing', ['activation_operation_id', 'operation_id'])
def test_turnover_requires_committed_activation_and_generation_policy(harness, missing):
    activate(harness)
    path = (harness.parent / '.harness-store/store.yaml' if missing == 'activation_operation_id'
            else harness / 'storage-binding.yaml')
    value = yaml.safe_load(path.read_bytes())
    del value[missing]
    path.write_text(yaml.safe_dump(value))
    before = identity(harness), (harness / 'current-task.yaml').read_bytes()
    result = cli(harness.parent, 'task', 'recover', 'TASK-029', '--reason', 'test')
    assert result.returncode == 2
    assert 'STORE_READER_UNSUPPORTED' in result.stderr
    assert (identity(harness), (harness / 'current-task.yaml').read_bytes()) == before
    store = harness.parent / '.harness-store'
    assert not list((store / 'history/archives').iterdir())
    assert not list((store / 'operations').iterdir())


@pytest.mark.parametrize('mutation', ['namespace', 'product', 'template'])
def test_turnover_rechecks_selected_policy_namespace_before_commit(harness, monkeypatch, mutation):
    from harness.storage import StorageError
    from harness.storage.journal import DirectoryOperation
    from harness.storage.turnover import replace_bound_task
    from harness import workspace
    from harness.task_replacement import trusted_architecture_mode

    activate(harness)
    task = yaml.safe_load((harness / 'current-task.yaml').read_bytes())
    import shutil
    from harness.storage import turnover
    local_templates = harness.parent.with_name(harness.parent.name + '-templates')
    shutil.copytree(turnover.templates_dir(), local_templates)
    monkeypatch.setattr(turnover, 'templates_dir', lambda: local_templates)
    advance = DirectoryOperation.advance

    def late_file(operation, action):
        result = advance(operation, action)
        if action['kind'] == 'move' and action['source'] == '.harness':
            if mutation == 'namespace':
                path = harness.parent / action['target'] / 'decisions/late-policy.txt'
            elif mutation == 'product':
                path = harness.parent / 'late-product.txt'
            else:
                path = local_templates / 'gate.yaml'
            with path.open('a') as stream:
                stream.write('\n# late source mutation\n')
        return result

    monkeypatch.setattr(DirectoryOperation, 'advance', late_file)
    code = None
    try:
        replace_bound_task(harness, task, 'TASK-029', '', 'RECOVER', workspace.git_head(harness.parent),
                           trusted_architecture_mode(harness, task), 'fixture')
    except StorageError as error:
        code = error.code
    assert code == 'STORE_PLAN_STALE', code


def test_twenty_bound_turnovers_keep_flat_roots_and_first_archive_inode(harness):
    activate(harness)
    store = harness.parent / '.harness-store'
    policy_before = {p.name: p.read_bytes() for p in (harness / 'decisions').iterdir()}
    first = first_id = None
    bootstrap_root = identity(harness)
    for cycle in range(20):
        marker = harness / 'evidence' / f'cycle-{cycle}.txt'
        marker.write_text(f'owned by cycle {cycle}')
        new_id = f'TASK-{29 + cycle:03d}'
        task = yaml.safe_load((harness / 'current-task.yaml').read_bytes())
        previous_id = task['task']['id']
        if cycle % 2 == 0:
            task['state'] = 'DONE'  # Construct input, not Gate proof.
            (harness / 'current-task.yaml').write_text(yaml.safe_dump(task))
            args = ('new', new_id)
        else:
            args = ('recover', new_id, '--reason', 'bounded cycle fixture')
        old_id = identity(harness)
        fd = os.open(harness, os.O_RDONLY | os.O_DIRECTORY)
        try:
            result = cli(harness.parent, 'task', *args, timeout=90)
            assert result.returncode == 0, (cycle, result.stdout, result.stderr)
            file = os.open('current-task.yaml', os.O_RDONLY, dir_fd=fd)
            try:
                assert yaml.safe_load(os.read(file, 1024 * 1024))['task']['id'] == previous_id
            finally:
                os.close(file)
        finally:
            os.close(fd)
        roots = list((store / 'retained/roots').glob('*/previous'))
        assert old_id in [identity(root) for root in roots]
        assert len(roots) == cycle + 1
        # Original bootstrap contains legitimate v2 receipts. Preserve, never erase them.
        generated = [root for root in roots if identity(root) != bootstrap_root]
        assert all(not (root / '.publication-retained').exists() for root in generated)
        assert all(not (root / '.staging').exists() for root in generated)
        assert all(len(root.relative_to(store / 'retained/roots').parts) == 2 for root in roots)
        assert not list((harness / 'history').iterdir())
        archives = list((store / 'history/archives').iterdir())
        assert len(archives) == cycle + 1
        assert sum((root / f'evidence/cycle-{cycle}.txt').exists() for root in archives) == 1
        assert not list((harness / 'evidence').iterdir())
        assert {p.name: p.read_bytes() for p in (harness / 'decisions').iterdir()} == policy_before
        if first is None:
            first = archives[0]
            first_id = identity(first)
        assert identity(first) == first_id


def test_unknown_pending_never_allows_task_turnover(tmp_path):
    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    (store / "operations/unknown.json").write_text("{}")
    task = repo / ".harness/current-task.yaml"
    before = task.read_bytes()
    result = cli(repo, "task", "new", "TASK-901")
    assert result.returncode == 2
    assert "STORE_RECOVERY_REQUIRED" in result.stderr
    assert task.read_bytes() == before

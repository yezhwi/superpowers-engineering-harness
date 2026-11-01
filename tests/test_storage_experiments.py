"""Reclamation preview is not a destructive command or an ownership inference."""
import json
import pytest
import yaml
from storage_factory import cli, fixture_store, identity, repository
from storage_experiment_factory import experiment


def test_manifest_runtime_classification_is_read_only_and_never_delete_permission(tmp_path):
    repo = repository(tmp_path)
    fixture_store(repo)
    manifest, obj, path = experiment(repo)
    before = identity(obj), obj.read_bytes(), path.read_bytes(), (repo / '.harness/current-task.yaml').read_bytes()
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['objects'][0]['category'] == 'runtime'
    assert report['objects'][0]['status'] == 'runtime_review_only'
    assert report['objects'][0]['deletion_authorized'] is False
    assert report['deletion_authorized'] is False
    assert report['candidates'] == []
    assert report['freed_bytes'] == 0
    assert report['physical_savings_estimate'] is None
    assert (identity(obj), obj.read_bytes(), path.read_bytes(), (repo / '.harness/current-task.yaml').read_bytes()) == before
    assert not (repo / '.harness/context').exists()


@pytest.mark.parametrize('category', ['inputs', 'results', 'opaque'])
def test_nonruntime_objects_stay_retained_even_if_named_venv(tmp_path, category):
    repo = repository(tmp_path)
    fixture_store(repo)
    _, obj, _ = experiment(repo, category=category)
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)['objects'][0]
    assert row['category'] == category
    assert row['status'] == 'retained'
    assert obj.exists()


@pytest.mark.parametrize('damage', ['missing-rebuild', 'member-inode', 'source-task', 'must-keep', 'unknown-scope', 'missing-environment', 'blank-command', 'dynamic-reference', 'live-reference'])
def test_runtime_missing_qualification_never_becomes_review_candidate(tmp_path, damage):
    repo = repository(tmp_path)
    fixture_store(repo)
    manifest, obj, path = experiment(repo)
    if damage == 'missing-rebuild':
        del manifest['objects'][0]['rebuild']
    elif damage == 'member-inode':
        replacement = obj.with_suffix('.new')
        replacement.write_bytes(obj.read_bytes())
        replacement.replace(obj)
    elif damage == 'source-task':
        manifest['source_task']['sha256'] = '0' * 64
    elif damage == 'must-keep':
        manifest['must_keep'] = [{'path': manifest['objects'][0]['path'], 'reason': 'retain original replay'}]
    elif damage == 'dynamic-reference':
        manifest['must_keep'] = [{'path': '${UNRESOLVED_RUNTIME}', 'reason': 'dynamic reference'}]
    elif damage == 'live-reference':
        impact_path = repo / '.harness/impact.yaml'
        impact = yaml.safe_load(impact_path.read_bytes())
        impact['impact']['contracts'] = [{'kind': 'generic', 'ref': manifest['objects'][0]['path']}]
        impact_path.write_text(yaml.safe_dump(impact))
    elif damage == 'missing-environment':
        del manifest['environment_identity']
    elif damage == 'blank-command':
        manifest['objects'][0]['rebuild']['command'] = '   '
    else:
        manifest['reference_scope'] = 'unknown'
    path.write_text(yaml.safe_dump(manifest))
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert all(row['status'] != 'runtime_review_only' for row in report['objects'])
    assert report['deletion_authorized'] is False


def test_unmanifested_experiment_directory_is_unknown_not_runtime(tmp_path):
    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    unknown = store / 'experiments/venv'
    unknown.mkdir()
    (unknown / 'python').write_bytes(b'same binaries prove nothing')
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['objects'][0]['status'] == 'unknown'
    assert report['objects'][0]['logical_bytes'] is None
    assert unknown.exists()


def test_empty_lsof_output_never_qualifies_cleanup(tmp_path, monkeypatch):
    import subprocess
    from harness.storage import admit_storage
    from harness.storage.experiments import classify_candidates, _DEFAULT_LIMITS

    repo = repository(tmp_path)
    fixture_store(repo)
    manifest, _, _ = experiment(repo)
    manifest['reference_scope'] = 'unknown'
    def no_process_inference(*args, **kwargs):
        raise AssertionError('process listing/lsof cannot grant cleanup')
    monkeypatch.setattr(subprocess, 'run', no_process_inference)
    with admit_storage(repo / '.harness') as session:
        report = classify_candidates(session, (manifest,), dict(_DEFAULT_LIMITS))
    assert report['candidates'] == []
    assert report['objects'][0]['status'] != 'runtime_review_only'
    assert report['deletion_authorized'] is False


def test_read_only_candidate_command_does_not_update_task_or_context(tmp_path):
    repo = repository(tmp_path)
    fixture_store(repo)
    experiment(repo)
    context = repo / '.harness/context'
    context.mkdir()
    (context / 'current.yaml').write_bytes(b'untouched saved context fixture')
    files = [repo / '.harness/current-task.yaml', context / 'current.yaml']
    before = [(identity(path), path.read_bytes()) for path in files]
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    assert [(identity(path), path.read_bytes()) for path in files] == before


def test_equal_binary_hashes_do_not_merge_or_reclassify_inputs(tmp_path):
    repo = repository(tmp_path)
    fixture_store(repo)
    manifest, obj, path = experiment(repo)
    other = obj.with_name('input-binary')
    other.write_bytes(obj.read_bytes())
    manifest['objects'].append({**manifest['objects'][0], 'category': 'inputs',
                                'path': other.relative_to(repo).as_posix(), 'identity': identity(other)})
    path.write_text(yaml.safe_dump(manifest))
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert [row['status'] for row in report['objects']] == ['runtime_review_only', 'retained']
    assert report['logical_bytes'] == len(obj.read_bytes()) * 2
    assert report['candidates'] == []


def test_archived_active_task_blocks_runtime_review_even_with_rebuild_recipe(tmp_path):
    repo = repository(tmp_path)
    fixture_store(repo)
    experiment(repo, task_state='CREATED')
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['objects'][0]['status'] == 'retained'
    assert report['candidates'] == []


def test_migration_grant_in_manifest_is_not_cleanup_authority(tmp_path):
    repo = repository(tmp_path)
    fixture_store(repo)
    manifest, _, path = experiment(repo)
    manifest['storage_authorization'] = {'operation': 'M2', 'status': 'ACCEPTED'}
    path.write_text(yaml.safe_dump(manifest))
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['deletion_authorized'] is False
    assert report['objects'][0]['status'] == 'unknown'


def test_candidate_command_blocks_pending_before_reading_manifest(tmp_path):
    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    (store / 'operations/unknown.json').write_bytes(b'unknown directory coordination')
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 2
    assert 'STORE_RECOVERY_REQUIRED' in result.stderr
    assert result.stdout == ''


def test_quarantine_is_not_reported_as_freed_bytes(tmp_path):
    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    (store / 'quarantine').mkdir(exist_ok=True)
    (store / 'quarantine/preserved.bin').write_bytes(b'not freed')
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['freed_bytes'] == 0
    assert report['physical_savings_estimate'] is None
    assert '.harness-store/quarantine' in report['protected_namespaces']


@pytest.mark.parametrize('unsafe', ['fifo', 'symlink', 'hardlink'])
def test_special_and_linked_nodes_are_unknown_and_never_opened(tmp_path, unsafe):
    import os
    repo = repository(tmp_path)
    fixture_store(repo)
    _, obj, _ = experiment(repo)
    if unsafe == 'hardlink':
        os.link(obj, obj.with_suffix('.other'))
    else:
        obj.unlink()
        if unsafe == 'fifo':
            os.mkfifo(obj)
        else:
            obj.symlink_to('/never-followed')
    result = cli(repo, 'storage', 'prune', '--dry-run', '--json')
    assert result.returncode == 0, result.stderr
    row = json.loads(result.stdout)['objects'][0]
    assert row['status'] == 'unknown'
    assert row['logical_bytes'] is None


@pytest.mark.parametrize('cap', [None, 'max_depth', 'max_nodes'])
def test_fifty_five_level_tree_is_bounded_and_hash_qualified(tmp_path, cap):
    from harness.storage import admit_storage
    from harness.storage.experiments import classify_candidates, _DEFAULT_LIMITS
    from storage_experiment_factory import directory_experiment
    repo = repository(tmp_path)
    fixture_store(repo)
    manifest, _, _ = directory_experiment(repo)
    limits = dict(_DEFAULT_LIMITS)
    if cap:
        limits[cap] = 5
    with admit_storage(repo / '.harness') as session:
        report = classify_candidates(session, (manifest,), limits)
    assert report['scan_complete'] is (cap is None)
    assert report['objects'][0]['status'] == ('unknown' if cap else 'runtime_review_only')
    assert report['logical_bytes'] == (0 if cap else len(b'fixture'))
    assert report['freed_bytes'] == 0


def test_device_change_is_unknown_without_opening_object(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace
    from harness.storage import admit_storage
    from harness.storage import experiments
    repo = repository(tmp_path)
    fixture_store(repo)
    manifest, _, _ = experiment(repo)
    original = os.stat
    def changed_device(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == 'venv' and kwargs.get('dir_fd') is not None:
            return SimpleNamespace(st_dev=info.st_dev + 1, st_ino=info.st_ino)
        return info
    with admit_storage(repo / '.harness') as session:
        monkeypatch.setattr(os, 'stat', changed_device)
        report = experiments.classify_candidates(session, (manifest,), dict(experiments._DEFAULT_LIMITS))
    assert report['objects'][0]['status'] == 'unknown'
    assert report['logical_bytes'] == 0


@pytest.mark.parametrize('limits', [{}, {'max_nodes': True}, {'max_bytes': 0}, {'max_manifests': 129}])
def test_invalid_scan_limits_refuse_before_classification(tmp_path, limits):
    from harness.storage import StorageError, admit_storage
    from harness.storage.experiments import classify_candidates, _DEFAULT_LIMITS
    repo = repository(tmp_path)
    fixture_store(repo)
    value = {} if not limits else {**_DEFAULT_LIMITS, **limits}
    with admit_storage(repo / '.harness') as session, pytest.raises(StorageError, match='STORE_UNSAFE_NODE'):
        classify_candidates(session, (), value)


def test_byte_budget_reports_incomplete_not_empty_success(tmp_path):
    from harness.storage import admit_storage
    from harness.storage.experiments import classify_candidates, _DEFAULT_LIMITS
    repo = repository(tmp_path)
    fixture_store(repo)
    manifest, _, _ = experiment(repo)
    with admit_storage(repo / '.harness') as session:
        report = classify_candidates(session, (manifest,), {**_DEFAULT_LIMITS, 'max_bytes': 1})
    assert report['scan_complete'] is False
    assert report['objects'][0]['status'] == 'unknown'
    assert report['freed_bytes'] == 0


def test_nested_declarations_are_not_counted_twice(tmp_path):
    from harness.storage import admit_storage
    from harness.storage.experiments import classify_candidates, _DEFAULT_LIMITS
    repo = repository(tmp_path)
    fixture_store(repo)
    manifest, obj, _ = experiment(repo)
    manifest['objects'].append({**manifest['objects'][0], 'path': obj.relative_to(repo).as_posix() + '/nested'})
    with admit_storage(repo / '.harness') as session:
        report = classify_candidates(session, (manifest,), dict(_DEFAULT_LIMITS))
    assert report['logical_bytes'] == 0
    assert report['candidates'] == []
    assert all(row['status'] == 'unknown' for row in report['objects'])


def test_reader_identity_pins_actual_experiment_classifier():
    from harness.storage.migration import reader_identity
    assert 'storage/experiments.py' in reader_identity()['modules']


def test_storage_prune_has_no_destructive_apply_route(tmp_path):
    repo = repository(tmp_path)
    fixture_store(repo)
    result = cli(repo, "storage", "prune", "--apply")
    assert result.returncode == 2
    assert "--apply" in result.stderr

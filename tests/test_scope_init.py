"""Fresh initialization and genesis identity binding preserve actual initial scope."""

import importlib
import shutil

import pytest
import yaml

from harness import publication_fs
from harness.init import init_harness
from harness.templates import templates_dir

SCOPE_FILES = ('test-scope-baseline.yaml', 'test-scope-audit.yaml', 'test-scope-seal.yaml')


def bytes_tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('initial', [[], ['tests/test_initial.py::test_ok']])
def test_fresh_init_seals_actual_initial_set_including_custom_template(tmp_path, initial):
    custom = tmp_path / 'templates'
    shutil.copytree(templates_dir(), custom)
    (custom / 'impact.yaml').write_text(yaml.safe_dump({'impact': {'changed': [], 'required_tests': initial}}))
    init_harness(tmp_path, custom)
    root = tmp_path / '.harness'
    baseline = yaml.safe_load((root / SCOPE_FILES[0]).read_text())
    assert baseline['task_id'] is None
    assert baseline['required_tests'] == initial
    assert all((root / name).is_file() for name in SCOPE_FILES)
    before = bytes_tree(root)
    init_harness(tmp_path, custom)
    assert bytes_tree(root) == before


def test_fresh_init_fault_leaves_zero_partial_canonical_files(tmp_path, monkeypatch):
    original = publication_fs.move_noreplace
    failed = False
    def fail_seal_once(*args):
        nonlocal failed
        if args[3] == SCOPE_FILES[2] and not failed:
            failed = True
            raise OSError('injected genesis publication failure')
        return original(*args)
    monkeypatch.setattr(publication_fs, 'move_noreplace', fail_seal_once)
    with pytest.raises(OSError, match='injected genesis publication failure'):
        init_harness(tmp_path)
    assert failed
    root = tmp_path / '.harness'
    # No partial canonical files; immutable recovery/input retention is expected.
    assert not {name: content for name, content in bytes_tree(root).items()
                if name.split('/')[0] not in {'.staging', '.transactions', '.publication-retained'}}
    assert not list((root / '.transactions').iterdir())


def test_existing_impact_cannot_be_blessed_as_new_task_origin(tmp_path):
    root = tmp_path / '.harness'
    root.mkdir()
    (root / 'impact.yaml').write_text('impact: {changed: [], required_tests: [current_subset.py]}\n')
    original = (root / 'impact.yaml').read_bytes()
    init_harness(tmp_path)
    assert (root / 'impact.yaml').read_bytes() == original
    assert not any((root / name).exists() for name in SCOPE_FILES)


def test_genesis_identity_bind_preserves_set_and_rejects_reassignment(tmp_path):
    scope = importlib.import_module('harness.test_scope')
    assert hasattr(scope, 'bind_scope_identity'), 'genesis bind missing'
    init_harness(tmp_path)
    root = tmp_path / '.harness'
    scope.bind_scope_identity(root, 'TASK-777')
    for name in (*SCOPE_FILES, 'current-task.yaml'):
        data = yaml.safe_load((root / name).read_text())
        assert (data['task']['id'] if name == 'current-task.yaml' else data['task_id']) == 'TASK-777'
    before = bytes_tree(root)
    with pytest.raises(ValueError, match='TEST_SCOPE_'):
        scope.bind_scope_identity(root, 'TASK-888')
    assert bytes_tree(root) == before


def test_identity_bind_refuses_changed_initial_scope(tmp_path):
    scope = importlib.import_module('harness.test_scope')
    assert hasattr(scope, 'bind_scope_identity'), 'genesis bind missing'
    init_harness(tmp_path)
    root = tmp_path / '.harness'
    (root / 'impact.yaml').write_text('impact: {changed: [], required_tests: [untrusted.py]}\n')
    before = bytes_tree(root)
    with pytest.raises(ValueError, match='TEST_SCOPE_'):
        scope.bind_scope_identity(root, 'TASK-777')
    assert bytes_tree(root) == before


@pytest.mark.parametrize('boundary', ['before', 'after'])
def test_identity_bind_failure_rolls_back_entire_genesis(tmp_path, monkeypatch, boundary):
    from test_test_scope import (
        assert_restored_with_retention,
        canonical_exchange_member,
        file_identities,
    )

    scope = importlib.import_module('harness.test_scope')
    assert hasattr(scope, 'bind_scope_identity'), 'genesis bind missing'
    init_harness(tmp_path)
    root = tmp_path / '.harness'
    before, identities = bytes_tree(root), file_identities(root)
    original = publication_fs.exchange
    observed = []

    def reject(*args):
        if canonical_exchange_member(root, args) == 'current-task.yaml' and not observed:
            observed.append(boundary)
            if boundary == 'after':
                original(*args)
                assert (root / 'current-task.yaml').stat().st_ino != identities['current-task.yaml'][1]
            raise OSError('injected bind publication failure')
        return original(*args)

    with monkeypatch.context() as fault:
        fault.setattr(publication_fs, 'exchange', reject)
        with pytest.raises(OSError, match='injected bind publication failure'):
            scope.bind_scope_identity(root, 'TASK-777')
    assert observed == [boundary], 'native canonical bind fault was not reached'
    assert_restored_with_retention(root, before, identities)
    assert yaml.safe_load((root / 'current-task.yaml').read_text())['task']['id'] is None
    scope.bind_scope_identity(root, 'TASK-777')
    assert yaml.safe_load((root / 'current-task.yaml').read_text())['task']['id'] == 'TASK-777'
    assert yaml.safe_load((root / SCOPE_FILES[0]).read_text())['required_tests'] == []

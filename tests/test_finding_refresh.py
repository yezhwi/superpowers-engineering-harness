"""FIXED proof maintenance never advances finding/task lifecycle or edits receipts."""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from test_finding_transition import cli, setup

from harness import controlplane, transaction
from harness.collect_evidence import workspace_fingerprint


@pytest.fixture
def fixed(tmp_path):
    h = setup(tmp_path)
    task_path = h / 'current-task.yaml'
    task = yaml.safe_load(task_path.read_text())
    task['task']['id'] = 'TASK-001'
    task_path.write_text(yaml.safe_dump(task))
    for state, args in (
        ('REPRODUCING', ('--attempt', 'fixture RED')),
        ('CONFIRMED', ('--test', 'tests/test_x.py::test_x', '--evidence', 'red.json')),
        ('FIXING', ()), ('FIXED', ('--evidence', 'green.json')),
    ):
        result = cli(tmp_path, 'finding', 'transition', 'FND-001', state, *args)
        assert result.returncode == 0, result.stderr
    finding_path = h / 'findings/fnd-001.yaml'
    finding = yaml.safe_load(finding_path.read_text())
    finding['task_id'] = 'TASK-001'
    finding_path.write_text(yaml.safe_dump(finding))
    (tmp_path / 'product_edit.py').write_text('changed_product = True\n')
    record = json.loads((h / 'evidence/green.json').read_text())
    record['workspace_fingerprint'] = workspace_fingerprint(tmp_path)
    record['workspace_fingerprint_after'] = record['workspace_fingerprint']
    (h / 'evidence/fresh.json').write_text(json.dumps(record))
    return h


def tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


def refresh(root, reference='fresh.json'):
    return cli(root.parent, 'finding', 'refresh-proof', 'FND-001', '--evidence', reference)


def test_refresh_fixed_keeps_history_receipts_and_status(fixed):
    path = fixed / 'findings/fnd-001.yaml'
    original = yaml.safe_load(path.read_text())
    receipts = tree(fixed / 'evidence')
    task = (fixed / 'current-task.yaml').read_bytes()
    result = refresh(fixed)
    assert result.returncode == 0, result.stderr
    updated = yaml.safe_load(path.read_text())
    expected = copy.deepcopy(original)
    expected['regression_test']['green_evidence'] = 'fresh.json'
    history = updated['regression_test'].pop('green_evidence_history')
    assert updated == expected
    assert len(history) == 1
    assert history[0]['previous'] == 'green.json'
    assert history[0]['current'] == 'fresh.json'
    assert history[0]['refreshed_at']
    assert tree(fixed / 'evidence') == receipts
    assert (fixed / 'current-task.yaml').read_bytes() == task
    before = tree(fixed)
    repeat = refresh(fixed)
    assert repeat.returncode == 0, repeat.stderr
    assert tree(fixed) == before, 'same fresh reference is byte-idempotent including runtime retention'


@pytest.mark.parametrize('variant', ['failed', 'wrong_finding', 'wrong_test', 'wrong_head',
                                     'stale', 'changed_during_execution', 'missing', 'outside', 'wrong_task',
                                     'missing_task', 'receipt_task'])
def test_bad_refresh_proof_changes_no_canonical_or_runtime_bytes(fixed, variant):
    record_path = fixed / 'evidence/fresh.json'
    record = json.loads(record_path.read_text())
    reference = 'fresh.json'
    if variant == 'failed':
        record['exit_code'] = 1
    elif variant == 'wrong_finding':
        record['subject']['id'] = 'FND-999'
    elif variant == 'wrong_test':
        record['test']['node_id'] = 'tests/other.py::test_other'
    elif variant == 'wrong_head':
        record['commit'] = '0' * 40
    elif variant == 'stale':
        record['workspace_fingerprint'] = record['workspace_fingerprint_after'] = 'old'
    elif variant == 'changed_during_execution':
        record['workspace_fingerprint_after'] = 'different'
    elif variant == 'missing':
        reference = 'missing.json'
    elif variant == 'outside':
        outside = fixed.parent / 'outside.json'
        outside.write_text(json.dumps(record))
        reference = str(outside)
    elif variant == 'receipt_task':
        record['task_id'] = 'TASK-999'
    elif variant == 'missing_task':
        path = fixed / 'findings/fnd-001.yaml'
        finding = yaml.safe_load(path.read_text())
        finding.pop('task_id')
        path.write_text(yaml.safe_dump(finding))
    elif variant == 'wrong_task':
        path = fixed / 'findings/fnd-001.yaml'
        finding = yaml.safe_load(path.read_text())
        finding['task_id'] = 'TASK-999'
        path.write_text(yaml.safe_dump(finding))
    record_path.write_text(json.dumps(record))
    before = tree(fixed)
    result = refresh(fixed, reference)
    assert result.returncode != 0
    assert tree(fixed) == before


@pytest.mark.parametrize('status', ['PROPOSED', 'REPRODUCING', 'CONFIRMED', 'FIXING', 'VERIFIED', 'CLOSED', 'REJECTED'])
def test_refresh_rejects_other_lifecycle_states(fixed, status):
    path = fixed / 'findings/fnd-001.yaml'
    finding = yaml.safe_load(path.read_text())
    finding['status'] = status
    path.write_text(yaml.safe_dump(finding))
    before = tree(fixed)
    assert refresh(fixed).returncode != 0
    assert tree(fixed) == before


@pytest.mark.parametrize('change', ['category', 'test_mismatch', 'missing_red', 'failed_old_green', 'malformed_history', 'duplicate_id'])
def test_refresh_requires_valid_existing_authority(fixed, change):
    path = fixed / 'findings/fnd-001.yaml'
    finding = yaml.safe_load(path.read_text())
    if change == 'category':
        finding['category'] = 'alignment'
    elif change == 'test_mismatch':
        finding['test'] = 'tests/other.py::test_other'
    elif change == 'missing_red':
        (fixed / 'evidence/red.json').unlink()
    elif change == 'failed_old_green':
        old = fixed / 'evidence/green.json'
        record = json.loads(old.read_text())
        record['exit_code'] = 1
        old.write_text(json.dumps(record))
    elif change == 'malformed_history':
        finding['regression_test']['green_evidence_history'] = [{'previous': 'green.json'}]
    else:
        (fixed / 'findings/duplicate.yaml').write_text(yaml.safe_dump(finding))
    path.write_text(yaml.safe_dump(finding))
    before = tree(fixed)
    assert refresh(fixed).returncode != 0
    assert tree(fixed) == before


def test_pending_refresh_refuses_without_recovery(fixed):
    pending = fixed / '.transactions/unknown.json'
    pending.write_bytes(b'unknown user journal')
    before = tree(fixed)
    result = refresh(fixed)
    assert result.returncode != 0
    assert 'TRANSACTION_RECOVERY_' in result.stderr
    assert tree(fixed) == before


@pytest.mark.parametrize('source', ['task', 'receipt', 'product'])
def test_refresh_rechecks_sources_inside_transaction(fixed, monkeypatch, source):
    monkeypatch.chdir(fixed.parent)
    path = fixed / 'findings/fnd-001.yaml'
    before = path.read_bytes()
    publish = transaction.publish
    injected = False

    def edit_then_publish(*args, **kwargs):
        nonlocal injected
        injected = True
        if source == 'task':
            task_path = fixed / 'current-task.yaml'
            task = yaml.safe_load(task_path.read_text())
            task['task']['title'] = 'operator title'
            task_path.write_text(yaml.safe_dump(task))
        elif source == 'receipt':
            (fixed / 'evidence/fresh.json').write_bytes(b'operator receipt bytes')
        else:
            (fixed.parent / 'product_edit.py').write_text('changed_again = True\n')
        return publish(*args, **kwargs)

    monkeypatch.setattr(transaction, 'publish', edit_then_publish)
    assert controlplane.cmd_finding_refresh_proof('FND-001', 'fresh.json') == 2
    assert injected
    assert path.read_bytes() == before
    assert not list((fixed / '.transactions').iterdir())


def test_refresh_process_death_is_recoverable_without_receipt_edits(fixed):
    from harness import transaction_recovery
    from harness.telemetry_lock import telemetry_lock

    before = (fixed / 'findings/fnd-001.yaml').read_bytes()
    receipts = tree(fixed / 'evidence')
    script = '''
import os
from harness import controlplane, publication_fs
original = publication_fs.exchange
def killed(*args):
    result = original(*args)
    if 'fnd-001.yaml' in args:
        os._exit(91)
    return result
publication_fs.exchange = killed
controlplane.cmd_finding_refresh_proof('FND-001', 'fresh.json')
os._exit(92)
'''
    result = subprocess.run([sys.executable, '-c', script], cwd=fixed.parent,
                            env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')},
                            capture_output=True, text=True, check=False, timeout=25)
    assert result.returncode == 91, result.stderr
    with telemetry_lock(fixed):
        transaction_recovery.recover_pending_publications(fixed)
    assert (fixed / 'findings/fnd-001.yaml').read_bytes() == before
    assert tree(fixed / 'evidence') == receipts


def test_same_reference_change_between_reads_is_not_adopted(fixed, monkeypatch):
    from harness import source_access

    monkeypatch.chdir(fixed.parent)
    read = source_access.read_regular_bytes_beneath
    target = fixed / 'evidence/green.json'
    replacement = (fixed / 'evidence/fresh.json').read_bytes()
    finding = (fixed / 'findings/fnd-001.yaml').read_bytes()
    injected = False

    def read_then_change(path, root):
        nonlocal injected
        data = read(path, root)
        if path == target and not injected:
            injected = True
            target.write_bytes(replacement)
        return data

    monkeypatch.setattr(source_access, 'read_regular_bytes_beneath', read_then_change)
    assert controlplane.cmd_finding_refresh_proof('FND-001', 'green.json') == 2
    assert injected
    assert target.read_bytes() == replacement, 'command must not compensate over external receipt edit'
    assert (fixed / 'findings/fnd-001.yaml').read_bytes() == finding


def test_refresh_rejects_canonical_foreign_task_receipt(fixed):
    path = fixed / 'evidence/fresh.json'
    record = json.loads(path.read_text())
    record['task'] = 'TASK-999'
    path.write_text(json.dumps(record))
    before = tree(fixed)
    result = refresh(fixed)
    assert result.returncode == 2, result.stderr
    assert tree(fixed) == before


def test_refresh_validates_all_historical_green_references(fixed):
    first = refresh(fixed)
    assert first.returncode == 0, first.stderr
    (fixed / 'evidence/green.json').unlink()
    (fixed / 'evidence/next.json').write_bytes((fixed / 'evidence/fresh.json').read_bytes())
    before = tree(fixed)
    result = refresh(fixed, 'next.json')
    assert result.returncode == 2, result.stderr
    assert tree(fixed) == before


def test_refresh_symlink_staging_cannot_write_external_payload(fixed):
    staging = fixed / '.staging'
    assert list(staging.iterdir()) == []
    staging.rmdir()
    outside = fixed.parent / 'outside'
    outside.mkdir()
    staging.symlink_to(outside, target_is_directory=True)
    result = refresh(fixed)
    assert result.returncode == 2, result.stderr
    assert list(outside.iterdir()) == [], 'refusal must happen before any external staging write'


def test_refresh_schema_error_has_stable_refusal_without_traceback(fixed):
    path = fixed / 'findings/fnd-001.yaml'
    finding = yaml.safe_load(path.read_text())
    finding['regression_test']['green_evidence_history'] = [{'previous': 'green.json'}]
    path.write_text(yaml.safe_dump(finding))
    before = tree(fixed)
    result = refresh(fixed)
    assert result.returncode == 2, result.stderr
    assert 'FINDING_REFRESH_SCHEMA_INVALID' in result.stderr
    assert 'Traceback' not in result.stderr
    assert tree(fixed) == before

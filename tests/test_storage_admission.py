"""Store ownership and pending state must be checked before canonical task facts."""
import json

import pytest
from storage_factory import cli, fixture_store, repository


@pytest.mark.parametrize("command", [
    ("init",), ("status",), ("gate", "preflight"), ("context", "--compact"),
    ("evidence", "run", "--type", "build", "--command", "true"),
    ("task", "new", "TASK-900"), ("task", "prune"),
])
def test_unowned_store_refuses_before_task_fact_use(tmp_path, command):
    repo = repository(tmp_path)
    store = repo / ".harness-store"
    store.mkdir()
    (store / "user.txt").write_text("do not adopt")
    task = repo / ".harness/current-task.yaml"
    task.write_text("[invalid task")
    before = task.read_bytes()

    result = cli(repo, *command)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "STORE_UNOWNED" in result.stderr
    assert task.read_bytes() == before
    assert (store / "user.txt").read_text() == "do not adopt"


@pytest.mark.parametrize("command", [("init",), ("status",), ("context", "--compact"), ("gate",)])
def test_coordination_pending_precedes_absent_root_init(tmp_path, command):
    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    (store / "operations/pending.json").write_text(json.dumps({"unknown": True}))
    (repo / ".harness").rename(repo / "retained-fixture-root")

    result = cli(repo, *command)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "STORE_RECOVERY_REQUIRED" in result.stderr
    assert not (repo / ".harness").exists()
    assert (store / "operations/pending.json").is_file()


def test_nested_custom_root_is_not_admitted_as_legacy_inside_bound_workspace(tmp_path):
    from harness.storage import StorageError, admit_storage

    repo = repository(tmp_path)
    fixture_store(repo)
    nested = repo / 'nested/.harness'
    nested.mkdir(parents=True)
    (nested / 'current-task.yaml').write_text('PRIVATE_INVALID_TASK')
    with pytest.raises(StorageError, match='STORE_IDENTITY_CHANGED'):
        with admit_storage(nested):
            pytest.fail('nested root bypassed bound workspace admission')
    assert (nested / 'current-task.yaml').read_text() == 'PRIVATE_INVALID_TASK'


def test_legacy_nested_root_regular_publication_uses_shared_owner(tmp_path):
    from harness import transaction
    from harness.telemetry_lock import telemetry_lock
    from harness.transaction_recovery import publication_admission

    repo = repository(tmp_path)
    nested = repo / 'nested/.harness'
    nested.mkdir(parents=True)
    (nested / 'value.yaml').write_bytes(b'before')
    artifact = transaction.StagedArtifact('value.yaml', b'after')
    with telemetry_lock(repo / '.harness'), publication_admission(nested):
        staged = transaction.stage(nested, (artifact,))
        transaction.publish(nested, staged, replace_paths=frozenset({'value.yaml'}),
                            expected_sources={'value.yaml': b'before'}, expected_artifacts=(artifact,), durable=True)
    assert (nested / 'value.yaml').read_bytes() == b'after'
    assert not (repo / '.harness-store').exists()


@pytest.mark.parametrize('version', [1, 2])
def test_low_level_regular_prepare_cannot_overlap_directory_coordination(tmp_path, version):
    from harness import publication_journal, transaction_recovery
    from harness.storage import admit_storage
    from harness.storage.journal import prepare_turnover
    from storage_journal_factory import authority, turnover_plan

    repo = repository(tmp_path)
    fixture_store(repo)
    root = repo / '.harness'
    value = turnover_plan(repo)
    before = (root / 'gate.yaml').read_bytes()
    with admit_storage(root) as session:
        operation = prepare_turnover(session, {'plan': value, 'authority': authority(value)})
        with pytest.raises(OSError, match='STORE_RECOVERY_REQUIRED'):
            if version == 1:
                transaction_recovery.begin(root, [(root / 'gate.yaml', before, before + b'\n')])
            else:
                with publication_journal.prepare(root, (publication_journal.Member('gate.yaml', before, before + b'\n'),)):
                    pytest.fail('ordinary prepare bypassed directory coordination')
        assert not list((root / '.transactions').iterdir())
        assert operation.abort()['status'] == 'ABORTED'

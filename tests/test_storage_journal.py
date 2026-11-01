"""Coordination must preserve an unknown object, never adopt same-byte data."""
import json

import pytest
from storage_factory import fixture_store, repository


def test_regular_pending_blocks_directory_recovery_without_mutation(tmp_path):
    from harness.storage import StorageError, recover_operation

    repo = repository(tmp_path)
    fixture_store(repo)
    pending = repo / ".harness/.transactions/unknown.json"
    pending.parent.mkdir(exist_ok=True)
    pending.write_text('{"version": 999}')
    before = pending.read_bytes()
    with pytest.raises(StorageError):
        recover_operation(repo, "a" * 32)
    assert pending.read_bytes() == before


def test_ordinary_recovery_never_dispatches_activation_bootstrap(tmp_path):
    """A storage bootstrap must not enter ordinary regular-file compensation."""
    from harness.telemetry_lock import telemetry_lock
    from harness.transaction_recovery import recover_pending_publications

    repo = repository(tmp_path)
    root = repo / ".harness"
    pending = root / ".transactions" / ("a" * 32 + ".json")
    pending.parent.mkdir(exist_ok=True)
    pending.write_text(json.dumps({"version": 3, "kind": "storage_activation"}))
    before = pending.read_bytes()
    with telemetry_lock(root), pytest.raises(OSError, match="STORE_RECOVERY_REQUIRED"):
        recover_pending_publications(root)
    assert pending.read_bytes() == before
    assert not (repo / ".harness-store").exists()


def test_bootstrap_is_durable_before_first_store_object(tmp_path):
    from harness.storage.journal import prepare_activation
    from harness.telemetry_lock import telemetry_lock
    from storage_journal_factory import OP, activation_plan, authority

    repo = repository(tmp_path)
    value = activation_plan(repo)
    with telemetry_lock(repo / ".harness"):
        operation = prepare_activation(repo / ".harness", value, authority(value))
        descriptor = repo / ".harness/.transactions" / ("storage-activation-" + OP + ".json")
        assert json.loads(descriptor.read_bytes())["kind"] == "storage_activation"
        assert not (repo / value["actions"][0]["target"]).exists()
        operation.advance(value["actions"][0])
        assert (repo / value["actions"][0]["target"]).stat().st_mode & 0o777 == 0o700
        result = operation.abort()
    assert result["status"] == "ABORTED"
    assert not (repo / ".harness-store").exists()
    assert not descriptor.exists()
    assert list((repo / result["receipt"]).parent.glob("quarantine/*"))


def test_turnover_abort_restores_original_inodes_and_preserves_candidate(tmp_path):
    from harness.storage import admit_storage
    from harness.storage.journal import prepare_turnover
    from storage_factory import identity
    from storage_journal_factory import OP, authority, turnover_plan

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    before = identity(repo / ".harness")
    value = turnover_plan(repo)
    candidate_id = identity(store / "retained/roots" / OP / "candidate")
    with admit_storage(repo / ".harness") as session:
        operation = prepare_turnover(session, {"plan": value, "authority": authority(value)})
        for entry in value["actions"]:
            operation.advance(entry)
        assert identity(repo / ".harness") == candidate_id
        result = operation.abort()
    assert result["status"] == "ABORTED"
    assert identity(repo / ".harness") == before
    assert identity(store / "retained/roots" / OP / "candidate") == candidate_id
    assert not list((store / "operations").iterdir())


def test_committed_operation_finishes_never_aborts(tmp_path):
    from harness.storage import StorageError, admit_storage, recover_operation
    from harness.storage.journal import prepare_turnover
    from storage_factory import identity
    from storage_journal_factory import OP, authority, turnover_plan

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    value = turnover_plan(repo)
    candidate_id = identity(store / "retained/roots" / OP / "candidate")
    with admit_storage(repo / ".harness") as session:
        operation = prepare_turnover(session, {"plan": value, "authority": authority(value)})
        for entry in value["actions"]:
            operation.advance(entry)
        result = operation.commit()
        with pytest.raises(StorageError):
            operation.abort()
    assert result["status"] == "COMMITTED"
    assert recover_operation(repo, OP)["status"] == "COMMITTED"
    assert identity(repo / ".harness") == candidate_id


def test_unknown_inode_with_identical_bytes_is_not_owned(tmp_path):
    import shutil

    from harness.storage import StorageError, admit_storage
    from harness.storage.journal import prepare_turnover
    from storage_factory import identity
    from storage_journal_factory import authority, turnover_plan

    repo = repository(tmp_path)
    fixture_store(repo)
    value = turnover_plan(repo)
    with admit_storage(repo / ".harness") as session:
        operation = prepare_turnover(session, {"plan": value, "authority": authority(value)})
        operation.advance(value["actions"][0])
        previous = repo / value["actions"][0]["target"]
        parked = previous.with_name("parked")
        previous.rename(parked)
        shutil.copytree(parked, previous)
        unknown_id = identity(previous)
        with pytest.raises(StorageError, match="STORE_IDENTITY_CHANGED"):
            operation.abort()
        assert identity(previous) == unknown_id
        assert parked.is_dir()
        assert not (repo / ".harness").exists()


def test_metadata_read_ignores_access_time_but_not_content_change(tmp_path, monkeypatch):
    """Reading immutable metadata may update atime, never its content token."""
    import os

    from harness.storage import StorageError
    from harness.storage.journal import _read

    repo = repository(tmp_path)
    metadata = repo / "record.json"
    metadata.write_bytes(b'{"known":true}')
    parent = os.open(repo, os.O_RDONLY | os.O_DIRECTORY)
    original = os.read
    changed = False

    def read_updates_atime(fd, size):
        nonlocal changed
        result = original(fd, size)
        if not changed:
            info = os.fstat(fd)
            os.utime(fd, ns=(info.st_atime_ns + 1_000_000_000, info.st_mtime_ns))
            changed = True
        return result

    # Kernel atime update itself does not update ctime. Simulate that read-time
    # observation while preserving every other stat field.
    real_fstat = os.fstat
    calls = 0

    def atime_only(fd):
        nonlocal calls
        info = real_fstat(fd)
        calls += 1
        if calls == 2:
            from types import SimpleNamespace

            fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            fields["st_atime"] += 1
            fields["st_atime_ns"] += 1_000_000_000
            return SimpleNamespace(**fields)
        return info

    try:
        monkeypatch.setattr(os, "fstat", atime_only)
        assert _read(parent, "record.json") == b'{"known":true}'
        monkeypatch.setattr(os, "fstat", real_fstat)
        monkeypatch.setattr(os, "read", read_updates_atime)
        with pytest.raises(StorageError, match="STORE_IDENTITY_CHANGED"):
            _read(parent, "record.json")
    finally:
        os.close(parent)


@pytest.mark.parametrize("damage", ["frame-bytes", "frame-gap", "frame-symlink", "parent-substitution", "unknown-target"])
def test_drift_never_restores_over_unknown_objects(tmp_path, damage):
    from harness.storage import StorageError, admit_storage, recover_operation
    from harness.storage.journal import prepare_turnover
    from storage_journal_factory import OP, authority, turnover_plan

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    value = turnover_plan(repo)
    with admit_storage(repo / ".harness") as session:
        operation = prepare_turnover(session, {"plan": value, "authority": authority(value)})
        operation.advance(value["actions"][0])
    frames = store / "receipts" / ("storage-" + OP)
    if damage == "frame-bytes":
        frame = frames / "00000001.json"
        document = json.loads(frame.read_bytes())
        document["previous_hash"] = "0" * 64
        frame.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")))
    elif damage == "frame-gap":
        (frames / "00000001.json").rename(frames / "00000003.json")
    elif damage == "frame-symlink":
        (frames / "00000001.json").rename(frames / "parked.json")
        (frames / "00000001.json").symlink_to(frames / "parked.json")
    elif damage == "parent-substitution":
        roots = store / "retained/roots"
        roots.rename(roots.with_name("parked-roots"))
        roots.mkdir()
    else:
        (repo / ".harness").mkdir()
        (repo / ".harness/user-data").write_text("preserve")
    before = (store / "operations" / (OP + ".json")).read_bytes()
    with pytest.raises(StorageError):
        recover_operation(repo, OP)
    assert (store / "operations" / (OP + ".json")).read_bytes() == before
    if damage == "unknown-target":
        assert (repo / ".harness/user-data").read_text() == "preserve"
    assert not list(store.glob("quarantine/*"))


def test_descriptor_plan_tampering_cannot_expand_recovery_scope(tmp_path):
    from harness.storage import StorageError, admit_storage, recover_operation
    from harness.storage.journal import prepare_turnover
    from storage_journal_factory import OP, authority, turnover_plan

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    value = turnover_plan(repo)
    with admit_storage(repo / ".harness") as session:
        operation = prepare_turnover(session, {"plan": value, "authority": authority(value)})
        operation.advance(value["actions"][0])
    descriptor = store / "operations" / (OP + ".json")
    document = json.loads(descriptor.read_bytes())
    document["plan"]["scope_digest"] = "0" * 64
    # Updating the frame chain alone cannot bless a different authorized plan.
    import hashlib

    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    descriptor.write_bytes(raw)
    previous = hashlib.sha256(raw).hexdigest()
    for path in sorted((store / "receipts" / ("storage-" + OP)).glob("[0-9]*.json")):
        frame = json.loads(path.read_bytes())
        frame["previous_hash"] = previous
        raw = json.dumps(frame, sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(raw)
        previous = hashlib.sha256(raw).hexdigest()
    with pytest.raises(StorageError, match="STORE_PLAN_STALE"):
        recover_operation(repo, OP)
    assert descriptor.is_file()
    assert not (repo / ".harness").exists()


def test_unsupported_platform_refuses_before_storage_creation(tmp_path, monkeypatch):
    from harness import publication_fs
    from harness.storage.journal import prepare_activation
    from harness.telemetry_lock import telemetry_lock
    from storage_journal_factory import activation_plan, authority

    repo = repository(tmp_path)
    value = activation_plan(repo)
    with telemetry_lock(repo / ".harness"):
        monkeypatch.setattr(publication_fs.sys, "platform", "unsupported-fixture")
        with pytest.raises(publication_fs.PublicationUnsupported):
            prepare_activation(repo / ".harness", value, authority(value))
    assert not (repo / ".harness-store").exists()
    assert not list((repo / ".harness/.transactions").glob("*.json"))


def test_changed_plan_and_missing_owner_never_begin(tmp_path):
    from harness.storage import StorageError
    from harness.storage.journal import prepare_activation
    from harness.telemetry_lock import telemetry_lock
    from storage_journal_factory import activation_plan, authority

    repo = repository(tmp_path)
    value = activation_plan(repo)
    with pytest.raises(OSError, match="publication lock required"):
        prepare_activation(repo / ".harness", value, authority(value))
    grant = authority(value)
    value["actions"].clear()
    with telemetry_lock(repo / ".harness"), pytest.raises(StorageError, match="STORE_PLAN_STALE"):
        prepare_activation(repo / ".harness", value, grant)
    assert not (repo / ".harness-store").exists()


def test_descriptor_cleanup_does_not_mask_primary_refusal(tmp_path, monkeypatch):
    import os

    from harness.storage import StorageError, admit_storage
    from harness.storage.journal import prepare_turnover
    from storage_journal_factory import authority, turnover_plan

    repo = repository(tmp_path)
    fixture_store(repo)
    value = turnover_plan(repo)
    with admit_storage(repo / ".harness") as session:
        operation = prepare_turnover(session, {"plan": value, "authority": authority(value)})
        close = os.close
        failed = False

        def close_then_fail(fd):
            nonlocal failed
            close(fd)
            import sys

            if not failed and isinstance(sys.exception(), StorageError):
                failed = True
                raise OSError("TEST_SECONDARY_CLOSE")

        with monkeypatch.context() as patch:
            patch.setattr(os, "close", close_then_fail)
            with pytest.raises(StorageError, match="STORE_IDENTITY_CHANGED"):
                operation.advance({"not": "next action"})
        assert failed
        assert operation.abort()["status"] == "ABORTED"


def test_cross_device_move_refusal_preserves_source_and_recovers_intent(tmp_path, monkeypatch):
    import errno

    from harness import publication_fs
    from harness.storage import admit_storage, recover_operation
    from harness.storage.journal import prepare_turnover
    from storage_factory import identity
    from storage_journal_factory import OP, authority, turnover_plan

    repo = repository(tmp_path)
    fixture_store(repo)
    original = identity(repo / ".harness")
    value = turnover_plan(repo)
    move = publication_fs.move_noreplace

    def refuse_source(srcfd, src, dstfd, dst):
        if src == ".harness":
            raise publication_fs.PublicationUnsupported(errno.EXDEV, "PUBLICATION_UNSUPPORTED")
        return move(srcfd, src, dstfd, dst)

    with admit_storage(repo / ".harness") as session:
        operation = prepare_turnover(session, {"plan": value, "authority": authority(value)})
        with monkeypatch.context() as patch:
            patch.setattr(publication_fs, "move_noreplace", refuse_source)
            with pytest.raises(publication_fs.PublicationUnsupported):
                operation.advance(value["actions"][0])
        assert identity(repo / ".harness") == original
    assert recover_operation(repo, OP)["status"] == "ABORTED"
    assert identity(repo / ".harness") == original


def test_held_file_descriptor_remains_on_original_root_object(tmp_path):
    from harness.storage import admit_storage
    from harness.storage.journal import prepare_turnover
    from storage_factory import identity
    from storage_journal_factory import OP, authority, turnover_plan

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    payload = repo / ".harness/held.txt"
    payload.write_bytes(b"before")
    payload.chmod(0o640)
    original = identity(payload)
    value = turnover_plan(repo)
    with payload.open("ab") as held, admit_storage(repo / ".harness") as session:
        operation = prepare_turnover(session, {"plan": value, "authority": authority(value)})
        for entry in value["actions"]:
            operation.advance(entry)
        held.write(b"-after")
        held.flush()
        previous = store / "retained/roots" / OP / "previous/held.txt"
        assert previous.read_bytes() == b"before-after"
        assert identity(previous) == original
        assert previous.stat().st_mode & 0o777 == 0o640
        operation.abort()
    assert identity(payload) == original
    assert payload.read_bytes() == b"before-after"


@pytest.mark.parametrize("invalid", ["early-commit", "wrong-next", "duplicate-step"])
def test_illegal_progress_leaves_recorded_generation_recoverable(tmp_path, invalid):
    from harness.storage import StorageError, admit_storage
    from harness.storage.journal import prepare_turnover
    from storage_journal_factory import authority, turnover_plan

    repo = repository(tmp_path)
    fixture_store(repo)
    value = turnover_plan(repo)
    with admit_storage(repo / ".harness") as session:
        operation = prepare_turnover(session, {"plan": value, "authority": authority(value)})
        if invalid == "duplicate-step":
            operation.advance(value["actions"][0])
        with pytest.raises(StorageError):
            if invalid == "early-commit":
                operation.commit()
            else:
                operation.advance(value["actions"][0 if invalid == "duplicate-step" else 1])
        assert operation.abort()["status"] == "ABORTED"
    assert (repo / ".harness/current-task.yaml").is_file()


def test_owned_snapshot_copy_preserves_source_and_records_new_member_identity(tmp_path):
    import hashlib

    from harness.storage import StorageError, admit_storage
    from harness.storage.journal import prepare_turnover
    from storage_factory import identity
    from storage_journal_factory import OP, action, authority, plan

    repo = repository(tmp_path)
    store, _, _ = fixture_store(repo)
    (store / 'retained/roots' / OP).mkdir()
    source = repo / '.harness/gate.yaml'
    before = identity(source), source.read_bytes()
    entry = action('copy', f'.harness-store/retained/roots/{OP}/copied.yaml',
                   source='.harness/gate.yaml', node_identity=before[0],
                   sha256=hashlib.sha256(before[1]).hexdigest())
    value = plan(repo, [entry], bound=True)
    error = None
    with admit_storage(repo / '.harness') as session:
        try:
            operation = prepare_turnover(session, {'plan': value, 'authority': authority(value)})
            operation.advance(entry)
        except StorageError as caught:
            error = caught.code
        assert error is None, error
        target = repo / entry['target']
        assert target.read_bytes() == before[1]
        assert identity(target) != before[0]
        assert (identity(source), source.read_bytes()) == before
        assert target.stat().st_mode & 0o777 == 0o600
        assert operation.abort()['status'] == 'ABORTED'


def test_regular_and_directory_operations_cannot_overlap(tmp_path):
    from harness.storage import StorageError
    from harness.storage.journal import prepare_activation
    from harness.telemetry_lock import telemetry_lock
    from storage_journal_factory import activation_plan, authority

    repo = repository(tmp_path)
    root = repo / ".harness"
    pending = root / ".transactions/pending.json"
    pending.parent.mkdir(exist_ok=True)
    pending.write_text('{"version":999}')
    value = activation_plan(repo)
    with telemetry_lock(root), pytest.raises(StorageError, match="STORE_RECOVERY_REQUIRED"):
        prepare_activation(root, value, authority(value))
    assert pending.read_text() == '{"version":999}'
    assert not (repo / ".harness-store").exists()
